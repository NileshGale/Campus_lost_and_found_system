"""One-time passwords for registration, password reset and item handover.

* Codes come from Python's `secrets` module (cryptographically secure), not `random`.
* Only an HMAC-SHA256 hash is stored, keyed with SECRET_KEY. A leaked database alone
  is not enough to recover a code.
* The hash also covers the purpose, so a registration code can never reset a password.
* MongoDB's TTL index deletes expired OTP documents; we also check expiry in code
  because the TTL cleaner only runs about once a minute.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from flask import current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions import mongo
from utils.helpers import as_utc, utcnow

PURPOSES = ("register", "reset")


def generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code, *, purpose, subject):
    key = current_app.config["SECRET_KEY"].encode()
    message = f"{purpose}:{subject}:{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def check_otp_hash(code, stored_hash, *, purpose, subject):
    if not code or not stored_hash:
        return False
    return hmac.compare_digest(hash_otp(code, purpose=purpose, subject=subject), stored_hash)


def cooldown_remaining(email, purpose):
    """Seconds until a new code may be sent for this email + purpose (0 = now)."""
    doc = mongo.db.otps.find_one({"email": email, "purpose": purpose}, {"last_sent_at": 1, "expires_at": 1})
    if not doc:
        return 0
    now = utcnow()
    if as_utc(doc["expires_at"]) <= now:
        return 0
    elapsed = (now - as_utc(doc["last_sent_at"])).total_seconds()
    return max(0, int(current_app.config["OTP_RESEND_COOLDOWN"] - elapsed + 0.999))


def issue_otp(email, purpose):
    """Create or replace the OTP for email + purpose.

    Returns (code, wait_seconds). `code` is None while the 60-second resend
    cooldown is still running. The update is atomic, so two quick clicks can't
    both send a code.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"Unknown OTP purpose: {purpose}")
    cfg = current_app.config
    now = utcnow()
    code = generate_otp()
    try:
        mongo.db.otps.update_one(
            {
                "email": email,
                "purpose": purpose,
                "$or": [
                    {"last_sent_at": {"$lte": now - timedelta(seconds=cfg["OTP_RESEND_COOLDOWN"])}},
                    {"expires_at": {"$lte": now}},
                ],
            },
            {
                "$set": {
                    "otp_hash": hash_otp(code, purpose=purpose, subject=email),
                    "attempts": 0,
                    "created_at": now,
                    "last_sent_at": now,
                    "expires_at": now + timedelta(minutes=cfg["OTP_EXPIRY_MINUTES"]),
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        # A recent code exists, so the filter didn't match and the upsert hit the unique index.
        return None, max(1, cooldown_remaining(email, purpose))
    return code, 0


def check_code(email, purpose, code):
    """Check a code. Returns (ok, status, attempts_left).

    status is one of "ok", "invalid", "locked" (5 wrong tries) or "expired".
    Every guess uses up one attempt *before* comparing, atomically, so parallel
    requests can't get extra guesses.
    """
    max_attempts = current_app.config["OTP_MAX_ATTEMPTS"]
    now = utcnow()
    doc = mongo.db.otps.find_one_and_update(
        {"email": email, "purpose": purpose, "attempts": {"$lt": max_attempts}, "expires_at": {"$gt": now}},
        {"$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        existing = mongo.db.otps.find_one({"email": email, "purpose": purpose})
        if existing and existing.get("attempts", 0) >= max_attempts and as_utc(existing["expires_at"]) > now:
            return False, "locked", 0
        return False, "expired", 0

    if check_otp_hash(code, doc["otp_hash"], purpose=purpose, subject=email):
        mongo.db.otps.delete_one({"_id": doc["_id"]})
        return True, "ok", 0

    left = max_attempts - doc["attempts"]
    return False, ("locked" if left <= 0 else "invalid"), max(0, left)
