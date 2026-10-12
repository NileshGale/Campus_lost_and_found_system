"""Reporting, browsing and viewing lost / found items."""
import re
from datetime import datetime, time, timezone

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory,
                   url_for)
from flask_login import current_user, login_required

from extensions import limiter, mongo, user_or_ip
from forms import CATEGORIES, FoundItemForm, LostItemForm
from utils.claims import pending_count
from utils.helpers import page_arg, paginate, utcnow
from utils.matcher import find_matches, notify_matches
from utils.uploads import UploadError, private_path, save_item_image
from utils.validators import parse_object_id

bp = Blueprint("items", __name__, url_prefix="/items")


def get_item_or_404(item_id):
    item = mongo.db.items.find_one({"_id": parse_object_id(item_id)})
    if not item:
        abort(404)
    if item["status"] == "removed" and not (current_user.is_admin or item["posted_by"] == current_user.oid):
        abort(404)
    return item


def _to_datetime(d):
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


@bp.route("/report/<kind>", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"], key_func=user_or_ip)
def report(kind):
    if kind not in ("lost", "found"):
        abort(404)
    form = FoundItemForm() if kind == "found" else LostItemForm()

    if request.method == "GET":
        form.date.data = utcnow().date()
        # "I found this" from a lost post: copy over the title and category.
        source_id = request.args.get("from")
        if kind == "found" and source_id:
            source = mongo.db.items.find_one({"_id": parse_object_id(source_id), "type": "lost", "status": "open"})
            if source:
                form.title.data = source["title"]
                form.category.data = source["category"]

    if form.validate_on_submit():
        image_id = None
        if form.photo.data:
            try:
                image_id = save_item_image(form.photo.data, blur=(kind == "found"))
            except UploadError as exc:
                form.photo.errors.append(str(exc))
                return render_template("items/report.html", form=form, kind=kind,
                                       locations=current_app.config["CAMPUS_LOCATIONS"])

        now = utcnow()
        doc = {
            "type": kind,
            "title": form.title.data,
            "category": form.category.data,
            "description": form.description.data,
            "location": form.location.data,
            "date": _to_datetime(form.date.data),
            "image_id": image_id,
            "status": "open",
            "posted_by": current_user.oid,
            "created_at": now,
            "updated_at": now,
        }
        if kind == "found":
            doc["hidden_details"] = form.hidden_details.data
            doc["verification_questions"] = form.verification_questions()
            doc["held_at"] = form.held_at.data
        doc["_id"] = mongo.db.items.insert_one(doc).inserted_id

        found = notify_matches(doc)
        if found:
            flash(f"Posted! We found {found} possible match{'es' if found > 1 else ''}. See them below.", "success")
        else:
            flash("Posted! We'll email you if a matching item shows up.", "success")
        return redirect(url_for("items.detail", item_id=str(doc["_id"])))

    return render_template("items/report.html", form=form, kind=kind,
                           locations=current_app.config["CAMPUS_LOCATIONS"])


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@bp.route("/")
@bp.route("/browse")
@login_required
def browse():
    args = request.args
    filters = {
        "q": args.get("q", "").strip()[:100],
        "type": args.get("type") if args.get("type") in ("lost", "found") else "",
        "category": args.get("category") if args.get("category") in CATEGORIES else "",
        "location": args.get("location", "").strip()[:60],
        "date_from": args.get("date_from", ""),
        "date_to": args.get("date_to", ""),
        "status": args.get("status") if args.get("status") in ("open", "all") else "open",
    }

    query = {"status": "open"} if filters["status"] == "open" else {"status": {"$in": ["open", "claimed", "returned"]}}
    if filters["type"]:
        query["type"] = filters["type"]
    if filters["category"]:
        query["category"] = filters["category"]
    if filters["location"]:
        query["location"] = {"$regex": re.escape(filters["location"]), "$options": "i"}
    date_range = {}
    if _parse_date(filters["date_from"]):
        date_range["$gte"] = _parse_date(filters["date_from"])
    if _parse_date(filters["date_to"]):
        date_range["$lte"] = _parse_date(filters["date_to"])
    if date_range:
        query["date"] = date_range
    if filters["q"]:
        # Every word must appear somewhere. re.escape stops users from injecting regex patterns.
        words = filters["q"].split()[:6]
        query["$and"] = [
            {"$or": [{field: {"$regex": re.escape(word), "$options": "i"}}
                     for field in ("title", "description", "location", "category")]}
            for word in words
        ]

    result = paginate(mongo.db.items, query, page_arg(request), 12)
    return render_template("items/browse.html", result=result, filters=filters, categories=CATEGORIES)


@bp.route("/<item_id>")
@login_required
def detail(item_id):
    item = get_item_or_404(item_id)
    db = mongo.db
    is_owner = item["posted_by"] == current_user.oid
    is_admin = current_user.is_admin

    claims = []
    if item["type"] == "found" and (is_owner or is_admin):
        claims = list(db.claims.find({"item_id": item["_id"]}).sort("created_at", 1))
    my_claim = db.claims.find_one({"item_id": item["_id"], "claimant_id": current_user.oid})
    matches = find_matches(item) if is_owner and item["status"] == "open" else []
    poster = db.users.find_one({"_id": item["posted_by"]}, {"name": 1, "email": 1}) if is_admin else None

    can_claim = (
        item["type"] == "found" and item["status"] == "open" and not is_owner and not my_claim
        and not is_admin and current_user.can_claim
    )
    return render_template(
        "items/detail.html",
        item=item,
        is_owner=is_owner,
        is_admin=is_admin,
        claims=claims,
        pending=pending_count(item["_id"]) if item["type"] == "found" else 0,
        my_claim=my_claim,
        matches=matches,
        poster=poster,
        can_claim=can_claim,
        can_see_photo=_can_see_original(item, is_owner, is_admin),
    )


def _can_see_original(item, is_owner, is_admin):
    if not item.get("image_id"):
        return False
    if item["type"] == "lost" or is_owner or is_admin:
        return True
    # The approved owner of a found item may see the full photo.
    return bool(mongo.db.claims.find_one(
        {"item_id": item["_id"], "claimant_id": current_user.oid, "status": {"$in": ["approved", "completed"]}}
    ))


@bp.route("/<item_id>/photo")
@login_required
def photo(item_id):
    item = get_item_or_404(item_id)
    is_owner = item["posted_by"] == current_user.oid
    if not _can_see_original(item, is_owner, current_user.is_admin):
        abort(403)
    folder, filename = private_path("items", item["image_id"])
    if not folder:
        abort(404)
    response = send_from_directory(folder, filename, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/<item_id>/resolve", methods=["POST"])
@login_required
def resolve(item_id):
    """The owner of a lost post got it back some other way."""
    item = get_item_or_404(item_id)
    if item["posted_by"] != current_user.oid or item["type"] != "lost" or item["status"] != "open":
        abort(403)
    mongo.db.items.update_one({"_id": item["_id"]},
                              {"$set": {"status": "returned", "returned_at": utcnow(), "updated_at": utcnow()}})
    flash("Great news! The post is marked as returned.", "success")
    return redirect(url_for("items.detail", item_id=item_id))


@bp.route("/<item_id>/delete", methods=["POST"])
@login_required
def delete(item_id):
    item = get_item_or_404(item_id)
    if item["posted_by"] != current_user.oid or item["status"] != "open":
        abort(403)
    if pending_count(item["_id"]):
        flash("This item has pending claims, so it can't be deleted. Contact the admin office.", "error")
        return redirect(url_for("items.detail", item_id=item_id))
    mongo.db.items.update_one(
        {"_id": item["_id"]},
        {"$set": {"status": "removed", "removed_reason": "Deleted by the poster", "removed_by": current_user.oid,
                  "updated_at": utcnow()}},
    )
    flash("Post deleted.", "success")
    return redirect(url_for("main.dashboard"))

