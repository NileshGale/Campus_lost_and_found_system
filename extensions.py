"""Shared extension objects, created once and attached to the app in app.py."""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from pymongo import ASCENDING, DESCENDING, MongoClient

csrf = CSRFProtect()
mail = Mail()
login_manager = LoginManager()
limiter = Limiter(get_remote_address)


def user_or_ip():
    """Rate-limit logged-in actions per account, since a whole campus can share one IP."""
    if current_user and current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


class Mongo:
    """Holds the PyMongo client. Use `mongo.db.<collection>` anywhere in the app."""

    def __init__(self):
        self.client = None
        self.db = None

    def init_app(self, app):
        # tz_aware=True returns every datetime as timezone-aware UTC.
        self.client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=5000, tz_aware=True)
        self.db = self.client.get_default_database(default="lostfound")
        app.extensions["mongo"] = self


mongo = Mongo()


def ensure_indexes(db):
    """Create indexes (safe to run many times)."""
    db.users.create_index("email", unique=True)
    # TTL: unverified sign-ups disappear automatically. Verified users don't have this field.
    db.users.create_index("unverified_expires_at", expireAfterSeconds=0)

    # One active OTP per email + purpose; MongoDB deletes it once expires_at passes.
    db.otps.create_index([("email", ASCENDING), ("purpose", ASCENDING)], unique=True)
    db.otps.create_index("expires_at", expireAfterSeconds=0)

    db.items.create_index([("type", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])
    db.items.create_index([("posted_by", ASCENDING), ("created_at", DESCENDING)])

    # A user can claim the same item only once.
    db.claims.create_index([("item_id", ASCENDING), ("claimant_id", ASCENDING)], unique=True)
    db.claims.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db.claims.create_index([("claimant_id", ASCENDING), ("created_at", DESCENDING)])

    db.notifications.create_index([("user_id", ASCENDING), ("is_read", ASCENDING), ("created_at", DESCENDING)])
