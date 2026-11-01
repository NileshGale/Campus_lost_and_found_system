"""Registration, email verification, login/logout and password reset."""
import hashlib
import math
import secrets
from datetime import timedelta

import bcrypt
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions import limiter, mongo
from forms import ForgotPasswordForm, LoginForm, OtpForm, RegisterForm, ResetPasswordForm
from models import User
from utils import mailer
from utils.helpers import as_utc, utcnow
from utils.notifications import notify
from utils.otp import check_code, cooldown_remaining, issue_otp
from utils.validators import is_safe_redirect, mask_email, normalize_email

bp = Blueprint("auth", __name__)

# Checked against when an email doesn't exist, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12))
RESET_WINDOW = timedelta(minutes=10)


# --- Password helpers ----------------------------------------------------------


def hash_password(password):
    rounds = current_app.config["BCRYPT_ROUNDS"]
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def check_password(password, hashed):
    try:
        if isinstance(hashed, str):
            hashed = hashed.encode("utf-8")
        return bcrypt.checkpw(password.encode("utf-8"), hashed)
    except ValueError:  # e.g. a password longer than bcrypt's 72-byte limit
        return False


def _fingerprint(password_hash):
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:24]


def _start_verification(email, password_hash=None):
    """Remember, in this browser's session, which account is being verified.

    The fingerprint ties the code to the password chosen in *this* browser. If someone
    else re-registers the same unverified email meanwhile, the fingerprint changes and
    the old browser can't verify an account whose password it doesn't know.
    """
    session["verify"] = {
        "email": email,
        "fp": _fingerprint(password_hash) if password_hash else secrets.token_hex(12),
    }


def _wants_json():
    return request.is_json or request.accept_mimetypes.best == "application/json"


# --- Registration ------------------------------------------------------------------


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute; 30 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        name = form.name.data
        users = mongo.db.users
        now = utcnow()
        existing = users.find_one({"email": email})

        if existing and existing.get("is_verified"):
            # Same response as a new sign-up, so the form can't be used to discover who
            # is registered. The real owner gets an email explaining what happened.
            code, _ = issue_otp(email, "register")
            if code:
                mailer.send_account_exists(email, existing["name"], url_for("auth.login", _external=True),
                                           url_for("auth.forgot_password", _external=True))
            _start_verification(email)
        else:
            password_hash = hash_password(form.password.data)
            fields = {
                "name": name,
                "password_hash": password_hash,
                "session_token": secrets.token_urlsafe(24),
                "unverified_expires_at": now + timedelta(hours=current_app.config["UNVERIFIED_ACCOUNT_HOURS"]),
            }
            if existing:
                users.update_one({"_id": existing["_id"], "is_verified": False}, {"$set": fields})
            else:
                try:
                    users.insert_one({
                        **fields,
                        "email": email,
                        "role": "user",
                        "is_verified": False,
                        "is_banned": False,
                        "trust_score": 100,
                        "rejected_claims": 0,
                        "failed_login_attempts": 0,
                        "lock_until": None,
                        "created_at": now,
                    })
                except DuplicateKeyError:
                    flash("Something went wrong. Please try again.", "error")
                    return render_template("auth/register.html", form=form)
            code, _ = issue_otp(email, "register")
            if code:
                mailer.send_register_otp(email, name, code)
            _start_verification(email, password_hash)

        flash(f"We've emailed a 6-digit code to {mask_email(email)}. It expires in 10 minutes.", "success")
        return redirect(url_for("auth.verify_otp"))
    return render_template("auth/register.html", form=form)


@bp.route("/verify-otp", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def verify_otp():
    binding = session.get("verify")
    if not binding:
        flash("Log in to finish verifying your email.", "info")
        return redirect(url_for("auth.login"))
    email = binding["email"]
    form = OtpForm()

    if form.validate_on_submit():
        ok, status, left = check_code(email, "register", form.code.data)
        if ok:
            users = mongo.db.users
            user = users.find_one({"email": email})
            if user and not user.get("is_verified"):
                if not secrets.compare_digest(binding["fp"], _fingerprint(user["password_hash"])):
                    session.pop("verify", None)
                    flash("This sign-up was changed from another browser. Please register again.", "error")
                    return redirect(url_for("auth.register"))
                users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"is_verified": True, "verified_at": utcnow()}, "$unset": {"unverified_expires_at": ""}},
                )
            session.pop("verify", None)
            flash("Email verified. You can log in now.", "success")
            return redirect(url_for("auth.login"))
        flash(_otp_error(status, left), "error")

    return render_template(
        "auth/verify_otp.html",
        form=form,
        purpose="register",
        masked_email=mask_email(email),
        cooldown=cooldown_remaining(email, "register"),
    )


def _otp_error(status, left):
    if status == "invalid":
        return f"That code is incorrect. {left} attempt{'s' if left != 1 else ''} left."
    if status == "locked":
        return "Too many wrong attempts. Request a new code."
    return "That code has expired. Request a new code."


@bp.route("/resend-otp", methods=["POST"])
@limiter.limit("3 per minute; 10 per hour")
def resend_otp():
    data = request.get_json(silent=True) or request.form
    purpose = data.get("purpose")
    cooldown = current_app.config["OTP_RESEND_COOLDOWN"]
    users = mongo.db.users

    if purpose == "register" and session.get("verify"):
        binding = session["verify"]
        email = binding["email"]
        wait = cooldown_remaining(email, "register")
        sent = False
        if not wait:
            user = users.find_one({"email": email})
            if user and user.get("is_verified"):
                code, _ = issue_otp(email, "register")
                if code:
                    mailer.send_account_exists(email, user["name"], url_for("auth.login", _external=True),
                                               url_for("auth.forgot_password", _external=True))
            elif user and secrets.compare_digest(binding["fp"], _fingerprint(user["password_hash"])):
                code, _ = issue_otp(email, "register")
                if code:
                    mailer.send_register_otp(email, user["name"], code)
            # Same answer in every case, so this can't be used to probe accounts.
            sent, wait = True, cooldown
        redirect_to = url_for("auth.verify_otp")

    elif purpose == "reset" and session.get("reset"):
        state = session["reset"]
        elapsed = utcnow().timestamp() - state.get("last_sent", 0)
        wait = max(0, math.ceil(cooldown - elapsed))
        sent = False
        if not wait:
            user = users.find_one({"email": state["email"], "is_banned": {"$ne": True}})
            if user:
                code, _ = issue_otp(state["email"], "reset")
                if code:
                    mailer.send_reset_otp(state["email"], user["name"], code)
            state["last_sent"] = utcnow().timestamp()
            session["reset"] = state
            sent, wait = True, cooldown
        redirect_to = url_for("auth.reset_verify")

    else:
        if _wants_json():
            return jsonify(ok=False, message="Your session expired. Start again."), 400
        flash("Your session expired. Start again.", "error")
        return redirect(url_for("auth.login"))

    message = "A new code is on its way." if sent else f"Please wait {wait} seconds before asking for a new code."
    if _wants_json():
        return jsonify(ok=sent, cooldown=wait, message=message)
    flash(message, "success" if sent else "warning")
    return redirect(redirect_to)


# --- Login / logout -------------------------------------------------------------------


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        cfg = current_app.config
        users = mongo.db.users
        email = normalize_email(form.email.data)
        user = users.find_one({"email": email})
        now = utcnow()
        generic_error = "Invalid email or password."

        if not user:
            check_password(form.password.data, _DUMMY_HASH)
            flash(generic_error, "error")
            return render_template("auth/login.html", form=form)

        lock_until = as_utc(user.get("lock_until"))
        if lock_until and lock_until > now:
            minutes = math.ceil((lock_until - now).total_seconds() / 60)
            flash(f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}, "
                  "or reset your password.", "error")
            return render_template("auth/login.html", form=form)

        if not check_password(form.password.data, user["password_hash"]):
            updated = users.find_one_and_update(
                {"_id": user["_id"]}, {"$inc": {"failed_login_attempts": 1}}, return_document=ReturnDocument.AFTER
            )
            if updated["failed_login_attempts"] >= cfg["LOGIN_MAX_ATTEMPTS"]:
                users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"lock_until": now + timedelta(minutes=cfg["LOGIN_LOCK_MINUTES"]),
                              "failed_login_attempts": 0}},
                )
                flash(f"Too many failed attempts. This account is locked for {cfg['LOGIN_LOCK_MINUTES']} minutes.",
                      "error")
            else:
                flash(generic_error, "error")
            return render_template("auth/login.html", form=form)

        users.update_one({"_id": user["_id"]}, {"$set": {"failed_login_attempts": 0, "lock_until": None}})

        if user.get("is_banned"):
            flash("This account has been suspended. Contact the admin office.", "error")
            return render_template("auth/login.html", form=form)

        if not user.get("is_verified"):
            code, _ = issue_otp(email, "register")
            if code:
                mailer.send_register_otp(email, user["name"], code)
            _start_verification(email, user["password_hash"])
            flash(f"Verify your email first. We've sent a code to {mask_email(email)}.", "info")
            return redirect(url_for("auth.verify_otp"))

        next_url = request.args.get("next")
        session.clear()  # fresh session on login
        session.permanent = True
        login_user(User(user), remember=form.remember.data)
        users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now}})
        default_target = url_for("admin.index") if user.get("role") == "admin" else url_for("main.dashboard")
        return redirect(next_url if is_safe_redirect(next_url) else default_target)
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    if current_user and current_user.is_authenticated:
        mongo.db.users.update_one(
            {"_id": current_user.oid},
            {"$set": {"session_token": secrets.token_urlsafe(24)}}
        )
    logout_user()
    session.clear()
    flash("You've been logged out.", "info")
    response = redirect(url_for("main.landing"))
    response.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "lf_session"))
    response.delete_cookie("remember_token")
    return response


# --- Forgot / reset password ------------------------------------------------------------


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        user = mongo.db.users.find_one({"email": email, "is_banned": {"$ne": True}})
        if user:
            code, _ = issue_otp(email, "reset")
            if code:
                mailer.send_reset_otp(email, user["name"], code)
        # Identical response whether or not the account exists.
        session["reset"] = {"email": email, "last_sent": utcnow().timestamp(), "verified_at": None}
        flash("If an account exists for that email, we've sent a 6-digit reset code. It expires in 10 minutes.",
              "info")
        return redirect(url_for("auth.reset_verify"))
    return render_template("auth/forgot_password.html", form=form)


@bp.route("/reset-password/verify", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def reset_verify():
    state = session.get("reset")
    if not state:
        return redirect(url_for("auth.forgot_password"))
    form = OtpForm()
    if form.validate_on_submit():
        ok, _, _ = check_code(state["email"], "reset", form.code.data)
        if ok:
            state["verified_at"] = utcnow().timestamp()
            session["reset"] = state
            return redirect(url_for("auth.reset_password"))
        # Deliberately vague: the same message whether or not the account exists.
        flash("That code is incorrect or has expired. After 5 wrong attempts you'll need a new code.", "error")

    cooldown = current_app.config["OTP_RESEND_COOLDOWN"]
    wait = max(0, math.ceil(cooldown - (utcnow().timestamp() - state.get("last_sent", 0))))
    return render_template(
        "auth/verify_otp.html", form=form, purpose="reset", masked_email=mask_email(state["email"]), cooldown=wait
    )


@bp.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password():
    state = session.get("reset") or {}
    verified_at = state.get("verified_at")
    if not verified_at or utcnow().timestamp() - verified_at > RESET_WINDOW.total_seconds():
        session.pop("reset", None)
        flash("Your reset session expired. Please start again.", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = mongo.db.users.find_one_and_update(
            {"email": state["email"]},
            {
                "$set": {
                    "password_hash": hash_password(form.password.data),
                    # A new token logs out every existing session and "remember me" cookie.
                    "session_token": secrets.token_urlsafe(24),
                    "failed_login_attempts": 0,
                    "lock_until": None,
                    "is_verified": True,  # the reset code proved they own this inbox
                    "password_changed_at": utcnow(),
                },
                "$unset": {"unverified_expires_at": ""},
            },
        )
        if user:
            notify(user["_id"], "Your password was changed and all other sessions were logged out. "
                                "If this wasn't you, contact the admin office.", "security")
        logout_user()
        session.clear()
        flash("Password updated. Log in with your new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form)
