"""The categories endpoint and admin-side department validation.

Both sides of the RBAC comparison have to agree on spelling: a user
granted "Underwriting" can never read a document filed under
"underwriting", and the failure is silent -- the query simply returns
nothing rather than erroring.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1.admin import _validate_departments
from app.api.v1.documents import _categories_payload
from app.documents import categories


class TestCategoriesPayload:
    def test_contains_both_lists(self):
        payload = _categories_payload()
        assert payload["doc_types"] == categories.as_options(categories.DOC_TYPES)
        assert payload["departments"] == categories.as_options(categories.DEPARTMENTS)

    def test_exposes_the_auto_sentinel_and_default(self):
        """The form needs both to build its default selection without
        hardcoding either value."""
        payload = _categories_payload()
        assert payload["auto_doc_type"] == categories.AUTO_DOC_TYPE
        assert payload["default_department"] == categories.DEFAULT_DEPARTMENT


class TestDepartmentValidation:
    def test_known_values_pass(self):
        _validate_departments("underwriting", ["general", "compliance"])

    def test_none_values_pass(self):
        """Both fields are optional on a PATCH."""
        _validate_departments(None, None)

    def test_empty_allowed_list_passes(self):
        _validate_departments("general", [])

    def test_unknown_department_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_departments("marketing", None)
        assert exc.value.status_code == 400

    def test_unknown_allowed_department_is_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_departments("general", ["underwriting", "sales"])
        assert exc.value.status_code == 400
        assert "sales" in exc.value.detail

    def test_wrong_case_is_rejected(self):
        with pytest.raises(HTTPException):
            _validate_departments("Underwriting", None)


class TestMyDocumentsScope:
    """GET /documents/mine must be scoped by uploader, not merely
    role-gated: a processor seeing every document would defeat the point of
    keeping the full list admin-only."""

    def test_query_filters_on_the_calling_user(self):
        from unittest.mock import MagicMock
        import asyncio

        from app.api.v1.documents import list_my_documents

        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        import app.api.v1.documents as documents_module

        original = documents_module.acquire
        documents_module.acquire = lambda: conn
        try:
            asyncio.run(list_my_documents(user={"id": 5, "role": "processor"}))
        finally:
            documents_module.acquire = original

        sql, params = cur.execute.call_args[0]
        assert "uploaded_by = %s" in sql
        assert params[0] == 5

    def test_approval_status_is_returned(self):
        """The UI needs it to show 'Pending review' vs 'Approved'."""
        from app.api.v1.documents import _DOCUMENT_COLUMNS

        assert "is_approved" in _DOCUMENT_COLUMNS
        assert "uploaded_by" in _DOCUMENT_COLUMNS
