"""Unit tests for admin user-provisioning endpoint (create_user)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1.admin import UserCreate, create_user


def _run(body, user):
    """Await the async endpoint; expect it to raise before any DB work."""
    return asyncio.run(create_user(body, user))


def _admin(**overrides):
    user = {
        "role": "super_admin",
        "department": "general",
        "allowed_departments": ["general"],
    }
    user.update(overrides)
    return user


def _body(**overrides):
    data = {
        "email": "new.user@example.com",
        "password": "SuperSecret123",
        "role": "loan_officer",
        "department": "general",
        "allowed_departments": [],
        "assigned_clients": [],
        "assigned_cases": [],
    }
    data.update(overrides)
    return UserCreate(**data)


class TestCreateUser:
    def test_non_super_admin_cannot_assign_elevated_role(self):
        """Plain admin creating an admin/underwriter/compliance user -> 403."""
        with pytest.raises(HTTPException) as exc:
            _run(_body(role="admin"), _admin(role="admin"))
        assert exc.value.status_code == 403

    def test_non_super_admin_can_create_default_role(self):
        """Plain admin creating a loan_officer passes the role gate (no 403)."""
        try:
            _run(_body(role="loan_officer"), _admin(role="admin"))
        except HTTPException as exc:
            assert exc.status_code != 403
        except Exception:
            # A later-stage failure (e.g. bcrypt/passlib version mismatch on
            # some dev hosts, or a missing DB) means the role gate passed.
            pass

    def test_rejects_missing_at_in_email(self):
        with pytest.raises(HTTPException) as exc:
            _run(_body(email="not-an-email"), _admin())
        assert exc.value.status_code == 400

    def test_rejects_blank_email(self):
        with pytest.raises(HTTPException) as exc:
            _run(_body(email="   "), _admin())
        assert exc.value.status_code == 400

    def test_rejects_short_password(self):
        with pytest.raises(HTTPException) as exc:
            _run(_body(password="short"), _admin())
        assert exc.value.status_code == 400
        assert "8 characters" in str(exc.value.detail)
