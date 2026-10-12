"""Items, uploads, matching, claims and the security-desk handover."""
import os
import re
from io import BytesIO

from conftest import jpeg, new_admin, new_user, post_found, post_lost
from extensions import mongo


def _item(title=None):
    query = {"title": title} if title else {}
    return mongo.db.items.find_one(query, sort=[("created_at", -1)])


def test_found_item_photo_is_blurred_and_details_hidden(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder, photo=(jpeg(), "wallet.jpg"))
    item = _item()
    assert item["image_id"]
    assert os.path.exists(os.path.join(app.config["PUBLIC_UPLOAD_FOLDER"], item["image_id"] + ".jpg"))
    assert os.path.exists(os.path.join(app.config["PRIVATE_UPLOAD_FOLDER"], "items", item["image_id"] + ".jpg"))

    stranger, _ = new_user(app, outbox, "Stranger")
    page = stranger.get(f"/items/{item['_id']}").data
    assert b"Black leather wallet" in page
    assert b"Brown inner lining" not in page and b"Expected answer" not in page
    assert stranger.get(f"/items/{item['_id']}/photo").status_code == 403
    assert finder.get(f"/items/{item['_id']}/photo").status_code == 200


def test_uploads_must_be_real_images_under_5mb(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    response = post_found(finder, photo=(BytesIO(b"#!/bin/sh\necho hacked"), "evil.jpg"))
    assert b"isn&#39;t a valid image" in response.data
    response = post_found(finder, photo=(BytesIO(b"%PDF-1.4"), "bill.pdf"))
    assert b"Only JPG, PNG or WEBP" in response.data
    response = post_found(finder, photo=(BytesIO(b"\xff" * (5 * 1024 * 1024 + 10)), "huge.jpg"))
    assert b"5 MB" in response.data
    assert mongo.db.items.count_documents({}) == 0


def test_found_item_needs_question_and_answer_together(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    response = post_found(finder, q2="Which card is inside?", a2="")
    assert b"Fill in both the question and its answer" in response.data


def test_matching_alerts_both_people(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder)
    owner, _ = new_user(app, outbox, "Owner")
    response = post_lost(owner)
    assert b"possible match" in response.data

    subjects = [m.subject for m in outbox]
    assert sum(1 for s in subjects if s.startswith("Possible match")) == 2
    assert mongo.db.notifications.count_documents({"type": "match"}) == 2


def test_unrelated_items_do_not_match(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder)
    owner, _ = new_user(app, outbox, "Owner")
    response = post_lost(owner, title="Casio calculator", category="Electronics",
                         description="Grey scientific calculator with my name scratched on it.", location="Canteen")
    assert b"We&#39;ll email you if a matching item shows up" in response.data


def _claim(client, item_id, answer="Brown", proof=True):
    data = {"answer_0": answer, "details": "My black wallet with a metro card and a brown lining.", "confirm": "y"}
    if proof:
        data["proofs"] = [(jpeg(), "bill.jpg")]
    return client.post(f"/claims/new/{item_id}", data=data, content_type="multipart/form-data", follow_redirects=True)


def test_full_claim_and_handover_flow(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder)
    item = _item()
    owner, _ = new_user(app, outbox, "Owner")

    # The claim form shows the question but never the finder's answer.
    form_page = owner.get(f"/claims/new/{item['_id']}").data
    assert b"What colour is the inside of the wallet?" in form_page
    assert b"Brown" not in form_page

    assert b"Claim submitted" in _claim(owner, item["_id"]).data
    claim = mongo.db.claims.find_one()
    assert claim["status"] == "pending" and len(claim["proof_files"]) == 1

    # Finder sees answers side by side and approves.
    review_page = finder.get(f"/claims/{claim['_id']}").data
    assert b"Expected (private)" in review_page
    assert owner.get(f"/claims/{claim['_id']}/proof/{claim['proof_files'][0]}").status_code == 200
    stranger, _ = new_user(app, outbox, "Stranger")
    assert stranger.get(f"/claims/{claim['_id']}").status_code == 404

    finder.post(f"/claims/{claim['_id']}/review", data={"decision": "approve", "note": "Matches."})
    claim = mongo.db.claims.find_one()
    assert claim["status"] == "approved" and claim["handover_otp_hash"]
    assert _item()["status"] == "claimed"
    handover_mail = next(m for m in outbox if m.subject.startswith("Your claim was approved"))
    code = re.search(r"Handover code: (\d{6})", handover_mail.body).group(1)
    assert code not in str(claim)

    # Security desk: wrong code fails, right code + ID check completes the handover.
    admin = new_admin(app)
    wrong = "000000" if code != "000000" else "111111"
    response = admin.post(f"/admin/claims/{claim['_id']}/handover", data={"code": wrong, "id_checked": "y"},
                          follow_redirects=True)
    assert b"Wrong handover code" in response.data
    response = admin.post(f"/admin/claims/{claim['_id']}/handover", data={"code": code}, follow_redirects=True)
    assert b"Check the college ID card" in response.data
    response = admin.post(f"/admin/claims/{claim['_id']}/handover", data={"code": code, "id_checked": "y"},
                          follow_redirects=True)
    assert b"Handover complete" in response.data

    claim = mongo.db.claims.find_one()
    assert claim["status"] == "completed" and "handover_otp_hash" not in claim
    assert [h["action"] for h in claim["history"]] == ["submitted", "approved", "handover_completed"]
    item = _item()
    assert item["status"] == "returned" and item["returned_to"] == claim["claimant_id"]


def test_three_rejections_block_claiming(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    for n in range(4):
        post_found(finder, title=f"Wallet number {n}")
    claimant, email = new_user(app, outbox, "Faker")
    items = list(mongo.db.items.find().sort("created_at", 1))

    for item in items[:3]:
        _claim(claimant, item["_id"], answer="Red", proof=False)
        claim = mongo.db.claims.find_one({"item_id": item["_id"]})
        finder.post(f"/claims/{claim['_id']}/review", data={"decision": "reject"})

    user = mongo.db.users.find_one({"email": email})
    assert user["rejected_claims"] == 3 and user["trust_score"] == 40
    response = claimant.get(f"/claims/new/{items[3]['_id']}", follow_redirects=True)
    assert b"can no longer submit claims" in response.data
    assert mongo.db.claims.count_documents({"item_id": items[3]["_id"]}) == 0


def test_disputed_item_is_decided_by_admin(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder)
    item = _item()
    first, _ = new_user(app, outbox, "First")
    second, _ = new_user(app, outbox, "Second")
    _claim(first, item["_id"])
    _claim(second, item["_id"], answer="Black")
    claim_one, claim_two = list(mongo.db.claims.find().sort("created_at", 1))

    response = finder.post(f"/claims/{claim_one['_id']}/review", data={"decision": "approve"}, follow_redirects=True)
    assert b"an admin decides" in response.data
    assert mongo.db.claims.find_one({"_id": claim_one["_id"]})["status"] == "pending"

    admin = new_admin(app)
    assert b"Disputed" in admin.get("/admin/claims?status=disputed").data
    admin.post(f"/claims/{claim_one['_id']}/review", data={"decision": "approve"})
    assert mongo.db.claims.find_one({"_id": claim_one["_id"]})["status"] == "approved"
    # The other claimant is closed without a trust penalty.
    assert mongo.db.claims.find_one({"_id": claim_two["_id"]})["status"] == "closed"
    assert mongo.db.users.find_one({"_id": claim_two["claimant_id"]})["trust_score"] == 100


def test_cannot_claim_own_item_or_twice(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder)
    item = _item()
    assert finder.get(f"/claims/new/{item['_id']}").status_code == 403
    owner, _ = new_user(app, outbox, "Owner")
    _claim(owner, item["_id"])
    response = _claim(owner, item["_id"])
    assert b"already claimed" in response.data
    assert mongo.db.claims.count_documents({}) == 1


def test_search_handles_special_characters(app, outbox):
    user, _ = new_user(app, outbox, "Asha")
    post_found(user)
    assert user.get("/items/browse?q=(.*").status_code == 200
    response = user.get("/items/browse?q=leather+wallet&type=found")
    assert b"Black leather wallet" in response.data
    assert user.get("/items/not-an-id").status_code == 404


def test_all_pages_render(app, outbox):
    finder, _ = new_user(app, outbox, "Finder")
    post_found(finder, photo=(jpeg(), "w.jpg"))
    owner, _ = new_user(app, outbox, "Owner")
    post_lost(owner)
    item = _item("Black leather wallet")
    _claim(owner, item["_id"])
    claim = mongo.db.claims.find_one()
    admin = new_admin(app)

    for client, url in [
        (owner, "/"), (owner, "/dashboard"), (owner, "/items/browse"), (owner, "/items/report/lost"),
        (owner, "/items/report/found"), (owner, f"/items/{item['_id']}"), (owner, "/claims/mine"),
        (owner, f"/claims/{claim['_id']}"), (owner, "/notifications"), (owner, "/profile"),
        (finder, "/dashboard"), (finder, f"/items/{item['_id']}"), (finder, f"/claims/{claim['_id']}"),
        (admin, "/admin/"), (admin, "/admin/claims"), (admin, "/admin/claims?status=all"), (admin, "/admin/handover"),
        (admin, "/admin/items"), (admin, "/admin/users"), (admin, f"/claims/{claim['_id']}"),
        (admin, f"/items/{item['_id']}"),
    ]:
        response = client.get(url)
        assert response.status_code == 200, url
