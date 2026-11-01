"""
UNIT TESTS: Pure function tests for utils/, models.py, forms.py.
No HTTP requests or integration — each function tested in isolation.
"""
import hashlib
import hmac
import math
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId
from PIL import Image

from conftest import DOMAIN, PASSWORD

# ============================================================================
# 1. utils/validators.py — Pure functions
# ============================================================================


class TestNormalizeEmail:
    def test_strips_whitespace(self, app):
        from utils.validators import normalize_email
        assert normalize_email("  Alice@COLLEGE.edu.in  ") == "alice@college.edu.in"

    def test_lowercases(self, app):
        from utils.validators import normalize_email
        assert normalize_email("UPPER@CASE.COM") == "upper@case.com"

    def test_none_returns_empty(self, app):
        from utils.validators import normalize_email
        assert normalize_email(None) == ""

    def test_empty_returns_empty(self, app):
        from utils.validators import normalize_email
        assert normalize_email("") == ""


class TestIsCollegeEmail:
    def test_valid_college_email(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email(f"student@{DOMAIN}") is True

    def test_subdomain_accepted(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email(f"student@cs.{DOMAIN}") is True

    def test_gmail_rejected(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email("student@gmail.com") is False

    def test_no_at_rejected(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email("noemail") is False

    def test_double_at_rejected(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email(f"a@@{DOMAIN}") is False

    def test_empty_local_rejected(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email(f"@{DOMAIN}") is False

    def test_empty_domain_rejected(self, app):
        from utils.validators import is_college_email
        with app.app_context():
            assert is_college_email("student@") is False


class TestPasswordProblems:
    def test_strong_password_passes(self, app):
        from utils.validators import password_problems
        with app.app_context():
            assert password_problems("Str0ng!Pass") == []

    def test_too_short(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("Ab1!")
            assert any("8 characters" in p for p in result)

    def test_no_uppercase(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("weak1234!")
            assert any("uppercase" in p for p in result)

    def test_no_number(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("NoNumber!")
            assert any("number" in p for p in result)

    def test_no_special(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("NoSpecial1")
            assert any("special" in p for p in result)

    def test_too_long(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("A1!" + "x" * 65)
            assert any("at most" in p for p in result)

    def test_empty_password(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems("")
            assert len(result) >= 1

    def test_none_password(self, app):
        from utils.validators import password_problems
        with app.app_context():
            result = password_problems(None)
            assert len(result) >= 1


class TestCleanText:
    def test_strips_control_chars(self, app):
        from utils.validators import clean_text
        assert "\x00" not in clean_text("hello\x00world")
        assert "\x07" not in clean_text("bell\x07char")

    def test_normalises_newlines(self, app):
        from utils.validators import clean_text
        assert clean_text("a\r\nb\rc") == "a\nb\nc"

    def test_collapses_excess_newlines(self, app):
        from utils.validators import clean_text
        assert clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_trims_whitespace(self, app):
        from utils.validators import clean_text
        assert clean_text("  hello  ") == "hello"

    def test_non_string_passthrough(self, app):
        from utils.validators import clean_text
        assert clean_text(42) == 42


class TestCleanLine:
    def test_strips_control_chars(self, app):
        from utils.validators import clean_line
        assert "\x00" not in clean_line("hello\x00world")

    def test_collapses_whitespace(self, app):
        from utils.validators import clean_line
        assert clean_line("a   b\t\tc") == "a b c"

    def test_trims(self, app):
        from utils.validators import clean_line
        assert clean_line("  hello  ") == "hello"

    def test_non_string_passthrough(self, app):
        from utils.validators import clean_line
        assert clean_line(None) is None


class TestParseObjectId:
    def test_valid_id(self, app):
        from utils.validators import parse_object_id
        oid = ObjectId()
        with app.test_request_context():
            assert parse_object_id(str(oid)) == oid

    def test_invalid_id_aborts_404(self, app):
        from utils.validators import parse_object_id
        with app.test_request_context():
            with pytest.raises(Exception):  # werkzeug 404
                parse_object_id("not-an-id")

    def test_none_aborts_404(self, app):
        from utils.validators import parse_object_id
        with app.test_request_context():
            with pytest.raises(Exception):
                parse_object_id(None)


class TestIsSafeRedirect:
    def test_safe_path(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect("/dashboard") is True

    def test_rejects_absolute_url(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect("https://evil.com") is False

    def test_rejects_double_slash(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect("//evil.com") is False

    def test_rejects_backslash(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect("/\\evil.com") is False

    def test_rejects_none(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect(None) is False

    def test_rejects_empty(self, app):
        from utils.validators import is_safe_redirect
        with app.test_request_context():
            assert is_safe_redirect("") is False


class TestMaskEmail:
    def test_normal_email(self, app):
        from utils.validators import mask_email
        result = mask_email("student.name@college.edu")
        assert result.startswith("st")
        assert "***" in result
        assert result.endswith("@college.edu")

    def test_short_local(self, app):
        from utils.validators import mask_email
        result = mask_email("ab@c.com")
        assert "@c.com" in result

    def test_single_char_local(self, app):
        from utils.validators import mask_email
        result = mask_email("a@c.com")
        assert result.startswith("a")
        assert "@c.com" in result

    def test_none(self, app):
        from utils.validators import mask_email
        assert mask_email(None) == ""

    def test_no_at(self, app):
        from utils.validators import mask_email
        assert mask_email("noemail") == "noemail"


# ============================================================================
# 2. utils/helpers.py — Time and pagination
# ============================================================================


class TestUtcnow:
    def test_returns_aware_utc(self, app):
        from utils.helpers import utcnow
        now = utcnow()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc


class TestAsUtc:
    def test_naive_gets_utc(self, app):
        from utils.helpers import as_utc
        naive = datetime(2026, 1, 1, 12, 0)
        aware = as_utc(naive)
        assert aware.tzinfo == timezone.utc

    def test_aware_stays_same(self, app):
        from utils.helpers import as_utc
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert as_utc(aware) is aware

    def test_none_stays_none(self, app):
        from utils.helpers import as_utc
        assert as_utc(None) is None


class TestPageArg:
    def test_valid_page(self, app):
        from utils.helpers import page_arg
        with app.test_request_context("/?page=3"):
            from flask import request
            assert page_arg(request) == 3

    def test_negative_clamped(self, app):
        from utils.helpers import page_arg
        with app.test_request_context("/?page=-5"):
            from flask import request
            assert page_arg(request) == 1

    def test_invalid_defaults_to_1(self, app):
        from utils.helpers import page_arg
        with app.test_request_context("/?page=abc"):
            from flask import request
            assert page_arg(request) == 1

    def test_missing_defaults_to_1(self, app):
        from utils.helpers import page_arg
        with app.test_request_context("/"):
            from flask import request
            assert page_arg(request) == 1


# ============================================================================
# 3. models.py — User model
# ============================================================================


class TestUserModel:
    def _make_doc(self, **overrides):
        doc = {
            "_id": ObjectId(),
            "name": "Test User",
            "email": f"test@{DOMAIN}",
            "role": "user",
            "is_verified": True,
            "is_banned": False,
            "trust_score": 100,
            "rejected_claims": 0,
            "session_token": "test-token",
            "password_hash": "$2b$04$fake",
        }
        doc.update(overrides)
        return doc

    def test_id_is_string(self, app):
        from models import User
        doc = self._make_doc()
        user = User(doc)
        assert user.id == str(doc["_id"])

    def test_oid_is_objectid(self, app):
        from models import User
        doc = self._make_doc()
        user = User(doc)
        assert isinstance(user.oid, ObjectId)

    def test_get_id_includes_session_token(self, app):
        from models import User
        doc = self._make_doc(session_token="abc123")
        user = User(doc)
        assert user.get_id() == f"{doc['_id']}:abc123"

    def test_is_admin_true(self, app):
        from models import User
        user = User(self._make_doc(role="admin"))
        assert user.is_admin is True

    def test_is_admin_false(self, app):
        from models import User
        user = User(self._make_doc(role="user"))
        assert user.is_admin is False

    def test_is_active_when_not_banned(self, app):
        from models import User
        user = User(self._make_doc(is_banned=False))
        assert user.is_active is True

    def test_is_inactive_when_banned(self, app):
        from models import User
        user = User(self._make_doc(is_banned=True))
        assert user.is_active is False

    def test_can_claim_when_under_limit(self, app):
        from models import User
        with app.app_context():
            user = User(self._make_doc(rejected_claims=0))
            assert user.can_claim is True

    def test_cannot_claim_at_limit(self, app):
        from models import User
        with app.app_context():
            user = User(self._make_doc(rejected_claims=3))
            assert user.can_claim is False

    def test_first_name(self, app):
        from models import User
        user = User(self._make_doc(name="John Doe"))
        assert user.first_name == "John"

    def test_first_name_empty(self, app):
        from models import User
        user = User(self._make_doc(name=""))
        assert user.first_name == ""


# ============================================================================
# 4. utils/otp.py — OTP generation and hashing
# ============================================================================


class TestOtpGeneration:
    def test_generate_otp_is_6_digits(self, app):
        from utils.otp import generate_otp
        with app.app_context():
            code = generate_otp()
            assert re.match(r"^\d{6}$", code)

    def test_generate_otp_is_zero_padded(self, app):
        from utils.otp import generate_otp
        with app.app_context():
            # Run enough times to hit low numbers
            for _ in range(100):
                code = generate_otp()
                assert len(code) == 6

    def test_hash_otp_is_deterministic(self, app):
        from utils.otp import hash_otp
        with app.app_context():
            h1 = hash_otp("123456", purpose="register", subject="a@b.com")
            h2 = hash_otp("123456", purpose="register", subject="a@b.com")
            assert h1 == h2

    def test_hash_otp_purpose_matters(self, app):
        from utils.otp import hash_otp
        with app.app_context():
            h1 = hash_otp("123456", purpose="register", subject="a@b.com")
            h2 = hash_otp("123456", purpose="reset", subject="a@b.com")
            assert h1 != h2

    def test_hash_otp_subject_matters(self, app):
        from utils.otp import hash_otp
        with app.app_context():
            h1 = hash_otp("123456", purpose="register", subject="a@b.com")
            h2 = hash_otp("123456", purpose="register", subject="c@d.com")
            assert h1 != h2

    def test_check_otp_hash_correct(self, app):
        from utils.otp import check_otp_hash, hash_otp
        with app.app_context():
            h = hash_otp("654321", purpose="register", subject="x@y.com")
            assert check_otp_hash("654321", h, purpose="register", subject="x@y.com") is True

    def test_check_otp_hash_wrong_code(self, app):
        from utils.otp import check_otp_hash, hash_otp
        with app.app_context():
            h = hash_otp("654321", purpose="register", subject="x@y.com")
            assert check_otp_hash("000000", h, purpose="register", subject="x@y.com") is False

    def test_check_otp_hash_empty_inputs(self, app):
        from utils.otp import check_otp_hash
        with app.app_context():
            assert check_otp_hash("", "somehash", purpose="register", subject="x") is False
            assert check_otp_hash("123456", "", purpose="register", subject="x") is False
            assert check_otp_hash(None, None, purpose="register", subject="x") is False


# ============================================================================
# 5. utils/matcher.py — Answer similarity
# ============================================================================


class TestAnswerSimilarity:
    def test_identical_answers(self, app):
        from utils.matcher import answer_similarity
        assert answer_similarity("Brown", "Brown") == 100

    def test_case_insensitive(self, app):
        from utils.matcher import answer_similarity
        assert answer_similarity("brown", "Brown") == 100

    def test_partial_match(self, app):
        from utils.matcher import answer_similarity
        score = answer_similarity("Metro card", "Metro card and some cash")
        assert 30 < score < 100

    def test_empty_answer(self, app):
        from utils.matcher import answer_similarity
        assert answer_similarity("", "Brown") == 0

    def test_empty_expected(self, app):
        from utils.matcher import answer_similarity
        assert answer_similarity("Brown", "") == 0

    def test_both_empty(self, app):
        from utils.matcher import answer_similarity
        assert answer_similarity("", "") == 0

    def test_completely_different(self, app):
        from utils.matcher import answer_similarity
        score = answer_similarity("xyz", "abc")
        assert score < 50


# ============================================================================
# 6. utils/uploads.py — File ID regex
# ============================================================================


class TestPrivatePath:
    def test_valid_items_path(self, app):
        from utils.uploads import private_path
        with app.app_context():
            folder, filename = private_path("items", "a" * 32)
            assert folder is not None
            assert filename == "a" * 32 + ".jpg"

    def test_valid_proofs_path(self, app):
        from utils.uploads import private_path
        with app.app_context():
            folder, filename = private_path("proofs", "b" * 32)
            assert folder is not None

    def test_invalid_kind_returns_none(self, app):
        from utils.uploads import private_path
        with app.app_context():
            assert private_path("hacked", "a" * 32) == (None, None)

    def test_invalid_file_id_returns_none(self, app):
        from utils.uploads import private_path
        with app.app_context():
            assert private_path("items", "short") == (None, None)
            assert private_path("items", "../../../etc/passwd") == (None, None)
            assert private_path("items", None) == (None, None)
            assert private_path("items", "") == (None, None)

    def test_sql_injection_in_file_id(self, app):
        from utils.uploads import private_path
        with app.app_context():
            assert private_path("items", "'; DROP TABLE items;--") == (None, None)


# ============================================================================
# 7. utils/notifications.py
# ============================================================================


class TestNotify:
    def test_notify_creates_document(self, app):
        from extensions import mongo
        from utils.notifications import notify
        with app.app_context():
            uid = ObjectId()
            notify(uid, "Test message", "system")
            doc = mongo.db.notifications.find_one({"user_id": uid})
            assert doc is not None
            assert doc["message"] == "Test message"
            assert doc["is_read"] is False

    def test_notify_truncates_long_message(self, app):
        from extensions import mongo
        from utils.notifications import notify
        with app.app_context():
            uid = ObjectId()
            notify(uid, "x" * 500, "system")
            doc = mongo.db.notifications.find_one({"user_id": uid})
            assert len(doc["message"]) <= 300

    def test_notify_admins(self, app):
        from extensions import mongo
        from utils.notifications import notify_admins
        with app.app_context():
            admin_id = mongo.db.users.insert_one({
                "name": "Admin", "email": f"admin@{DOMAIN}", "role": "admin",
                "is_banned": False, "is_verified": True,
            }).inserted_id
            notify_admins("Alert!", "admin")
            doc = mongo.db.notifications.find_one({"user_id": admin_id})
            assert doc is not None
            assert doc["message"] == "Alert!"


# ============================================================================
# 8. utils/decorators.py
# ============================================================================


class TestAdminRequired:
    def test_unauthenticated_redirected(self, client):
        response = client.get("/admin/")
        assert response.status_code == 302

    def test_normal_user_gets_403(self, app, outbox):
        from conftest import new_user
        user, _ = new_user(app, outbox, "Regular")
        assert user.get("/admin/").status_code == 403

    def test_admin_gets_200(self, app):
        from conftest import new_admin
        admin = new_admin(app)
        assert admin.get("/admin/").status_code == 200


# ============================================================================
# 9. utils/icons.py
# ============================================================================


class TestIcon:
    def test_known_icon(self, app):
        from utils.icons import icon
        svg = icon("search")
        assert "svg" in str(svg)
        assert "search" not in str(svg) or "icon" in str(svg)

    def test_unknown_icon_falls_back(self, app):
        from utils.icons import icon
        svg = icon("nonexistent-icon")
        # Should fall back to "info" icon
        assert "svg" in str(svg)

    def test_custom_class(self, app):
        from utils.icons import icon
        svg = icon("search", cls="large")
        assert "large" in str(svg)

    def test_xss_in_class(self, app):
        from utils.icons import icon
        svg = icon("search", cls='"><script>alert(1)</script>')
        result = str(svg)
        assert "<script>" not in result


# ============================================================================
# 10. Password hashing (routes/auth.py helpers)
# ============================================================================


class TestPasswordHashing:
    def test_hash_and_check(self, app):
        from routes.auth import check_password, hash_password
        with app.app_context():
            h = hash_password("Test!Pass1")
            assert check_password("Test!Pass1", h) is True
            assert check_password("WrongPass1!", h) is False

    def test_hash_is_bcrypt(self, app):
        from routes.auth import hash_password
        with app.app_context():
            h = hash_password("Test!Pass1")
            assert h.startswith("$2b$")

    def test_check_handles_str_and_bytes(self, app):
        from routes.auth import check_password, hash_password
        with app.app_context():
            h = hash_password("Test!Pass1")
            assert check_password("Test!Pass1", h) is True
            assert check_password("Test!Pass1", h.encode("utf-8")) is True

    def test_check_handles_invalid_hash(self, app):
        from routes.auth import check_password
        with app.app_context():
            assert check_password("anything", "not-a-hash") is False


# ============================================================================
# 11. config.py — env helpers
# ============================================================================


class TestEnvBool:
    def test_true_values(self):
        from config import env_bool
        import os
        for val in ("1", "true", "yes", "on", "TRUE", " Yes "):
            os.environ["_TEST_BOOL"] = val
            assert env_bool("_TEST_BOOL") is True
        os.environ.pop("_TEST_BOOL", None)

    def test_false_values(self):
        from config import env_bool
        import os
        for val in ("0", "false", "no", "off", "anything"):
            os.environ["_TEST_BOOL"] = val
            assert env_bool("_TEST_BOOL") is False
        os.environ.pop("_TEST_BOOL", None)

    def test_missing_uses_default(self):
        from config import env_bool
        import os
        os.environ.pop("_TEST_BOOL_MISSING", None)
        assert env_bool("_TEST_BOOL_MISSING") is False
        assert env_bool("_TEST_BOOL_MISSING", True) is True


class TestEnvList:
    def test_comma_separated(self):
        from config import env_list
        import os
        os.environ["_TEST_LIST"] = "a, b, c"
        assert env_list("_TEST_LIST") == ["a", "b", "c"]
        os.environ.pop("_TEST_LIST", None)

    def test_empty_parts_filtered(self):
        from config import env_list
        import os
        os.environ["_TEST_LIST"] = "a,,b,,"
        assert env_list("_TEST_LIST") == ["a", "b"]
        os.environ.pop("_TEST_LIST", None)

    def test_missing_uses_default(self):
        from config import env_list
        import os
        os.environ.pop("_TEST_LIST_MISS", None)
        assert env_list("_TEST_LIST_MISS", "x,y") == ["x", "y"]

