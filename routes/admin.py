"""Admin panel. Every route uses @admin_required, which is checked on the server."""
import re
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from extensions import mongo
from forms import HandoverForm, RemoveItemForm
from routes.claims import get_claim_and_item
from utils.claims import complete_handover, history_entry, resend_handover_code
from utils.decorators import admin_required
from utils.helpers import page_arg, paginate, utcnow
from utils.notifications import notify
from utils.validators import back_url, parse_object_id

bp = Blueprint("admin", __name__, url_prefix="/admin")

CLAIM_TABS = ["pending", "disputed", "approved", "completed", "rejected", "closed", "all"]


def _disputed_item_ids():
    pipeline = [
        {"$match": {"status": "pending"}},
        {"$group": {"_id": "$item_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]
    return [row["_id"] for row in mongo.db.claims.aggregate(pipeline)]


def _lookup(claims):
    items = {i["_id"]: i for i in mongo.db.items.find({"_id": {"$in": [c["item_id"] for c in claims]}})}
    users = {u["_id"]: u for u in mongo.db.users.find(
        {"_id": {"$in": [c["claimant_id"] for c in claims]}}, {"name": 1, "email": 1, "trust_score": 1})}
    return items, users


@bp.route("/")
@admin_required
def index():
    db = mongo.db
    stats = {
        "users": db.users.count_documents({"is_verified": True}),
        "banned": db.users.count_documents({"is_banned": True}),
        "open_lost": db.items.count_documents({"type": "lost", "status": "open"}),
        "open_found": db.items.count_documents({"type": "found", "status": "open"}),
        "returned": db.items.count_documents({"status": "returned"}),
        "pending": db.claims.count_documents({"status": "pending"}),
        "disputed": len(_disputed_item_ids()),
        "awaiting_handover": db.claims.count_documents({"status": "approved"}),
    }
    recent = list(db.claims.find().sort("created_at", -1).limit(8))
    items, users = _lookup(recent)
    return render_template("admin/index.html", stats=stats, recent=recent, items=items, users=users)


@bp.route("/claims")
@admin_required
def claims():
    status = request.args.get("status", "pending")
    if status not in CLAIM_TABS:
        status = "pending"
    disputed_ids = _disputed_item_ids()
    if status == "all":
        query = {}
    elif status == "disputed":
        query = {"status": "pending", "item_id": {"$in": disputed_ids}}
    else:
        query = {"status": status}
    result = paginate(mongo.db.claims, query, page_arg(request), 25)
    items, users = _lookup(result["docs"])
    return render_template("admin/claims.html", result=result, status=status, tabs=CLAIM_TABS,
                           items=items, users=users, disputed_ids=set(disputed_ids))


@bp.route("/handover")
@admin_required
def handover():
    """The security desk's queue: approved claims waiting to be collected."""
    q = request.args.get("q", "").strip()[:80]
    query = {"status": "approved"}
    if q:
        matching = [u["_id"] for u in mongo.db.users.find(
            {"$or": [{"email": {"$regex": re.escape(q), "$options": "i"}},
                     {"name": {"$regex": re.escape(q), "$options": "i"}}]}, {"_id": 1})]
        query["claimant_id"] = {"$in": matching}
    claims_list = list(mongo.db.claims.find(query).sort("reviewed_at", 1))
    items, users = _lookup(claims_list)
    return render_template("admin/handover.html", claims=claims_list, items=items, users=users, q=q)


@bp.route("/claims/<claim_id>/handover", methods=["POST"])
@admin_required
def complete(claim_id):
    claim, item = get_claim_and_item(claim_id)
    form = HandoverForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
        return redirect(url_for("claims.detail", claim_id=claim_id))
    ok, message = complete_handover(claim, item, current_user, form.code.data)
    flash(message, "success" if ok else "error")
    return redirect(url_for("claims.detail", claim_id=claim_id))


@bp.route("/claims/<claim_id>/resend-code", methods=["POST"])
@admin_required
def resend_code(claim_id):
    claim, item = get_claim_and_item(claim_id)
    ok, message = resend_handover_code(claim, item, current_user)
    flash(message, "success" if ok else "error")
    return redirect(url_for("claims.detail", claim_id=claim_id))


# --- Items -------------------------------------------------------------------------------


@bp.route("/items")
@admin_required
def items():
    args = request.args
    query = {}
    status = args.get("status", "")
    if status in ("open", "claimed", "returned", "removed"):
        query["status"] = status
    kind = args.get("type", "")
    if kind in ("lost", "found"):
        query["type"] = kind
    q = args.get("q", "").strip()[:80]
    if q:
        query["$or"] = [{"title": {"$regex": re.escape(q), "$options": "i"}},
                        {"description": {"$regex": re.escape(q), "$options": "i"}}]
    result = paginate(mongo.db.items, query, page_arg(request), 25)
    posters = {u["_id"]: u for u in mongo.db.users.find(
        {"_id": {"$in": [i["posted_by"] for i in result["docs"]]}}, {"name": 1, "email": 1})}
    return render_template("admin/items.html", result=result, posters=posters,
                           filters={"status": status, "type": kind, "q": q}, remove_form=RemoveItemForm())


@bp.route("/items/<item_id>/remove", methods=["POST"])
@admin_required
def remove_item(item_id):
    item = mongo.db.items.find_one({"_id": parse_object_id(item_id)})
    if not item:
        abort(404)
    form = RemoveItemForm()
    if not form.validate_on_submit():
        flash("Give a short reason for removing the post.", "error")
        return redirect(back_url(url_for("admin.items")))
    if item["status"] not in ("open", "claimed"):
        flash("Only open or claimed posts can be removed.", "error")
        return redirect(url_for("admin.items"))
    now = utcnow()
    mongo.db.items.update_one({"_id": item["_id"]}, {"$set": {
        "status": "removed", "removed_reason": form.reason.data, "removed_by": current_user.oid,
        "previous_status": item["status"], "updated_at": now}})
    affected = list(mongo.db.claims.find({"item_id": item["_id"], "status": {"$in": ["pending", "approved"]}}))
    if affected:
        mongo.db.claims.update_many(
            {"_id": {"$in": [c["_id"] for c in affected]}},
            {"$set": {"status": "closed"},
             "$push": {"history": history_entry("closed", current_user.oid, "The post was removed by an admin.")}},
        )
        for claim in affected:
            notify(claim["claimant_id"], f"Your claim for “{item['title']}” was closed because the post "
                                         "was removed.", "claim")
    notify(item["posted_by"], f"Your post “{item['title']}” was removed by an admin. Reason: "
                              f"{form.reason.data}", "system")
    flash("Post removed.", "success")
    return redirect(back_url(url_for("admin.items")))


@bp.route("/items/<item_id>/restore", methods=["POST"])
@admin_required
def restore_item(item_id):
    result = mongo.db.items.update_one(
        {"_id": parse_object_id(item_id), "status": "removed"},
        {"$set": {"status": "open", "updated_at": utcnow()}, "$unset": {"removed_reason": "", "removed_by": ""}},
    )
    flash("Post restored." if result.modified_count else "Nothing to restore.", "success")
    return redirect(back_url(url_for("admin.items")))


@bp.route("/items/<item_id>/received", methods=["POST"])
@admin_required
def mark_received(item_id):
    mongo.db.items.update_one({"_id": parse_object_id(item_id), "type": "found"},
                              {"$set": {"held_at": "security_desk", "updated_at": utcnow()}})
    flash("Marked as received at the security desk.", "success")
    return redirect(back_url(url_for("admin.items")))


# --- Users ---------------------------------------------------------------------------------


@bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip()[:80]
    query = {}
    if q:
        query["$or"] = [{"email": {"$regex": re.escape(q), "$options": "i"}},
                        {"name": {"$regex": re.escape(q), "$options": "i"}}]
    result = paginate(mongo.db.users, query, page_arg(request), 25)
    return render_template("admin/users.html", result=result, q=q)


def _target_user(user_id):
    user = mongo.db.users.find_one({"_id": parse_object_id(user_id)})
    if not user:
        abort(404)
    if user["_id"] == current_user.oid or user.get("role") == "admin":
        flash("Admins can't be banned or changed from here.", "error")
        return None
    return user


@bp.route("/users/<user_id>/ban", methods=["POST"])
@admin_required
def ban(user_id):
    user = _target_user(user_id)
    if user:
        # A new session token logs the user out immediately.
        mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {
            "is_banned": True, "banned_at": utcnow(), "banned_by": current_user.oid,
            "session_token": secrets.token_urlsafe(24)}})
        flash(f"{user['name']} is banned and has been logged out.", "success")
    return redirect(back_url(url_for("admin.users")))


@bp.route("/users/<user_id>/unban", methods=["POST"])
@admin_required
def unban(user_id):
    user = _target_user(user_id)
    if user:
        mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"is_banned": False}})
        notify(user["_id"], "Your account has been restored.", "system")
        flash(f"{user['name']} is no longer banned.", "success")
    return redirect(back_url(url_for("admin.users")))


@bp.route("/users/<user_id>/unblock-claims", methods=["POST"])
@admin_required
def unblock_claims(user_id):
    user = _target_user(user_id)
    if user:
        mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"rejected_claims": 0}})
        notify(user["_id"], "An admin reset your rejected-claims count. You can submit claims again.", "system")
        flash(f"{user['name']} can submit claims again.", "success")
    return redirect(back_url(url_for("admin.users")))
