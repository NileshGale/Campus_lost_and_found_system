"""Server-side validation and clean-up of user input."""
import re
from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from flask import abort, current_app, request

MAX_PASSWORD_CHARS = 64

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_email(email):
    return (email or "").strip().lower()


def is_college_email(email):
    """True only for addresses on an allowed college domain (or its subdomains)."""
    email = normalize_email(email)
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if not local or not domain:
        return False
    for allowed in current_app.config["ALLOWED_EMAIL_DOMAINS"]:
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def password_problems(password):
    """Return the list of password rules that are not met (empty list = strong enough)."""
    password = password or ""
    problems = []
    if len(password) < 8:
        problems.append("be at least 8 characters long")
    if len(password) > MAX_PASSWORD_CHARS or len(password.encode("utf-8")) > 72:
        problems.append(f"be at most {MAX_PASSWORD_CHARS} characters long")
    if not re.search(r"[A-Z]", password):
        problems.append("include an uppercase letter")
    if not re.search(r"[0-9]", password):
        problems.append("include a number")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        problems.append("include a special character (like ! @ # $ %)")
    return problems


def clean_text(value):
    """Multi-line text: strip control characters, normalise newlines, trim."""
    if not isinstance(value, str):
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL_CHARS.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def clean_line(value):
    """Single-line text: strip control characters and collapse whitespace."""
    if not isinstance(value, str):
        return value
    value = _CONTROL_CHARS.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_object_id(value):
    """Turn a URL id into an ObjectId, or show 404 for anything malformed."""
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        abort(404)


def is_safe_redirect(target):
    """Only allow redirects to paths on this site (blocks open-redirect attacks)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc


def back_url(default):
    """Where the user came from, but only if it's a page on this site."""
    ref = urlparse(request.referrer or "")
    if ref.netloc == request.host and ref.path.startswith("/"):
        target = ref.path + (f"?{ref.query}" if ref.query else "")
        if is_safe_redirect(target):
            return target
    return default


def mask_email(email):
    """student.name@college.edu -> st*********@college.edu"""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"
