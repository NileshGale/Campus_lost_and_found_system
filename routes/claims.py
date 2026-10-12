"""Claims: an owner claims a found item, then the finder or an admin reviews it."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from pymongo.errors import DuplicateKeyError

from extensions import limiter, mongo, user_or_ip
from forms import HandoverForm, ReviewForm, build_claim_form
from routes.items import get_item_or_404
from utils import mailer
from utils.claims import approve_claim, can_review, history_entry, pending_count, reject_claim
from utils.helpers import utcnow
from utils.matcher import answer_similarity
from utils.notifications import notify, notify_admins
from utils.uploads import UploadError, private_path, save_proof_image
from utils.validators import parse_object_id

bp = Blueprint("claims", __name__, url_prefix="/claims")


def get_claim_and_item(claim_id):
    claim = mongo.db.claims.find_one({"_id": parse_object_id(claim_id)})
    if not claim:
        abort(404)
    item = mongo.db.items.find_one({"_id": claim["item_id"]})
    if not item:
        abort(404)
    return claim, item


def _role_for(claim, item):
    """Who is looking: 'admin', 'finder' or 'claimant'. Anyone else gets a 404."""
    if current_user.is_admin:
        return "admin"
    if item["posted_by"] == current_user.oid:
        return "finder"
    if claim["claimant_id"] == current_user.oid:
        return "claimant"
    abort(404)


@bp.route("/new/<item_id>", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"], key_func=user_or_ip)
def new(item_id):
    item = get_item_or_404(item_id)
    if item["type"] != "found" or item["status"] != "open":
        flash("This item isn't open for claims.", "error")
        return redirect(url_for("items.detail", item_id=item_id))
    if item["posted_by"] == current_user.oid or current_user.is_admin:
        abort(403)
    if not current_user.can_claim:
        flash("Your account can no longer submit claims because of rejected claims. Contact the admin office.", "error")
        return redirect(url_for("items.detail", item_id=item_id))
    existing = mongo.db.claims.find_one({"item_id": item["_id"], "claimant_id": current_user.oid})
    if existing:
        flash("You've already claimed this item.", "info")
        return redirect(url_for("claims.detail", claim_id=str(existing["_id"])))

    questions = item.get("verification_questions", [])
    form = build_claim_form(questions)
    if form.validate_on_submit():
        files = [f for f in (form.proofs.data or []) if f and f.filename]
        max_files = current_app.config["MAX_PROOF_FILES"]
        if len(files) > max_files:
            form.proofs.errors.append(f"Upload at most {max_files} images.")
        else:
            try:
                proof_ids = [save_proof_image(f) for f in files]
            except UploadError as exc:
                form.proofs.errors.append(str(exc))
                proof_ids = None
            if proof_ids is not None:
                now = utcnow()
                claim = {
                    "item_id": item["_id"],
                    "claimant_id": current_user.oid,
                    # Only the questions are copied here. The finder's answers stay on the item.
                    "answers": [{"question": q["question"], "answer": field.data}
                                for q, field in zip(questions, form.answer_fields)],
                    "details": form.details.data,
                    "proof_files": proof_ids,
                    "status": "pending",
                    "handover_otp_hash": None,
                    "reviewed_by": None,
                    "created_at": now,
                    "history": [history_entry("submitted", current_user.oid)],
                }
                try:
                    claim["_id"] = mongo.db.claims.insert_one(claim).inserted_id
                except DuplicateKeyError:
                    flash("You've already claimed this item.", "info")
                    return redirect(url_for("items.detail", item_id=item_id))
                _announce_new_claim(claim, item)
                flash("Claim submitted. You'll get an email when it's reviewed.", "success")
                return redirect(url_for("claims.detail", claim_id=str(claim["_id"])))

    return render_template("claims/claim_form.html", form=form, item=item)


def _announce_new_claim(claim, item):
    claim_url = url_for("claims.detail", claim_id=str(claim["_id"]))
    count = pending_count(item["_id"])
    finder = mongo.db.users.find_one({"_id": item["posted_by"]})
    if count > 1:
        message = (f"“{item['title']}” now has {count} claims. An admin will compare them and decide.")
        notify_admins(f"Disputed item: “{item['title']}” has {count} pending claims.", "admin",
                      url_for("admin.claims", status="disputed"))
    else:
        message = f"Someone claimed “{item['title']}”, the item you found. Please review their answers."
    if finder:
        notify(finder["_id"], message, "claim", claim_url)
        mailer.send_claim_status(finder["email"], finder["name"], "New claim on your found item", message,
                                 status="pending", cta_url=url_for("claims.detail", claim_id=str(claim["_id"]),
                                                                   _external=True),
                                 cta_label="Review the claim")


@bp.route("/mine")
@login_required
def mine():
    claims = list(mongo.db.claims.find({"claimant_id": current_user.oid}).sort("created_at", -1))
    items = {i["_id"]: i for i in mongo.db.items.find({"_id": {"$in": [c["item_id"] for c in claims]}})}
    return render_template("claims/my_claims.html", claims=claims, items=items)


@bp.route("/<claim_id>")
@login_required
def detail(claim_id):
    claim, item = get_claim_and_item(claim_id)
    role = _role_for(claim, item)

    comparisons = []
    if role in ("finder", "admin"):
        expected = {q["question"]: q["answer"] for q in item.get("verification_questions", [])}
        for pair in claim.get("answers", []):
            exp = expected.get(pair["question"], "")
            comparisons.append({**pair, "expected": exp, "similarity": answer_similarity(pair["answer"], exp)})

    claimant = mongo.db.users.find_one({"_id": claim["claimant_id"]},
                                       {"name": 1, "email": 1, "trust_score": 1, "rejected_claims": 1, "created_at": 1})
    other_claims = []
    if role == "admin":
        other_claims = list(mongo.db.claims.find({"item_id": item["_id"], "_id": {"$ne": claim["_id"]}}))
    people = {}
    actor_ids = {h.get("by") for h in claim.get("history", []) if h.get("by")}
    actor_ids |= {c["claimant_id"] for c in other_claims}
    for user in mongo.db.users.find({"_id": {"$in": list(actor_ids)}}, {"name": 1, "role": 1}):
        people[user["_id"]] = user

    return render_template(
        "claims/claim_detail.html",
        claim=claim,
        item=item,
        role=role,
        comparisons=comparisons,
        claimant=claimant,
        other_claims=other_claims,
        people=people,
        pending=pending_count(item["_id"]),
        can_review=can_review(current_user, claim, item),
        review_form=ReviewForm(),
        handover_form=HandoverForm(),
    )


@bp.route("/<claim_id>/review", methods=["POST"])
@login_required
def review(claim_id):
    claim, item = get_claim_and_item(claim_id)
    _role_for(claim, item)
    if not can_review(current_user, claim, item):
        flash("You can't review this claim. If several people claimed the item, an admin decides.", "error")
        return redirect(url_for("claims.detail", claim_id=claim_id))
    form = ReviewForm()
    decision = request.form.get("decision")
    if not form.validate_on_submit() or decision not in ("approve", "reject"):
        flash("Please choose approve or reject.", "error")
        return redirect(url_for("claims.detail", claim_id=claim_id))
    action = approve_claim if decision == "approve" else reject_claim
    ok, message = action(claim, item, current_user, form.note.data or None)
    flash(message, "success" if ok else "error")
    return redirect(url_for("claims.detail", claim_id=claim_id))


@bp.route("/<claim_id>/proof/<file_id>")
@login_required
def proof(claim_id, file_id):
    claim, item = get_claim_and_item(claim_id)
    _role_for(claim, item)
    if file_id not in claim.get("proof_files", []):
        abort(404)
    folder, filename = private_path("proofs", file_id)
    if not folder:
        abort(404)
    response = send_from_directory(folder, filename, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response
