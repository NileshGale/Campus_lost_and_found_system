"""Campus Lost & Found: entry point.

Start the site:          python app.py
Admin / helper commands: flask --app app create-admin
                         flask --app app seed-demo
                         flask --app app send-test-email you@example.com
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import Flask, has_request_context, jsonify, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import csrf, ensure_indexes, limiter, login_manager, mail, mongo
from utils.icons import icon
from utils.validators import is_college_email, mask_email, normalize_email, password_problems

STATUS_LABELS = {
    "open": "Open",
    "claimed": "Claimed",
    "returned": "Returned",
    "removed": "Removed",
    "pending": "Pending",
    "approved": "Approved",
    "rejected": "Rejected",
    "completed": "Completed",
    "closed": "Closed",
}

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    if len(app.config.get("SECRET_KEY") or "") < 32:
        raise RuntimeError(
            "SECRET_KEY is missing or too short. Copy .env.example to .env and set SECRET_KEY "
            "(see SETUP_GUIDE.md, step 8)."
        )
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    mongo.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "basic"

    import models  # noqa: F401  (registers the Flask-Login user loader)
    from routes import admin, auth, claims, items, main

    for blueprint in (main.bp, auth.bp, items.bp, claims.bp, admin.bp):
        app.register_blueprint(blueprint)

    for folder in (app.config["PUBLIC_UPLOAD_FOLDER"], app.config["PRIVATE_UPLOAD_FOLDER"]):
        os.makedirs(folder, exist_ok=True)

    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_cli(app)

    try:
        ensure_indexes(mongo.db)
    except ServerSelectionTimeoutError:
        app.logger.error(
            "\n\n  Could not connect to MongoDB at %s\n  Is MongoDB running? See SETUP_GUIDE.md, "
            "'Troubleshooting'.\n", app.config["MONGO_URI"]
        )
    return app


# --- Templates --------------------------------------------------------------------------


def _register_template_helpers(app):
    try:
        local_tz = ZoneInfo(app.config["TIMEZONE"])
    except ZoneInfoNotFoundError:
        app.logger.warning("Unknown TIMEZONE %r, showing times in UTC.", app.config["TIMEZONE"])
        local_tz = timezone.utc

    @app.template_filter("localdt")
    def localdt(value):
        """Date and time in the college's timezone, e.g. 12 Oct 2026, 3:45 PM."""
        if not value:
            return "-"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(local_tz)
        return f"{value:%d %b %Y}, {value.hour % 12 or 12}:{value:%M %p}"

    @app.template_filter("datefmt")
    def datefmt(value):
        """A calendar date (the day an item was lost or found)."""
        return f"{value:%d %b %Y}" if value else "-"

    @app.template_filter("status_label")
    def status_label(value):
        return STATUS_LABELS.get(value, (value or "").title())

    app.jinja_env.filters["mask_email"] = mask_email
    app.jinja_env.globals["icon"] = icon

    @app.context_processor
    def inject_globals():
        unread = 0
        if has_request_context() and current_user and current_user.is_authenticated:
            unread = mongo.db.notifications.count_documents({"user_id": current_user.oid, "is_read": False})

        def url_with_page(page):
            args = request.args.to_dict()
            args["page"] = page
            return url_for(request.endpoint, **(request.view_args or {}), **args)

        cfg = app.config
        return {
            "app_name": cfg["APP_NAME"],
            "college_name": cfg["COLLEGE_NAME"],
            "security_desk": cfg["SECURITY_DESK_LOCATION"],
            "security_hours": cfg["SECURITY_DESK_HOURS"],
            "contact_email": cfg["CONTACT_EMAIL"],
            "contact_phone": cfg["CONTACT_PHONE"],
            "allowed_domains": cfg["ALLOWED_EMAIL_DOMAINS"],
            "max_rejected": cfg["MAX_REJECTED_CLAIMS"],
            "unread_count": unread,
            "current_year": datetime.now().year,
            "url_with_page": url_with_page,
        }


# --- Errors ------------------------------------------------------------------------------


def _register_error_handlers(app):
    def render_error(code, title, message):
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify(ok=False, message=message), code
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        return render_error(400, "This form expired",
                            "The page was open too long, or the form came from another site. "
                            "Go back, refresh the page and try again.")

    @app.errorhandler(403)
    def forbidden(_):
        return render_error(403, "Not allowed", "You don't have permission to see this page.")

    @app.errorhandler(404)
    def not_found(_):
        return render_error(404, "Page not found", "The page you're looking for doesn't exist or was removed.")

    @app.errorhandler(413)
    def too_large(_):
        return render_error(413, "File too large", "Each image must be 5 MB or smaller.")

    @app.errorhandler(429)
    def rate_limited(_):
        return render_error(429, "Slow down", "Too many attempts. Please wait a minute and try again.")

    @app.errorhandler(PyMongoError)
    def database_error(exc):
        app.logger.exception("Database error: %s", exc)
        return render_error(503, "Database unavailable",
                            "We couldn't reach the database. Make sure MongoDB is running and try again.")

    @app.errorhandler(500)
    def server_error(_):
        return render_error(500, "Something went wrong", "An unexpected error happened. Please try again.")


# --- Security headers -----------------------------------------------------------------


def _register_security_headers(app):
    @app.after_request
    def set_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        headers.setdefault("Content-Security-Policy", CSP)
        if app.config["SESSION_COOKIE_SECURE"]:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Private pages shouldn't be readable from the browser cache after logout.
        if current_user and current_user.is_authenticated and not request.path.startswith("/static/"):
            headers["Cache-Control"] = "no-store"
        return response


# --- Command-line helpers ------------------------------------------------------------------


def _register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create the MongoDB indexes."""
        ensure_indexes(mongo.db)
        click.echo("Indexes created.")

    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", prompt="Email")
    @click.password_option(prompt="Password (hidden while typing)")
    def create_admin(name, email, password):
        """Create a verified admin account."""
        from routes.auth import hash_password

        email = normalize_email(email)
        problems = password_problems(password)
        if problems:
            raise click.ClickException("Password must " + ", ".join(problems) + ".")
        if mongo.db.users.find_one({"email": email}):
            raise click.ClickException(f"{email} already exists. Use: flask --app app promote-admin {email}")
        if not is_college_email(email):
            click.secho("Note: this email isn't on an allowed college domain (allowed for admins).", fg="yellow")
        mongo.db.users.insert_one({
            "name": name.strip(), "email": email, "password_hash": hash_password(password), "role": "admin",
            "is_verified": True, "is_banned": False, "trust_score": 100, "rejected_claims": 0,
            "failed_login_attempts": 0, "lock_until": None, "session_token": secrets.token_urlsafe(24),
            "created_at": datetime.now(timezone.utc),
        })
        click.secho(f"Admin {email} created. Log in at http://127.0.0.1:5000/login", fg="green")

    @app.cli.command("promote-admin")
    @click.argument("email")
    def promote_admin(email):
        """Make an existing user an admin."""
        result = mongo.db.users.update_one({"email": normalize_email(email)},
                                           {"$set": {"role": "admin", "is_verified": True},
                                            "$unset": {"unverified_expires_at": ""}})
        if not result.matched_count:
            raise click.ClickException(f"No user with email {email}.")
        click.secho(f"{email} is now an admin.", fg="green")

    @app.cli.command("send-test-email")
    @click.argument("to")
    def send_test_email(to):
        """Send a test email to check the Gmail settings in .env."""
        from utils.mailer import send_test_email as send

        if not (app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]):
            raise click.ClickException("MAIL_USERNAME and MAIL_PASSWORD are empty in .env.")
        try:
            send(to)
        except Exception as exc:  # show the real SMTP error to the person setting it up
            raise click.ClickException(f"Sending failed: {exc}")
        click.secho(f"Sent! Check the inbox (and spam folder) of {to}.", fg="green")

    @app.cli.command("seed-demo")
    @click.option("--clear", is_flag=True, help="Remove the demo data instead of adding it.")
    def seed_demo(clear):
        """Add demo users and items for a presentation (password: Demo@1234)."""
        _seed_demo(app, clear)


def _seed_demo(app, clear):
    from routes.auth import hash_password

    db = mongo.db
    demo_users = list(db.users.find({"is_demo": True}, {"_id": 1}))
    if clear:
        ids = [u["_id"] for u in demo_users]
        item_ids = [i["_id"] for i in db.items.find({"is_demo": True}, {"_id": 1})]
        db.claims.delete_many({"$or": [{"item_id": {"$in": item_ids}}, {"claimant_id": {"$in": ids}}]})
        db.notifications.delete_many({"user_id": {"$in": ids}})
        db.items.delete_many({"is_demo": True})
        db.users.delete_many({"is_demo": True})
        click.secho("Demo data removed.", fg="green")
        return
    if demo_users:
        raise click.ClickException("Demo data already exists. Run with --clear first to reset it.")

    domain = app.config["ALLOWED_EMAIL_DOMAINS"][0]
    now = datetime.now(timezone.utc)
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    password_hash = hash_password("Demo@1234")
    people = {}
    for key, name in (("aarav", "Aarav Sharma"), ("diya", "Diya Patel"), ("kabir", "Kabir Singh")):
        people[key] = db.users.insert_one({
            "name": name, "email": f"demo.{key}@{domain}", "password_hash": password_hash, "role": "user",
            "is_verified": True, "is_banned": False, "trust_score": 100, "rejected_claims": 0,
            "failed_login_attempts": 0, "lock_until": None, "session_token": secrets.token_urlsafe(24),
            "created_at": now, "is_demo": True,
        }).inserted_id

    def item(kind, who, title, category, description, location, days_ago, **extra):
        return {"type": kind, "title": title, "category": category, "description": description,
                "location": location, "date": today - timedelta(days=days_ago), "image_id": None,
                "status": "open", "posted_by": people[who], "created_at": now - timedelta(days=days_ago),
                "updated_at": now, "is_demo": True, **extra}

    db.items.insert_many([
        item("found", "aarav", "Black leather wallet", "Wallets & Purses",
             "Black leather bi-fold wallet found under a table in the reading hall.", "Library", 1,
             hidden_details="Brown inner lining. Has a metro card, a Rs 500 note and a photo of a dog.",
             verification_questions=[
                 {"question": "What colour is the inside of the wallet?", "answer": "Brown"},
                 {"question": "Which card is inside apart from your ID?", "answer": "Metro card"}],
             held_at="security_desk"),
        item("found", "aarav", "Blue steel water bottle", "Water Bottles",
             "1 litre blue steel bottle with a few stickers, left on the bench near the football field.",
             "Sports Ground", 2,
             hidden_details="Sticker of a cartoon cat near the bottom and a dent on the lid.",
             verification_questions=[{"question": "Describe the stickers on the bottle.", "answer": "A cartoon cat"}],
             held_at="finder"),
        item("found", "kabir", "House keys with red keychain", "Keys",
             "Bunch of three keys on a red keychain found near the billing counter.", "Canteen", 3,
             hidden_details="Keychain says 'Goa 2024'. One key is small and gold coloured.",
             verification_questions=[{"question": "What is written on the keychain?", "answer": "Goa 2024"}],
             held_at="security_desk"),
        item("lost", "diya", "Lost my black wallet", "Wallets & Purses",
             "Black leather wallet with my college ID and metro card. Lost it while studying.",
             "Library 2nd floor", 1),
        item("lost", "kabir", "Casio scientific calculator", "Electronics",
             "Casio fx-991EX calculator in a grey cover, has my name scratched on the back.",
             "Classroom Block", 4),
    ])
    click.secho("Demo data added. Log in with any of these (password Demo@1234):", fg="green")
    for key in people:
        click.echo(f"  demo.{key}@{domain}")
    click.echo("Diya's lost wallet matches Aarav's found wallet: log in as Diya and open the dashboard.")


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=app.config["DEBUG"], use_reloader=False)
