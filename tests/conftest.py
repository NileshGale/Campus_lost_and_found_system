"""Test setup. Tests need a running MongoDB and use a separate database ending in `_test`.

Run:  pytest
Use another server:  set TEST_MONGO_URI=mongodb://host:port/lostfound_test   (Windows)
"""
import os
import re
import sys
from datetime import date
from io import BytesIO

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_URI = os.environ.get("TEST_MONGO_URI", "mongodb://localhost:27017/lostfound_test")
# Set before importing app.py so the real database is never touched.
os.environ["MONGO_URI"] = TEST_URI

from PIL import Image  # noqa: E402

from app import create_app  # noqa: E402
from extensions import ensure_indexes, mail, mongo  # noqa: E402

DOMAIN = "testcollege.edu.in"
PASSWORD = "Str0ng!Pass"


@pytest.fixture
def make_app(tmp_path):
    created = []

    def factory(**overrides):
        config = {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-" + "x" * 40,
            "MONGO_URI": TEST_URI,
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "BCRYPT_ROUNDS": 4,
            "MAIL_DEFAULT_SENDER": ("Lost & Found", "noreply@example.com"),
            "ALLOWED_EMAIL_DOMAINS": [DOMAIN],
            "PUBLIC_UPLOAD_FOLDER": str(tmp_path / "public"),
            "PRIVATE_UPLOAD_FOLDER": str(tmp_path / "private"),
        }
        config.update(overrides)
        app = create_app(config)
        db = mongo.db
        assert db.name.endswith("_test"), "Tests only run against a database whose name ends in _test"
        mongo.client.drop_database(db.name)
        ensure_indexes(db)
        created.append(app)
        return app

    yield factory
    mongo.client.drop_database(mongo.db.name)


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def outbox(app):
    with mail.record_messages() as messages:
        yield messages


# --- Helpers --------------------------------------------------------------------------


def last_code(outbox):
    for message in reversed(outbox):
        match = re.search(r"\b(\d{6})\b", message.body or "")
        if match:
            return match.group(1)
    raise AssertionError("No email with a 6-digit code was sent")


def register(client, email, name="Test User", password=PASSWORD):
    return client.post(
        "/register",
        data={"name": name, "email": email, "password": password, "confirm": password},
        follow_redirects=True,
    )


def login(client, email, password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def logged_in(response):
    """True when a login ended on the dashboard."""
    return response.status_code == 200 and response.request.path == "/dashboard"


def new_user(app, outbox, name):
    """Register, verify and log in a fresh user. Returns (client, email)."""
    client = app.test_client()
    email = f"{name.lower()}@{DOMAIN}"
    register(client, email, name=name)
    client.post("/verify-otp", data={"code": last_code(outbox)}, follow_redirects=True)
    assert logged_in(login(client, email))
    return client, email


def new_admin(app, name="Admin"):
    from routes.auth import hash_password

    email = f"{name.lower()}@{DOMAIN}"
    with app.app_context():
        mongo.db.users.insert_one({
            "name": name, "email": email, "password_hash": hash_password(PASSWORD), "role": "admin",
            "is_verified": True, "is_banned": False, "trust_score": 100, "rejected_claims": 0,
            "failed_login_attempts": 0, "lock_until": None, "session_token": "admin-token",
        })
    client = app.test_client()
    assert logged_in(login(client, email))
    return client


def jpeg(size=(64, 48), colour=(20, 40, 60)):
    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG")
    buf.seek(0)
    return buf


def post_found(client, **overrides):
    data = {
        "title": "Black leather wallet",
        "category": "Wallets & Purses",
        "description": "Black leather wallet found under a table in the reading hall.",
        "location": "Library",
        "date": date.today().isoformat(),
        "held_at": "security_desk",
        "hidden_details": "Brown inner lining with a metro card inside.",
        "q1": "What colour is the inside of the wallet?",
        "a1": "Brown",
    }
    data.update(overrides)
    return client.post("/items/report/found", data=data, content_type="multipart/form-data", follow_redirects=True)


def post_lost(client, **overrides):
    data = {
        "title": "Lost my black wallet",
        "category": "Wallets & Purses",
        "description": "Black leather wallet with my college ID and a metro card.",
        "location": "Library 2nd floor",
        "date": date.today().isoformat(),
    }
    data.update(overrides)
    return client.post("/items/report/lost", data=data, content_type="multipart/form-data", follow_redirects=True)
