"""
INTEGRATION TESTS: End-to-end flows that exercise routes + database + email together.
Tests full user journeys across multiple components.
"""
import re
from datetime import date, timedelta
from io import BytesIO

import pytest
from bson import ObjectId
from PIL import Image

from conftest import (
    DOMAIN, PASSWORD, jpeg, last_code, logged_in, login, new_admin, new_user,
    post_found, post_lost, register,
)
from extensions import mongo
from utils.helpers import utcnow


# ============================================================================
# 1. Full Registration → OTP → Login flow
# ============================================================================


class TestRegistrationFlow:
    def test_full_register_verify_login(self, app, outbox):
        """TDD: user registers, receives OTP email, verifies, then logs in."""
        client = app.test_client()
        email = f"integration@{DOMAIN}"
        response = register(client, email, name="Integration User")
        assert b"emailed a 6-digit code" in response.data
        assert len(outbox) == 1
        assert mongo.db.users.find_one({"email": email})["is_verified"] is False

        code = last_code(outbox)
        response = client.post("/verify-otp", data={"code": code}, follow_redirects=True)
        assert b"Email verified" in response.data
        assert mongo.db.users.find_one({"email": email})["is_verified"] is True

        response = login(client, email)
        assert logged_in(response)

    def test_register_with_existing_verified_email_sends_warning(self, app, outbox):
        """Integration: re-registering a verified email sends 'account exists' email."""
        _, email = new_user(app, outbox, "Alice")
        other = app.test_client()
        response = register(other, email, password="Diff3rent!Pass")
        assert b"emailed a 6-digit code" in response.data
        assert outbox[-1].subject == "You already have an account"

    def test_unverified_user_gets_ttl_field(self, app, outbox):
        client = app.test_client()
        email = f"ttl@{DOMAIN}"
        register(client, email)
        user = mongo.db.users.find_one({"email": email})
        assert "unverified_expires_at" in user
        assert user["unverified_expires_at"] > utcnow()

    def test_verification_removes_ttl_field(self, app, outbox):
        _, email = new_user(app, outbox, "Verified")
        user = mongo.db.users.find_one({"email": email})
        assert "unverified_expires_at" not in user


# ============================================================================
# 2. Full Password Reset flow
# ============================================================================


class TestPasswordResetFlow:
    def test_forgot_verify_reset_login(self, app, outbox):
        """TDD: full password reset cycle."""
        _, email = new_user(app, outbox, "Forgetter")

        other = app.test_client()
        other.post("/forgot-password", data={"email": email})
        code = last_code(outbox)

        other.post("/reset-password/verify", data={"code": code})
        response = other.post(
            "/reset-password",
            data={"password": "Brand!N3w99", "confirm": "Brand!N3w99"},
            follow_redirects=True,
        )
        assert b"Password updated" in response.data

        assert logged_in(login(app.test_client(), email, "Brand!N3w99"))
        assert not logged_in(login(app.test_client(), email, PASSWORD))

    def test_reset_creates_security_notification(self, app, outbox):
        _, email = new_user(app, outbox, "Notified")
        other = app.test_client()
        other.post("/forgot-password", data={"email": email})
        code = last_code(outbox)
        other.post("/reset-password/verify", data={"code": code})
        other.post("/reset-password", data={"password": "Brand!N3w99", "confirm": "Brand!N3w99"})
        uid = mongo.db.users.find_one({"email": email})["_id"]
        note = mongo.db.notifications.find_one({"user_id": uid, "type": "security"})
        assert note is not None
        assert "password was changed" in note["message"]


# ============================================================================
# 3. Full Item Reporting → Matching flow
# ============================================================================


class TestItemMatchingFlow:
    def test_found_then_lost_triggers_match(self, app, outbox):
        """TDD: posting a lost item after a found item triggers match alerts."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        owner, _ = new_user(app, outbox, "Owner")
        response = post_lost(owner)
        assert b"possible match" in response.data

        match_emails = [m for m in outbox if m.subject.startswith("Possible match")]
        assert len(match_emails) == 2
        assert mongo.db.notifications.count_documents({"type": "match"}) == 2

    def test_lost_then_found_also_matches(self, app, outbox):
        """TDD: posting a found item after a lost item also triggers matches."""
        owner, _ = new_user(app, outbox, "Owner")
        post_lost(owner)
        finder, _ = new_user(app, outbox, "Finder")
        response = post_found(finder)
        assert b"possible match" in response.data

    def test_same_category_boosts_score(self, app, outbox):
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder, category="Wallets & Purses")
        owner, _ = new_user(app, outbox, "Owner")
        # Same category should produce a match
        post_lost(owner, category="Wallets & Purses")
        assert mongo.db.notifications.count_documents({"type": "match"}) > 0

    def test_unrelated_items_dont_match(self, app, outbox):
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        owner, _ = new_user(app, outbox, "Owner")
        post_lost(owner, title="Casio calculator", category="Electronics",
                  description="Scientific calculator with my name on back.", location="Canteen")
        assert mongo.db.notifications.count_documents({"type": "match"}) == 0


# ============================================================================
# 4. Full Claim → Review → Handover flow
# ============================================================================


def _claim(client, item_id, answer="Brown", proof=True):
    data = {"answer_0": answer, "details": "My black wallet with brown lining.", "confirm": "y"}
    if proof:
        data["proofs"] = [(jpeg(), "bill.jpg")]
    return client.post(f"/claims/new/{item_id}", data=data,
                       content_type="multipart/form-data", follow_redirects=True)


class TestClaimReviewHandoverFlow:
    def test_claim_approve_handover_complete(self, app, outbox):
        """TDD: full happy path from claim to security desk handover."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()
        owner, _ = new_user(app, outbox, "Owner")

        # Step 1: Submit claim
        response = _claim(owner, item["_id"])
        assert b"Claim submitted" in response.data
        claim = mongo.db.claims.find_one()
        assert claim["status"] == "pending"

        # Step 2: Finder approves
        finder.post(f"/claims/{claim['_id']}/review", data={"decision": "approve", "note": "Matches"})
        claim = mongo.db.claims.find_one()
        assert claim["status"] == "approved"
        assert item_status(item["_id"]) == "claimed"

        # Step 3: Extract handover code from email
        handover_mail = next(m for m in outbox if "handover code" in m.subject.lower())
        code = re.search(r"Handover code: (\d{6})", handover_mail.body).group(1)

        # Step 4: Security desk completes handover
        admin = new_admin(app)
        response = admin.post(
            f"/admin/claims/{claim['_id']}/handover",
            data={"code": code, "id_checked": "y"},
            follow_redirects=True,
        )
        assert b"Handover complete" in response.data
        assert item_status(item["_id"]) == "returned"
        claim = mongo.db.claims.find_one()
        assert claim["status"] == "completed"

    def test_rejected_claim_penalties(self, app, outbox):
        """TDD: rejecting a claim deducts trust score and increments rejection count."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()
        faker, email = new_user(app, outbox, "Faker")

        _claim(faker, item["_id"], answer="Red")  # Wrong answer
        claim = mongo.db.claims.find_one()
        finder.post(f"/claims/{claim['_id']}/review", data={"decision": "reject"})

        user = mongo.db.users.find_one({"email": email})
        assert user["rejected_claims"] == 1
        assert user["trust_score"] == 80  # 100 - 20 penalty

    def test_disputed_claims_require_admin(self, app, outbox):
        """TDD: two claims on same item = disputed, finder cannot approve."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        first, _ = new_user(app, outbox, "First")
        second, _ = new_user(app, outbox, "Second")
        _claim(first, item["_id"])
        _claim(second, item["_id"], answer="Black")

        claims = list(mongo.db.claims.find().sort("created_at", 1))
        response = finder.post(
            f"/claims/{claims[0]['_id']}/review",
            data={"decision": "approve"},
            follow_redirects=True,
        )
        assert b"admin decides" in response.data
        assert mongo.db.claims.find_one({"_id": claims[0]["_id"]})["status"] == "pending"

    def test_approved_claim_closes_others(self, app, outbox):
        """TDD: approving one claim closes other pending claims without penalty."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        first, _ = new_user(app, outbox, "First")
        second, second_email = new_user(app, outbox, "Second")
        _claim(first, item["_id"])
        _claim(second, item["_id"], answer="Black")

        claims = list(mongo.db.claims.find().sort("created_at", 1))
        admin = new_admin(app)
        admin.post(f"/claims/{claims[0]['_id']}/review", data={"decision": "approve"})

        assert mongo.db.claims.find_one({"_id": claims[1]["_id"]})["status"] == "closed"
        second_user = mongo.db.users.find_one({"email": second_email})
        assert second_user["trust_score"] == 100  # No penalty for closed claims


# ============================================================================
# 5. Admin Panel Integration
# ============================================================================


class TestAdminIntegration:
    def test_admin_can_remove_and_restore_item(self, app, outbox):
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()
        admin = new_admin(app)

        # Remove
        admin.post(f"/admin/items/{item['_id']}/remove", data={"reason": "Duplicate post"})
        assert item_status(item["_id"]) == "removed"

        # Restore
        admin.post(f"/admin/items/{item['_id']}/restore")
        assert item_status(item["_id"]) == "open"

    def test_admin_ban_logs_out_user(self, app, outbox):
        user_client, email = new_user(app, outbox, "Bannable")
        admin = new_admin(app)
        uid = mongo.db.users.find_one({"email": email})["_id"]

        admin.post(f"/admin/users/{uid}/ban")
        assert user_client.get("/dashboard").status_code == 302  # logged out

        assert b"suspended" in login(app.test_client(), email).data

    def test_admin_unban_restores_access(self, app, outbox):
        _, email = new_user(app, outbox, "Unbanned")
        admin = new_admin(app)
        uid = mongo.db.users.find_one({"email": email})["_id"]

        admin.post(f"/admin/users/{uid}/ban")
        admin.post(f"/admin/users/{uid}/unban")
        assert logged_in(login(app.test_client(), email))

    def test_admin_cannot_ban_admin(self, app):
        admin = new_admin(app, "AdminOne")
        admin_id = mongo.db.users.find_one({"email": f"adminone@{DOMAIN}"})["_id"]
        response = admin.post(f"/admin/users/{admin_id}/ban", follow_redirects=True)
        assert b"can\\'t be banned" in response.data or b"can&#39;t be banned" in response.data or b"Admins" in response.data

    def test_admin_resend_handover_code(self, app, outbox):
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()
        owner, _ = new_user(app, outbox, "Owner")
        _claim(owner, item["_id"])
        claim = mongo.db.claims.find_one()
        finder.post(f"/claims/{claim['_id']}/review", data={"decision": "approve"})

        admin = new_admin(app)
        old_hash = mongo.db.claims.find_one()["handover_otp_hash"]
        admin.post(f"/admin/claims/{claim['_id']}/resend-code")
        new_hash = mongo.db.claims.find_one()["handover_otp_hash"]
        assert old_hash != new_hash


# ============================================================================
# 6. Notification Integration
# ============================================================================


class TestNotificationIntegration:
    def test_mark_single_read(self, app, outbox):
        user, _ = new_user(app, outbox, "Notif")
        uid = mongo.db.users.find_one({"email": f"notif@{DOMAIN}"})["_id"]
        from utils.notifications import notify
        with app.app_context():
            notify(uid, "Test 1", "system")
            notify(uid, "Test 2", "system")
        nid = mongo.db.notifications.find_one({"user_id": uid})["_id"]
        user.post(f"/notifications/{nid}/read", headers={"Accept": "application/json"})
        assert mongo.db.notifications.find_one({"_id": nid})["is_read"] is True

    def test_mark_all_read(self, app, outbox):
        user, _ = new_user(app, outbox, "NotifTwo")
        uid = mongo.db.users.find_one({"email": f"notiftwo@{DOMAIN}"})["_id"]
        from utils.notifications import notify
        with app.app_context():
            for i in range(5):
                notify(uid, f"Message {i}", "system")
        user.post("/notifications/read-all")
        unread = mongo.db.notifications.count_documents({"user_id": uid, "is_read": False})
        assert unread == 0


# ============================================================================
# 7. Profile Integration
# ============================================================================


class TestProfileIntegration:
    def test_change_name(self, app, outbox):
        user, email = new_user(app, outbox, "OldName")
        user.post("/profile", data={"action": "profile", "profile-name": "New Name"})
        assert mongo.db.users.find_one({"email": email})["name"] == "New Name"

    def test_change_password(self, app, outbox):
        user, email = new_user(app, outbox, "Changer")
        user.post("/profile", data={
            "action": "password",
            "pw-current_password": PASSWORD,
            "pw-password": "Ch4nged!Pwd",
            "pw-confirm": "Ch4nged!Pwd",
        })
        assert logged_in(login(app.test_client(), email, "Ch4nged!Pwd"))
        assert not logged_in(login(app.test_client(), email, PASSWORD))

    def test_wrong_current_password_rejected(self, app, outbox):
        user, _ = new_user(app, outbox, "WrongPw")
        response = user.post("/profile", data={
            "action": "password",
            "pw-current_password": "WrongOld!1",
            "pw-password": "N3w!Password",
            "pw-confirm": "N3w!Password",
        }, follow_redirects=True)
        assert b"current password is incorrect" in response.data


# ============================================================================
# 8. Item delete / resolve
# ============================================================================


class TestItemDeleteResolve:
    def test_owner_can_delete_open_item(self, app, outbox):
        user, _ = new_user(app, outbox, "Poster")
        post_lost(user)
        item = mongo.db.items.find_one()
        user.post(f"/items/{item['_id']}/delete")
        assert item_status(item["_id"]) == "removed"

    def test_owner_can_resolve_lost_item(self, app, outbox):
        user, _ = new_user(app, outbox, "Resolver")
        post_lost(user)
        item = mongo.db.items.find_one()
        user.post(f"/items/{item['_id']}/resolve")
        assert item_status(item["_id"]) == "returned"

    def test_finder_can_resolve_item_they_still_have(self, app, outbox):
        finder, _ = new_user(app, outbox, "Keeper")
        post_found(finder, held_at="finder")
        item = mongo.db.items.find_one()
        claimer, _ = new_user(app, outbox, "Hopeful")
        _claim(claimer, item["_id"])
        finder.post(f"/items/{item['_id']}/resolve")
        assert item_status(item["_id"]) == "returned"
        assert mongo.db.claims.find_one({"item_id": item["_id"]})["status"] == "closed"

    def test_cannot_resolve_found_item_already_at_desk(self, app, outbox):
        finder, _ = new_user(app, outbox, "Dropper")
        post_found(finder, held_at="security_desk")
        item = mongo.db.items.find_one()
        response = finder.post(f"/items/{item['_id']}/resolve")
        assert response.status_code == 403
        assert item_status(item["_id"]) == "open"

    def test_cannot_delete_item_with_pending_claims(self, app, outbox):
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()
        claimer, _ = new_user(app, outbox, "Claimer")
        _claim(claimer, item["_id"])
        response = finder.post(f"/items/{item['_id']}/delete", follow_redirects=True)
        assert b"pending claims" in response.data
        assert item_status(item["_id"]) == "open"


# ============================================================================
# Helper
# ============================================================================


def item_status(item_id):
    return mongo.db.items.find_one({"_id": item_id})["status"]

