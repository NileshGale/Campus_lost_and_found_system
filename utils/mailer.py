"""Email sending through Gmail SMTP (Flask-Mail).

Every email has an HTML version (templates/emails/) and a plain-text version.
Sending happens in a background thread so pages stay fast.

While MAIL_USERNAME / MAIL_PASSWORD are blank and FLASK_DEBUG=1, emails are
printed in the terminal instead, so the project can be tested before Gmail is set up.
"""
import logging
import threading

from flask import current_app, render_template
from flask_mail import Message

from extensions import mail

log = logging.getLogger(__name__)


def send_email(to, subject, template, text, **context):
    app = current_app._get_current_object()
    html = render_template(f"emails/{template}.html", subject=subject, **context)
    msg = Message(subject=subject, recipients=[to], body=text, html=html)
    if app.config.get("MAIL_ASYNC") and not app.testing:
        threading.Thread(target=_deliver_in_context, args=(app, msg), daemon=True).start()
    else:
        _deliver(app, msg)


def _deliver_in_context(app, msg):
    with app.app_context():
        _deliver(app, msg)


def _deliver(app, msg, raise_errors=False):
    if app.testing:
        mail.send(msg)  # suppressed in tests; captured by mail.record_messages()
        return
    if not (app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]):
        if app.debug:
            print(
                "\n" + "=" * 70
                + "\n  EMAIL (not sent - MAIL_USERNAME/MAIL_PASSWORD are empty in .env)"
                + f"\n  To: {', '.join(msg.recipients)}\n  Subject: {msg.subject}\n"
                + "-" * 70 + f"\n{msg.body}\n" + "=" * 70 + "\n",
                flush=True,
            )
        else:
            log.error("Email to %s not sent: MAIL_USERNAME / MAIL_PASSWORD are not set.", msg.recipients)
        return
    try:
        mail.send(msg)
    except Exception:
        log.exception("Failed to send email to %s", msg.recipients)
        if raise_errors:
            raise


def send_test_email(to):
    """Used by `flask send-test-email`. Sends synchronously and raises on failure."""
    app = current_app._get_current_object()
    subject = f"Test email from {app.config['APP_NAME']}"
    text = "If you can read this, Gmail SMTP is set up correctly."
    html = render_template(
        "emails/claim_status.html",
        subject=subject,
        heading="SMTP is working",
        message=text,
        status=None,
        note=None,
        cta_url=None,
        cta_label=None,
    )
    _deliver(app, Message(subject=subject, recipients=[to], body=text, html=html), raise_errors=True)


# --- One helper per email type ----------------------------------------------------


def _minutes():
    return current_app.config["OTP_EXPIRY_MINUTES"]


def send_register_otp(email, name, code):
    send_email(
        email,
        "Your verification code",
        "register_otp",
        f"Hi {name},\n\nYour verification code is {code}.\nIt expires in {_minutes()} minutes.\n\n"
        "If you didn't create an account, you can ignore this email.",
        name=name,
        code=code,
        minutes=_minutes(),
    )


def send_reset_otp(email, name, code):
    send_email(
        email,
        "Your password reset code",
        "reset_otp",
        f"Hi {name},\n\nYour password reset code is {code}.\nIt expires in {_minutes()} minutes.\n\n"
        "If you didn't ask to reset your password, ignore this email. Your password stays the same.",
        name=name,
        code=code,
        minutes=_minutes(),
    )


def send_account_exists(email, name, login_url, reset_url):
    send_email(
        email,
        "You already have an account",
        "account_exists",
        f"Hi {name},\n\nSomeone (hopefully you) tried to register with this email, "
        f"but you already have an account.\n\nLog in: {login_url}\nForgot your password? {reset_url}\n\n"
        "If this wasn't you, you can ignore this email.",
        name=name,
        login_url=login_url,
        reset_url=reset_url,
    )


def send_match_alert(email, name, my_item, other_item, score, url):
    send_email(
        email,
        f"Possible match for “{my_item['title']}”",
        "match_found",
        f"Hi {name},\n\nA {other_item['type']} item looks like your {my_item['type']} item "
        f"“{my_item['title']}” ({score}% match).\n\n"
        f"{other_item['title']} - {other_item['category']}, {other_item['location']}\n\nView it: {url}",
        name=name,
        my_item=my_item,
        other_item=other_item,
        score=score,
        url=url,
    )


def send_claim_status(email, name, heading, message, status=None, note=None, cta_url=None, cta_label=None):
    text = f"Hi {name},\n\n{message}"
    if note:
        text += f"\n\nNote from the reviewer: {note}"
    if cta_url:
        text += f"\n\n{cta_label or 'Open'}: {cta_url}"
    send_email(
        email,
        heading,
        "claim_status",
        text,
        name=name,
        heading=heading,
        message=message,
        status=status,
        note=note,
        cta_url=cta_url,
        cta_label=cta_label,
    )


def send_handover_otp(email, name, item, code, expires_at, url):
    cfg = current_app.config
    send_email(
        email,
        "Your claim was approved: handover code inside",
        "handover_otp",
        f"Hi {name},\n\nYour claim for “{item['title']}” was approved.\n\n"
        f"Handover code: {code}\n\nCollect the item at {cfg['SECURITY_DESK_LOCATION']} "
        f"({cfg['SECURITY_DESK_HOURS']}). Bring your college ID card and tell this code only "
        "to the security desk staff.\n\nDetails: " + url,
        name=name,
        item=item,
        code=code,
        expires_at=expires_at,
        url=url,
    )
