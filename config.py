"""App settings. Secrets and college details are read from the .env file."""
import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    raw = os.environ.get(name) or default
    return [part.strip() for part in raw.split(",") if part.strip()]


class Config:
    # --- Core ---------------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    DEBUG = env_bool("FLASK_DEBUG")
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/lostfound")

    # --- College details shown around the site ----------------------------
    APP_NAME = os.environ.get("APP_NAME", "Campus Lost & Found")
    COLLEGE_NAME = os.environ.get("COLLEGE_NAME", "Your College Name")
    ALLOWED_EMAIL_DOMAINS = [
        d.lower().lstrip("@") for d in env_list("ALLOWED_EMAIL_DOMAINS", "yourcollege.edu.in")
    ]
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
    CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "")
    SECURITY_DESK_LOCATION = os.environ.get(
        "SECURITY_DESK_LOCATION", "Main Security Office, Ground Floor, Admin Block"
    )
    SECURITY_DESK_HOURS = os.environ.get("SECURITY_DESK_HOURS", "Mon-Sat, 9:00 AM - 5:00 PM")
    CAMPUS_LOCATIONS = env_list(
        "CAMPUS_LOCATIONS",
        "Library,Canteen,Main Gate,Parking Area,Auditorium,Sports Ground,Hostel,"
        "Computer Lab,Admin Block,Classroom Block",
    )
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")

    # --- Email: Gmail SMTP on port 587 with TLS ---------------------------------
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "").strip()
    # Google shows app passwords in groups of four ("abcd efgh ..."); the spaces aren't part of it.
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "").replace(" ", "")
    MAIL_DEFAULT_SENDER = (
        (os.environ.get("MAIL_SENDER_NAME") or APP_NAME, MAIL_USERNAME) if MAIL_USERNAME else None
    )
    MAIL_ASYNC = True  # send in a background thread so pages don't wait for Gmail

    # --- Cookies and sessions -------------------------------------------------
    SESSION_COOKIE_NAME = "lf_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 2 * 60 * 60

    # --- Uploads --------------------------------------------------------------
    MAX_IMAGE_BYTES = 5 * 1024 * 1024
    MAX_PROOF_FILES = 3
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # whole request (a claim can carry 3 photos)
    PUBLIC_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    PRIVATE_UPLOAD_FOLDER = os.path.join(BASE_DIR, "private_uploads")

    # --- Security rules -------------------------------------------------------
    BCRYPT_ROUNDS = 12
    OTP_EXPIRY_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5
    OTP_RESEND_COOLDOWN = 60  # seconds
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCK_MINUTES = 15
    UNVERIFIED_ACCOUNT_HOURS = 24  # unverified sign-ups are deleted after this
    MAX_REJECTED_CLAIMS = 3
    TRUST_PENALTY = 20
    TRUST_REWARD = 5
    HANDOVER_OTP_DAYS = 7
    MATCH_THRESHOLD = 0.30

    # --- Rate limiting (Flask-Limiter) -----------------------------------------
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    BEHIND_PROXY = env_bool("BEHIND_PROXY")
