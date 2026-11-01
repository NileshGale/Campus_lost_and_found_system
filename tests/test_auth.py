"""Authentication and OTP security rules."""
import re
from datetime import timedelta

from conftest import DOMAIN, PASSWORD, last_code, logged_in, login, new_admin, new_user, register
from extensions import mongo
from utils.helpers import utcnow


def test_register_rejects_non_college_email(client, outbox):
    response = register(client, "someone@gmail.com")
    assert b"Use your college email address" in response.data
    assert mongo.db.users.count_documents({}) == 0
    assert outbox == []


def test_register_rejects_weak_password(client):
    response = register(client, f"asha@{DOMAIN}", password="weakpassword")
    assert b"Password must" in response.data
    assert mongo.db.users.count_documents({}) == 0


def test_register_stores_hashes_not_secrets(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    user = mongo.db.users.find_one({"email": email})
    assert user["is_verified"] is False
    assert user["password_hash"].startswith("$2b$")
    assert PASSWORD not in str(user)

    code = last_code(outbox)
    otp = mongo.db.otps.find_one({"email": email, "purpose": "register"})
    assert code not in str(otp)
    assert otp["attempts"] == 0
    assert utcnow() + timedelta(minutes=9) < otp["expires_at"] <= utcnow() + timedelta(minutes=10)


def test_cannot_log_in_before_verifying(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    response = login(client, email)
    assert b"Verify your email" in response.data
    assert client.get("/dashboard").status_code == 302


def test_verify_then_log_in_sets_httponly_cookie(app, outbox):
    client, _ = new_user(app, outbox, "Asha")
    assert client.get("/dashboard").status_code == 200
    cookie = client.get_cookie("lf_session")
    assert cookie is not None and cookie.http_only


def test_otp_locks_after_five_wrong_attempts(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    code = last_code(outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/verify-otp", data={"code": wrong})
    response = client.post("/verify-otp", data={"code": code}, follow_redirects=True)
    assert b"Too many wrong attempts" in response.data
    assert mongo.db.users.find_one({"email": email})["is_verified"] is False


def test_expired_otp_is_rejected(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    code = last_code(outbox)
    mongo.db.otps.update_one({"email": email}, {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}})
    response = client.post("/verify-otp", data={"code": code}, follow_redirects=True)
    assert b"expired" in response.data
    assert mongo.db.users.find_one({"email": email})["is_verified"] is False


def test_registration_code_cannot_reset_password(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    register_code = last_code(outbox)
    client.post("/forgot-password", data={"email": email})
    reset_code = last_code(outbox)
    if reset_code == register_code:  # 1 in a million
        return
    response = client.post("/reset-password/verify", data={"code": register_code}, follow_redirects=True)
    assert b"incorrect or has expired" in response.data


def test_resend_has_60_second_cooldown(client, outbox):
    email = f"asha@{DOMAIN}"
    register(client, email)
    data = client.post("/resend-otp", json={"purpose": "register"}).get_json()
    assert data["ok"] is False and 0 < data["cooldown"] <= 60
    assert len(outbox) == 1

    mongo.db.otps.update_one({"email": email}, {"$set": {"last_sent_at": utcnow() - timedelta(seconds=61)}})
    data = client.post("/resend-otp", json={"purpose": "register"}).get_json()
    assert data["ok"] is True
    assert len(outbox) == 2


def test_registering_existing_email_reveals_nothing(app, outbox):
    _, email = new_user(app, outbox, "Asha")
    other = app.test_client()
    response = register(other, email, password="Diff3rent!Pass")
    assert b"emailed a 6-digit code" in response.data
    assert outbox[-1].subject == "You already have an account"
    # The original password still works; the attacker's doesn't.
    assert logged_in(login(app.test_client(), email))
    assert not logged_in(login(app.test_client(), email, "Diff3rent!Pass"))


def test_forgot_password_same_response_for_unknown_email(app, outbox):
    _, email = new_user(app, outbox, "Asha")

    def page(target):
        body = app.test_client().post("/forgot-password", data={"email": target}, follow_redirects=True).data.decode()
        body = re.sub(r'"[\w-]+\.[\w-]+\.[\w-]+"', '"CSRF"', body)  # per-session CSRF tokens differ
        return re.sub(r"<strong>[^<]*@[^<]*</strong>", "<strong>EMAIL</strong>", body)

    known = page(email)
    unknown = page(f"nobody@{DOMAIN}")
    assert "If an account exists" in known
    assert known == unknown


def test_reset_password_logs_out_old_sessions(app, outbox):
    old_session, email = new_user(app, outbox, "Asha")
    assert old_session.get("/dashboard").status_code == 200

    other = app.test_client()
    other.post("/forgot-password", data={"email": email})
    other.post("/reset-password/verify", data={"code": last_code(outbox)})
    redirected = other.post("/reset-password", data={"password": "N3w!Password", "confirm": "N3w!Password"})
    assert redirected.status_code == 302
    assert redirected.headers["Location"].endswith("/login")
    response = other.get("/login")
    assert b"Password updated" in response.data

    assert old_session.get("/dashboard").status_code == 302
    assert logged_in(login(app.test_client(), email, "N3w!Password"))
    assert not logged_in(login(app.test_client(), email))


def test_login_locks_for_15_minutes_after_5_failures(app, outbox):
    _, email = new_user(app, outbox, "Asha")
    client = app.test_client()
    for _ in range(5):
        login(client, email, "Wrong!Pass1")
    response = login(client, email)  # correct password, but locked
    assert b"Too many failed attempts" in response.data
    assert client.get("/dashboard").status_code == 302
    lock_until = mongo.db.users.find_one({"email": email})["lock_until"]
    assert utcnow() + timedelta(minutes=14) < lock_until <= utcnow() + timedelta(minutes=15)


def test_csrf_token_required(make_app):
    app = make_app(WTF_CSRF_ENABLED=True)
    response = app.test_client().post("/login", data={"email": f"a@{DOMAIN}", "password": PASSWORD})
    assert response.status_code == 400


def test_login_is_rate_limited(make_app):
    app = make_app(RATELIMIT_ENABLED=True)
    client = app.test_client()
    codes = [client.post("/login", data={"email": f"a@{DOMAIN}", "password": "x"}).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_admin_routes_need_admin_role(app, outbox):
    assert app.test_client().get("/admin/").status_code == 302
    user, _ = new_user(app, outbox, "Asha")
    assert user.get("/admin/").status_code == 403
    assert user.post("/admin/users/000000000000000000000000/ban").status_code == 403
    admin = new_admin(app)
    assert admin.get("/admin/").status_code == 200


def test_banned_user_is_logged_out(app, outbox):
    user, email = new_user(app, outbox, "Asha")
    admin = new_admin(app)
    user_id = mongo.db.users.find_one({"email": email})["_id"]
    admin.post(f"/admin/users/{user_id}/ban")
    assert user.get("/dashboard").status_code == 302
    assert b"suspended" in login(app.test_client(), email).data
