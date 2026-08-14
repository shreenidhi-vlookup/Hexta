"""Upload endpoint category handling.

Only the pure normalise/validate helper is unit-tested here; the
endpoint's file handling is covered by the existing integration tests.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1.upload import _resolve_category
from app.documents import categories


class TestResolveCategory:
    def test_valid_pair_passes_through(self):
        assert _resolve_category("glossary", "underwriting") == (
            "glossary",
            "underwriting",
        )

    def test_auto_doc_type_becomes_none(self):
        """'auto' is the form's way of saying 'detect it', which is
        represented downstream by the absence of an override."""
        doc_type, _ = _resolve_category(categories.AUTO_DOC_TYPE, "general")
        assert doc_type is None

    def test_blank_values_become_none(self):
        assert _resolve_category("", "") == (None, None)

    def test_missing_values_become_none(self):
        assert _resolve_category(None, None) == (None, None)

    def test_unknown_doc_type_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_category("invoice", "general")
        assert exc.value.status_code == 400
        assert "invoice" in exc.value.detail

    def test_unknown_department_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_category("policy", "marketing")
        assert exc.value.status_code == 400
        assert "marketing" in exc.value.detail

    def test_wrong_case_is_rejected_not_coerced(self):
        """Coercing would write a value the RBAC filter never matches."""
        with pytest.raises(HTTPException):
            _resolve_category("policy", "General")
