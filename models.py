"""The logged-in user wrapper used by Flask-Login."""
import secrets

from bson import ObjectId
from bson.errors import InvalidId
from flask import current_app
from flask_login import UserMixin

from extensions import login_manager, mongo


class User(UserMixin):
    def __init__(self, doc):
        self.doc = doc
        self.id = str(doc["_id"])

    def get_id(self):
        # The session token is part of the login cookie. Rotating it in the database
        # (password reset, ban) instantly logs out every old session and "remember me" cookie.
        return f"{self.id}:{self.doc.get('session_token', '')}"

    @property
    def oid(self):
        return self.doc["_id"]

    @property
    def name(self):
        return self.doc.get("name", "")

    @property
    def first_name(self):
        return self.name.split(" ")[0] if self.name else ""

    @property
    def email(self):
        return self.doc.get("email", "")

    @property
    def is_admin(self):
        return self.doc.get("role") == "admin"

    @property
    def trust_score(self):
        return self.doc.get("trust_score", 100)

    @property
    def rejected_claims(self):
        return self.doc.get("rejected_claims", 0)

    @property
    def can_claim(self):
        return self.rejected_claims < current_app.config["MAX_REJECTED_CLAIMS"]

    @property
    def is_active(self):
        return not self.doc.get("is_banned", False)


@login_manager.user_loader
def load_user(user_id):
    try:
        raw_id, token = user_id.split(":", 1)
        oid = ObjectId(raw_id)
    except (ValueError, InvalidId, TypeError):
        return None
    doc = mongo.db.users.find_one({"_id": oid})
    if not doc or not doc.get("is_verified") or doc.get("is_banned"):
        return None
    if not secrets.compare_digest(doc.get("session_token", ""), token):
        return None
    return User(doc)
