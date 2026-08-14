"""Unit tests for the shared document category vocabulary."""

from __future__ import annotations

from app.auth import rbac
from app.documents import categories


class TestVocabulary:
    def test_doc_types_and_departments_are_non_empty(self):
        assert categories.DOC_TYPES
        assert categories.DEPARTMENTS

    def test_values_are_unique(self):
        assert len(categories.doc_type_values()) == len(categories.DOC_TYPES)
        assert len(categories.department_values()) == len(categories.DEPARTMENTS)

    def test_values_are_lowercase_slugs(self):
        """Values are compared against database contents, so casing and
        spacing must be fixed at the vocabulary rather than per call site."""
        for value in categories.doc_type_values() | categories.department_values():
            assert value == value.lower()
            assert " " not in value

    def test_default_department_is_in_the_vocabulary(self):
        assert categories.DEFAULT_DEPARTMENT in categories.department_values()

    def test_default_department_matches_rbac(self):
        """rbac resolves an absent department to its own default; a
        mismatch here would make documents unreachable by everyone."""
        assert categories.DEFAULT_DEPARTMENT == rbac.DEFAULT_DEPARTMENT


class TestValidation:
    def test_known_doc_type_is_valid(self):
        assert categories.is_valid_doc_type("glossary")

    def test_auto_is_a_valid_doc_type(self):
        """'auto' means 'infer from content at ingest'."""
        assert categories.is_valid_doc_type(categories.AUTO_DOC_TYPE)

    def test_unknown_doc_type_is_rejected(self):
        assert not categories.is_valid_doc_type("invoice")

    def test_doc_type_validation_is_case_sensitive(self):
        """Silently accepting 'Glossary' would write a value that never
        matches the vocabulary again."""
        assert not categories.is_valid_doc_type("Glossary")

    def test_known_department_is_valid(self):
        assert categories.is_valid_department("underwriting")

    def test_auto_is_not_a_valid_department(self):
        """Department is never inferred -- there is nothing to infer from."""
        assert not categories.is_valid_department(categories.AUTO_DOC_TYPE)

    def test_unknown_department_is_rejected(self):
        assert not categories.is_valid_department("marketing")

    def test_empty_and_none_are_rejected(self):
        for value in ("", None):
            assert not categories.is_valid_doc_type(value)
            assert not categories.is_valid_department(value)


class TestOptions:
    def test_as_options_returns_value_label_pairs(self):
        options = categories.as_options(categories.DEPARTMENTS)
        assert {"value": "general", "label": "General (all staff)"} in options

    def test_as_options_preserves_order(self):
        options = categories.as_options(categories.DOC_TYPES)
        assert [o["value"] for o in options] == [c.value for c in categories.DOC_TYPES]


class TestInternalHowToTypes:
    """Staff asking "how do I do X in our CRM" is a documentation need, not
    a client-data need -- these types make that content first-class."""

    def test_system_guide_is_available(self):
        assert categories.is_valid_doc_type("system_guide")

    def test_sop_is_available(self):
        assert categories.is_valid_doc_type("sop")

    def test_both_appear_in_the_served_options(self):
        values = [o["value"] for o in categories.as_options(categories.DOC_TYPES)]
        assert "system_guide" in values
        assert "sop" in values
