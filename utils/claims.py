"""Claim decisions: approve, reject, and the security-desk handover.

Used by both the finder's review page and the admin panel, so the rules live in one place.
"""
from datetime import timedelta

from flask import current_app, url_for
from pymongo import ReturnDocument

from extensions import mongo
from utils import mailer
from utils.helpers import as_utc, utcnow
from utils.notifications import notify
from utils.otp import check_otp_hash, generate_otp, hash_otp

HANDOVER = "handover"


def history_entry(action, by=None, note=None):
    return {"at": utcnow(), "action": action, "by": by, "note": note}


def pending_count(item_id):
    return mongo.db.claims.count_documents({"item_id": item_id, "status": "pending"})


def close_pending_claims(item, by=None, note="This item is no longer available."):
    """Close pending claims without a trust penalty (item returned or removed)."""
    others = list(mongo.db.claims.find({"item_id": item["_id"], "status": "pending"}, {"claimant_id": 1}))
    if not others:
        return 0
    now = utcnow()
    mongo.db.claims.update_many(
        {"_id": {"$in": [o["_id"] for o in others]}, "status": "pending"},
        {
            "$set": {"status": "closed", "reviewed_at": now},
            "$push": {"history": history_entry("closed", by, note)},
        },
    )
    for other in others:
        notify(
            other["claimant_id"],
            f"Your claim for “{item['title']}” was closed. {note}",
            "claim",
            _claim_url(other["_id"]),
        )
    return len(others)


def can_review(user, claim, item):
    """Admins review any pending claim. The finder reviews only when it's the item's only
    pending claim; two or more claims make it "disputed" and only an admin decides."""
    if claim["status"] != "pending" or item["status"] != "open":
        return False
    if user.is_admin:
        return True
    is_finder = item["posted_by"] == user.oid and claim["claimant_id"] != user.oid
    return is_finder and pending_count(item["_id"]) == 1


def _new_handover_code(claim_id):
    code = generate_otp()
    fields = {
        "handover_otp_hash": hash_otp(code, purpose=HANDOVER, subject=str(claim_id)),
        "handover_expires_at": utcnow() + timedelta(days=current_app.config["HANDOVER_OTP_DAYS"]),
        "handover_attempts": 0,
    }
    return code, fields


def _item_url(item_id, external=False):
    try:
        return url_for("items.detail", item_id=str(item_id), _external=external)
    except RuntimeError:
        return f"/items/{item_id}"

def _claim_url(claim_id, external=False):
    try:
        return url_for("claims.detail", claim_id=str(claim_id), _external=external)
    except RuntimeError:
        return f"/claims/{claim_id}"


def approve_claim(claim, item, reviewer, note=None):
    now = utcnow()
    db = mongo.db
    # Lock the item first, so two reviewers can't approve two different claims.
    locked = db.items.update_one({"_id": item["_id"], "status": "open"}, {"$set": {"status": "claimed", "updated_at": now}})
    if not locked.modified_count:
        return False, "This item is no longer open for claims."

    code, handover_fields = _new_handover_code(claim["_id"])
    updated = db.claims.update_one(
        {"_id": claim["_id"], "status": "pending"},
        {
            "$set": {"status": "approved", "reviewed_by": reviewer.oid, "reviewed_at": now,
                     "review_note": note, **handover_fields},
            "$push": {"history": history_entry("approved", reviewer.oid, note)},
        },
    )
    if not updated.modified_count:
        db.items.update_one({"_id": item["_id"], "status": "claimed"}, {"$set": {"status": "open"}})
        return False, "This claim was already reviewed."

    # Other pending claims on the same item are closed, without a trust penalty.
    others = list(db.claims.find({"item_id": item["_id"], "status": "pending"}, {"claimant_id": 1}))
    if others:
        db.claims.update_many(
            {"_id": {"$in": [o["_id"] for o in others]}, "status": "pending"},
            {
                "$set": {"status": "closed", "reviewed_at": now},
                "$push": {"history": history_entry("closed", reviewer.oid, "Another claim for this item was approved.")},
            },
        )
        for other in others:
            notify(other["claimant_id"],
                   f"Your claim for “{item['title']}” was closed because another claim was approved.",
                   "claim", _claim_url(other["_id"]))

    claimant = db.users.find_one({"_id": claim["claimant_id"]})
    if claimant:
        notify(claimant["_id"],
               f"Your claim for “{item['title']}” was approved. Your handover code has been emailed. "
               "Collect the item at the security desk with your college ID.",
               "claim", _claim_url(claim["_id"]))
        mailer.send_handover_otp(claimant["email"], claimant["name"], item, code,
                                 handover_fields["handover_expires_at"], _claim_url(claim["_id"], external=True))

    finder = db.users.find_one({"_id": item["posted_by"]})
    if finder and finder["_id"] != reviewer.oid:
        notify(finder["_id"], f"A claim for your found item “{item['title']}” was approved.",
               "claim", _item_url(item["_id"]))
    if finder and item.get("held_at") != "security_desk":
        cfg = current_app.config
        mailer.send_claim_status(
            finder["email"], finder["name"], "Please drop the item at the security desk",
            f"A claim for “{item['title']}” was approved. If you still have the item, please hand it to "
            f"{cfg['SECURITY_DESK_LOCATION']} ({cfg['SECURITY_DESK_HOURS']}) so the owner can collect it.",
            status="approved",
            cta_url=_item_url(item["_id"], external=True), cta_label="View item",
        )
    return True, "Claim approved. The claimant has been emailed a handover code."


def reject_claim(claim, item, reviewer, note=None):
    cfg = current_app.config
    db = mongo.db
    updated = db.claims.update_one(
        {"_id": claim["_id"], "status": "pending"},
        {
            "$set": {"status": "rejected", "reviewed_by": reviewer.oid, "reviewed_at": utcnow(), "review_note": note},
            "$push": {"history": history_entry("rejected", reviewer.oid, note)},
        },
    )
    if not updated.modified_count:
        return False, "This claim was already reviewed."

    # Fake-claim penalty: lower the trust score and count the rejection (in one atomic update).
    claimant = db.users.find_one_and_update(
        {"_id": claim["claimant_id"]},
        [{"$set": {
            "rejected_claims": {"$add": [{"$ifNull": ["$rejected_claims", 0]}, 1]},
            "trust_score": {"$max": [0, {"$subtract": [{"$ifNull": ["$trust_score", 100]}, cfg["TRUST_PENALTY"]]}]},
        }}],
        return_document=ReturnDocument.AFTER,
    )
    if claimant:
        notify(claimant["_id"], f"Your claim for “{item['title']}” was rejected.", "claim",
               _claim_url(claim["_id"]))
        mailer.send_claim_status(
            claimant["email"], claimant["name"], "Your claim was not approved",
            f"Your claim for “{item['title']}” was reviewed and rejected. "
            f"Your trust score is now {claimant['trust_score']}.",
            status="rejected", note=note,
            cta_url=_claim_url(claim["_id"], external=True), cta_label="View claim",
        )
        if claimant["rejected_claims"] >= cfg["MAX_REJECTED_CLAIMS"]:
            notify(claimant["_id"],
                   f"You've had {cfg['MAX_REJECTED_CLAIMS']} claims rejected, so you can no longer submit claims. "
                   "Contact the admin office if you think this is a mistake.", "security")
    return True, "Claim rejected."


def complete_handover(claim, item, admin, code):
    """The owner tells the desk their code and shows their ID; the admin enters the code."""
    cfg = current_app.config
    db = mongo.db
    now = utcnow()
    if claim["status"] != "approved":
        return False, "Only approved claims can be handed over."
    expires = as_utc(claim.get("handover_expires_at"))
    if expires and expires <= now:
        return False, "This handover code has expired. Send the claimant a new code."

    doc = db.claims.find_one_and_update(
        {"_id": claim["_id"], "status": "approved", "handover_attempts": {"$lt": cfg["OTP_MAX_ATTEMPTS"]}},
        {"$inc": {"handover_attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return False, "Too many wrong codes. Send the claimant a new handover code."
    if not check_otp_hash(code, doc.get("handover_otp_hash"), purpose=HANDOVER, subject=str(claim["_id"])):
        left = cfg["OTP_MAX_ATTEMPTS"] - doc["handover_attempts"]
        if left <= 0:
            return False, "Wrong handover code. No attempts left: send the claimant a new code."
        return False, f"Wrong handover code. {left} attempt{'s' if left != 1 else ''} left."

    db.claims.update_one(
        {"_id": claim["_id"], "status": "approved"},
        {
            "$set": {"status": "completed", "handover_completed_at": now, "handover_by": admin.oid, "id_checked": True},
            "$unset": {"handover_otp_hash": ""},
            "$push": {"history": history_entry(
                "handover_completed", admin.oid,
                "Owner showed their college ID and the handover code at the security desk.")},
        },
    )
    db.items.update_one(
        {"_id": item["_id"]},
        {"$set": {"status": "returned", "held_at": "returned", "returned_at": now,
                  "returned_to": claim["claimant_id"], "handover_claim_id": claim["_id"], "updated_at": now}},
    )
    db.users.update_one(
        {"_id": claim["claimant_id"]},
        [{"$set": {"trust_score": {"$min": [100, {"$add": [{"$ifNull": ["$trust_score", 100]}, cfg["TRUST_REWARD"]]}]}}}],
    )

    try:
        item_url = _item_url(item["_id"], external=True)
    except RuntimeError:
        item_url = f"/items/{item['_id']}"
    for user_id, role in ((claim["claimant_id"], "owner"), (item["posted_by"], "finder")):
        user = db.users.find_one({"_id": user_id})
        if not user:
            continue
        if role == "owner":
            message = f"You collected “{item['title']}” from the security desk. Glad it's back with you!"
        else:
            message = f"“{item['title']}”, the item you found, is back with its owner. Thank you for reporting it!"
        notify(user_id, message, "handover", _item_url(item["_id"]))
        mailer.send_claim_status(user["email"], user["name"], "Item returned", message,
                                 status="completed", cta_url=item_url, cta_label="View item")
    return True, "Handover complete. The item is now marked as returned."


def resend_handover_code(claim, item, admin):
    if claim["status"] != "approved":
        return False, "Only approved claims have a handover code."
    code, fields = _new_handover_code(claim["_id"])
    mongo.db.claims.update_one(
        {"_id": claim["_id"], "status": "approved"},
        {"$set": fields, "$push": {"history": history_entry("handover_code_resent", admin.oid)}},
    )
    claimant = mongo.db.users.find_one({"_id": claim["claimant_id"]})
    if claimant:
        mailer.send_handover_otp(claimant["email"], claimant["name"], item, code, fields["handover_expires_at"],
                                 _claim_url(claim["_id"], external=True))
    return True, "A new handover code was emailed to the claimant. The old code no longer works."
