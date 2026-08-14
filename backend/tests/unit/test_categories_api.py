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
