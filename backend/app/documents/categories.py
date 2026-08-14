"""Document category vocabulary — the single source of truth.

Both halves of a document's category are declared here so that adding one
is a backend-only change: the upload endpoint validates against these
lists, the ingester resolves against them, and the admin form renders
whatever ``GET /documents/categories`` returns rather than carrying its
own copy.

The two fields answer different questions and are deliberately kept
apart. ``doc_type`` is organisational -- what kind of document this is.
``department`` is the access-control dimension: it is the column the RBAC
filter matches on (search/metadata_filters.py), so a document filed under
a department is readable only by users holding that department, plus
admins, who bypass department filtering entirely.

Values are lowercase slugs because they are compared against text stored
in Postgres. Accepting "Glossary" would write a value that no later
lookup matches, so validation is case-sensitive by design.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    value: str
    label: str


# Sentinel for "let ingestion infer the type from the content". Only valid
# for doc_type: department has nothing to infer from, so it falls back to
# DEFAULT_DEPARTMENT instead.
AUTO_DOC_TYPE = "auto"

# Kept in step with auth.rbac.DEFAULT_DEPARTMENT (asserted in tests): a
# document filed under a department nobody holds is readable by nobody.
DEFAULT_DEPARTMENT = "general"

DOC_TYPES: tuple[Category, ...] = (
    Category("glossary", "Glossary / definitions"),
    Category("policy", "Policy"),
    Category("procedure", "Procedure"),
    Category("underwriting", "Underwriting"),
    Category("eligibility", "Eligibility"),
    Category("compliance", "Compliance"),
    Category("product_guide", "Product guide"),
    # "How do I assign a case to another adviser?" is one of the most
    # common things staff currently interrupt an admin to ask, and the
    # answer is a document, not client data. The vendor's own help centre
    # sits behind a login, so what belongs here is the firm's own written
    # process for its tools.
    Category("system_guide", "System guide (Intelliflo, tools)"),
    Category("sop", "Internal process / SOP"),
)

DEPARTMENTS: tuple[Category, ...] = (
    Category("general", "General (all staff)"),
    Category("underwriting", "Underwriting"),
    Category("compliance", "Compliance"),
    Category("origination", "Origination"),
    Category("servicing", "Servicing"),
)


def doc_type_values() -> set[str]:
    return {c.value for c in DOC_TYPES}


def department_values() -> set[str]:
    return {c.value for c in DEPARTMENTS}


def is_valid_doc_type(value: str | None) -> bool:
    if not value:
        return False
    return value == AUTO_DOC_TYPE or value in doc_type_values()


def is_valid_department(value: str | None) -> bool:
    if not value:
        return False
    return value in department_values()


def as_options(categories: tuple[Category, ...]) -> list[dict[str, str]]:
    """Serialise for the categories endpoint / form rendering."""
    return [{"value": c.value, "label": c.label} for c in categories]
