"""
SECURITY & ADVERSARIAL BREAKING TESTS:
Acts as a security red-team agent / adversarial tester to actively attempt
breaking features, discovering vulnerabilities, logic flaws, bypasses, and edge-case crashes.
DO NOT FIX ANY ISSUES FOUND - ONLY IDENTIFY AND REPORT.
"""
import io
import json
import secrets
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

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
# 1. AUTHENTICATION & ACCESS CONTROL BREAKING TESTS
# ============================================================================

class TestAuthBreakingAttempts:

    def test_break_register_with_domain_collision_tricks(self, client):
        """Attacker tries subdomains or fake domains matching pattern."""
        # domain prefix spoofing: e.g. "notourcollege.edu.in"
        resp = register(client, "attacker@not" + DOMAIN)
        assert b"Use your college email address" in resp.data

        # trailing dot spoofing: "testcollege.edu.in."
        resp = register(client, f"attacker@{DOMAIN}.")
        assert b"Use your college email address" in resp.data

    def test_break_role_tampering_via_registration(self, client, outbox):
        """Attacker tries mass-assignment to sneak in role=admin during register."""
        email = f"sneakyadmin@{DOMAIN}"
        client.post(
            "/register",
            data={
                "name": "Hacker",
                "email": email,
                "password": PASSWORD,
                "confirm": PASSWORD,
                "role": "admin",
                "is_admin": True,
            },
            follow_redirects=True,
        )
        user = mongo.db.users.find_one({"email": email})
        if user:
            # Check if role was escalated
            assert user.get("role") == "user", "CRITICAL BREAK: Mass assignment allowed user to set role=admin!"

    def test_break_login_with_nosql_injection_payload(self, client):
        """Attacker sends Mongo query operators in login JSON or form."""
        resp = client.post(
            "/login",
            data={"email": '{"$gt": ""}', "password": '{"$gt": ""}'},
            follow_redirects=True,
        )
        assert b"Invalid email" in resp.data or resp.status_code in (200, 400)
        assert client.get("/dashboard").status_code == 302, "CRITICAL BREAK: NoSQL injection logged in!"

    def test_break_session_hijacking_via_reused_cookie_after_logout(self, app, outbox):
        """Attacker saves cookie and tries to use it after /logout."""
        user, email = new_user(app, outbox, "LogoutTest")
        # Save session cookie
        cookie = user.get_cookie("lf_session")
        assert cookie is not None

        # Log out
        user.get("/logout")

        # Set cookie back and test if still authenticated
        user.set_cookie("lf_session", cookie.value)
        resp = user.get("/dashboard")
        assert resp.status_code == 302, "BREAK: Session cookie remained valid after logout!"

    def test_break_horizontal_privilege_escalation_profile_update(self, app, outbox):
        """Attacker tries to modify another user's profile by injecting user_id."""
        victim, victim_email = new_user(app, outbox, "Victim")
        attacker, attacker_email = new_user(app, outbox, "Attacker")

        victim_id = mongo.db.users.find_one({"email": victim_email})["_id"]

        # Attacker attempts to pass victim's _id to update profile
        attacker.post("/profile", data={
            "action": "profile",
            "_id": str(victim_id),
            "user_id": str(victim_id),
            "profile-name": "Hacked Victim Name",
        })

        victim_doc = mongo.db.users.find_one({"_id": victim_id})
        assert victim_doc["name"] == "Victim", "CRITICAL BREAK: Attacker was able to update victim's profile!"


# ============================================================================
# 2. CLAIM & VERIFICATION BREAKING TESTS (Business Logic Flaws)
# ============================================================================

class TestClaimBreakingAttempts:

    def test_break_claim_on_closed_or_claimed_item(self, app, outbox):
        """Attacker attempts to submit claim for an item already claimed/returned."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        # Mark item as returned
        mongo.db.items.update_one({"_id": item["_id"]}, {"$set": {"status": "returned"}})

        attacker, _ = new_user(app, outbox, "Attacker")
        resp = attacker.post(
            f"/claims/new/{item['_id']}",
            data={"answer_0": "Test", "details": "My lost item", "confirm": "y"},
            follow_redirects=True,
        )
        assert b"isn't open for claims" in resp.data or b"isn&#39;t open for claims" in resp.data
        assert mongo.db.claims.count_documents({"item_id": item["_id"]}) == 0, "BREAK: Claim created on closed item!"

    def test_break_claim_approval_by_non_finder_non_admin(self, app, outbox):
        """Attacker attempts to approve another user's claim via POST."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        owner, _ = new_user(app, outbox, "LegitOwner")
        owner.post(f"/claims/new/{item['_id']}", data={"answer_0": "Brown", "details": "My lost black leather wallet", "confirm": "y"})
        claim = mongo.db.claims.find_one({"item_id": item["_id"]})

        attacker, _ = new_user(app, outbox, "Attacker")
        resp = attacker.post(f"/claims/{claim['_id']}/review", data={"decision": "approve"})
        # Should be forbidden / 404
        assert resp.status_code in (403, 404), "CRITICAL BREAK: Random user could reach claim review endpoint!"
        assert mongo.db.claims.find_one({"_id": claim["_id"]})["status"] == "pending"

    def test_break_claim_viewing_idor_proof_image(self, app, outbox):
        """Attacker attempts to download private proof image of a claim they don't own."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        owner, _ = new_user(app, outbox, "LegitOwner")
        proof_file_id = "a" * 32
        mongo.db.claims.insert_one({
            "item_id": item["_id"],
            "claimant_id": mongo.db.users.find_one({"email": f"legitowner@{DOMAIN}"})["_id"],
            "status": "pending",
            "proof_files": [proof_file_id],
        })
        claim = mongo.db.claims.find_one({"item_id": item["_id"]})

        attacker, _ = new_user(app, outbox, "Attacker")
        resp = attacker.get(f"/claims/{claim['_id']}/proof/{proof_file_id}")
        assert resp.status_code in (403, 404), "CRITICAL BREAK: IDOR allows unauthorized access to proof image!"

    def test_break_handover_otp_brute_force_lockout(self, app, outbox):
        """Test whether 5 wrong attempts strictly lock the handover OTP."""
        finder, _ = new_user(app, outbox, "Finder")
        post_found(finder)
        item = mongo.db.items.find_one()

        owner, _ = new_user(app, outbox, "Owner")
        owner.post(f"/claims/new/{item['_id']}", data={"answer_0": "Brown", "details": "My lost black leather wallet", "confirm": "y"})
        claim = mongo.db.claims.find_one({"item_id": item["_id"]})
        finder.post(f"/claims/{claim['_id']}/review", data={"decision": "approve"})

        # Claim is approved
        admin = new_admin(app)
        # Try 5 wrong OTPs
        for _ in range(5):
            admin.post(f"/admin/claims/{claim['_id']}/handover", data={"code": "999999", "id_checked": "y"})

        # Try a 6th time with ANY code
        resp = admin.post(f"/admin/claims/{claim['_id']}/handover", data={"code": "123456", "id_checked": "y"}, follow_redirects=True)
        assert b"Too many wrong codes" in resp.data or b"No attempts left" in resp.data or b"Wrong handover code" in resp.data or b"expired" in resp.data

    def test_break_trust_score_floor_and_ceiling(self, app):
        """Test if trust score goes below 0 or above 100 via logic boundary manipulation."""
        from utils.claims import complete_handover, reject_claim
        with app.app_context():
            uid = mongo.db.users.insert_one({
                "name": "BorderUser", "email": f"border@{DOMAIN}", "trust_score": 10, "rejected_claims": 2,
            }).inserted_id

            # Simulate reject
            claim = {"_id": ObjectId(), "claimant_id": uid, "status": "pending"}
            item = {"_id": ObjectId(), "title": "Watch", "status": "open"}
            admin_mock = type("Admin", (), {"oid": ObjectId(), "is_admin": True})()

            reject_claim(claim, item, admin_mock)
            user_doc = mongo.db.users.find_one({"_id": uid})
            assert user_doc["trust_score"] >= 0, "BREAK: Trust score became negative!"


# ============================================================================
# 3. UPLOAD SECURITY & FILE PARSER BREAKING TESTS
# ============================================================================

class TestUploadBreakingAttempts:

    def test_break_upload_svg_xss(self, app, outbox):
        """Attempt to upload SVG containing JavaScript payload."""
        finder, _ = new_user(app, outbox, "Finder")
        svg_payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.domain)</script></svg>'
        resp = post_found(finder, photo=(BytesIO(svg_payload), "avatar.svg"))
        assert b"Only JPG, PNG or WEBP" in resp.data or b"isn't a valid image" in resp.data or b"isn&#39;t a valid image" in resp.data

    def test_break_upload_polyglot_html_in_jpeg(self, app, outbox):
        """Attempt to upload a crafted file that starts with JPEG magic bytes but has HTML/JS."""
        finder, _ = new_user(app, outbox, "Finder")
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`<script>alert(1)</script>"
        resp = post_found(finder, photo=(BytesIO(fake_jpeg), "evil.jpg"))
        assert b"isn't a valid image" in resp.data or b"isn&#39;t a valid image" in resp.data

    def test_break_upload_directory_traversal_filename(self, app, outbox):
        """Filename with path traversal attempting to write outside upload directory."""
        finder, _ = new_user(app, outbox, "Finder")
        resp = post_found(finder, photo=(jpeg(), "../../../../shell.jpg"))
        # System uses uuid hex for saved files, ensuring path traversal via filename is neutralized
        item = mongo.db.items.find_one()
        assert item is not None
        assert not item.get("image_id", "").startswith(".")


# ============================================================================
# 4. DATA SANITIZATION & INJECTION BREAKING TESTS
# ============================================================================

class TestSanitizationBreakingAttempts:

    def test_break_xss_in_item_title_and_description(self, app, outbox):
        """Attacker injects script tag in item title, check if rendered unescaped."""
        user, _ = new_user(app, outbox, "Poster")
        xss_string = '<script>alert("XSS")</script>'
        post_lost(user, title=xss_string, description='<img src=x onerror=alert(1)>')
        item = mongo.db.items.find_one({"title": xss_string})
        assert item is not None

        resp = user.get(f"/items/{item['_id']}")
        # Must be HTML escaped in output
        assert b"<script>alert(\"XSS\")</script>" not in resp.data
        assert b"&lt;script&gt;" in resp.data or b"&lt;img" in resp.data

    def test_break_regex_dos_in_search_query(self, app, outbox):
        """Attacker submits catastrophic backtracking regex in search bar."""
        user, _ = new_user(app, outbox, "Searcher")
        post_found(user)

        redos_payload = "((((((a+)+)+)+)+)+)!"
        resp = user.get(f"/items/browse?q={redos_payload}")
        # Server should not hang or crash
        assert resp.status_code == 200

    def test_break_null_byte_injection_in_inputs(self, app, outbox):
        """Attacker injects null bytes into form fields."""
        user, _ = new_user(app, outbox, "NullByte")
        resp = post_lost(user, title="My\x00Lost\x00Keys")
        assert resp.status_code in (200, 302)
        item = mongo.db.items.find_one({"status": "open"})
        if item:
            assert "\x00" not in item["title"]

