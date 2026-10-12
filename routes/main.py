"""Landing page, dashboard, notifications and profile."""
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user

from extensions import mongo
from forms import ChangePasswordForm, ProfileForm
from models import User
from routes.auth import check_password, hash_password
from utils.helpers import page_arg, paginate, utcnow
from utils.matcher import find_matches
from utils.validators import parse_object_id

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    db = mongo.db
    stats = {
        "reported": db.items.count_documents({"status": {"$ne": "removed"}}),
        "returned": db.items.count_documents({"status": "returned"}),
        "users": db.users.count_documents({"is_verified": True}),
    }
    recent_found = list(db.items.find({"type": "found", "status": "open"}).sort("created_at", -1).limit(6))
    return render_template("main/landing.html", stats=stats, recent_found=recent_found)


@bp.route("/dashboard")
@login_required
def dashboard():
    db = mongo.db
    me = current_user.oid
    my_items = list(db.items.find({"posted_by": me, "status": {"$ne": "removed"}}).sort("created_at", -1).limit(50))
    counts = {
        "lost": sum(1 for i in my_items if i["type"] == "lost"),
        "found": sum(1 for i in my_items if i["type"] == "found"),
        "returned": sum(1 for i in my_items if i["status"] == "returned"),
        "claims": db.claims.count_documents({"claimant_id": me}),
    }

    my_claims = list(db.claims.find({"claimant_id": me}).sort("created_at", -1).limit(5))
    claim_items = {i["_id"]: i for i in db.items.find({"_id": {"$in": [c["item_id"] for c in my_claims]}})}

    # Claims waiting on me as the finder.
    my_found_ids = [i["_id"] for i in my_items if i["type"] == "found" and i["status"] == "open"]
    incoming = list(db.claims.find({"item_id": {"$in": my_found_ids}, "status": "pending"}).sort("created_at", -1))
    found_by_id = {i["_id"]: i for i in my_items}

    # Likely matches for my open lost items.
    match_groups = []
    for item in [i for i in my_items if i["type"] == "lost" and i["status"] == "open"][:3]:
        matches = find_matches(item, limit=3)
        if matches:
            match_groups.append((item, matches))

    return render_template(
        "main/dashboard.html",
        my_items=my_items,
        counts=counts,
        my_claims=my_claims,
        claim_items=claim_items,
        incoming=incoming,
        found_by_id=found_by_id,
        match_groups=match_groups,
    )


# --- Notifications -------------------------------------------------------------------


@bp.route("/notifications")
@login_required
def notifications():
    result = paginate(mongo.db.notifications, {"user_id": current_user.oid}, page_arg(request), 20)
    return render_template("main/notifications.html", result=result)


@bp.route("/notifications/<notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    oid = parse_object_id(notification_id)
    mongo.db.notifications.update_one({"_id": oid, "user_id": current_user.oid}, {"$set": {"is_read": True}})
    unread = mongo.db.notifications.count_documents({"user_id": current_user.oid, "is_read": False})
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(ok=True, unread=unread)
    return redirect(url_for("main.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    mongo.db.notifications.update_many({"user_id": current_user.oid, "is_read": False}, {"$set": {"is_read": True}})
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(ok=True, unread=0)
    flash("All notifications marked as read.", "success")
    return redirect(url_for("main.notifications"))


# --- Profile ---------------------------------------------------------------------------


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileForm(prefix="profile", data={"name": current_user.name})
    password_form = ChangePasswordForm(prefix="pw")
    users = mongo.db.users

    if request.method == "POST" and request.form.get("action") == "profile":
        if profile_form.validate_on_submit():
            users.update_one({"_id": current_user.oid}, {"$set": {"name": profile_form.name.data}})
            flash("Profile updated.", "success")
            return redirect(url_for("main.profile"))

    elif request.method == "POST" and request.form.get("action") == "password":
        if password_form.validate_on_submit():
            if not check_password(password_form.current_password.data, current_user.doc["password_hash"]):
                password_form.current_password.errors.append("Your current password is incorrect.")
            else:
                doc = users.find_one_and_update(
                    {"_id": current_user.oid},
                    {"$set": {"password_hash": hash_password(password_form.password.data),
                              "session_token": secrets.token_urlsafe(24), "password_changed_at": utcnow()}},
                    return_document=True,
                )
                login_user(User(doc))  # keep this browser logged in; every other session is logged out
                flash("Password changed. You've been logged out everywhere else.", "success")
                return redirect(url_for("main.profile"))

    stats = {
        "posts": mongo.db.items.count_documents({"posted_by": current_user.oid, "status": {"$ne": "removed"}}),
        "claims": mongo.db.claims.count_documents({"claimant_id": current_user.oid}),
        "returned": mongo.db.items.count_documents({"posted_by": current_user.oid, "status": "returned"}),
    }
    return render_template("main/profile.html", profile_form=profile_form, password_form=password_form, stats=stats)
