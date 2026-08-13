"""Detects questions no document lookup could ever legitimately answer.

Two classes, neither of which relevance-based gating (search.py's Phase B)
can catch, because both retrieve genuinely on-topic text:

1. Requests for the requester's own account-instance data ("what is my
   credit score", "what is my account balance", "what is the status of
   my loan application"). Hexta is a static document knowledge base with
   no session, account, or applicant data of any kind -- there is no
   correct document that could ever answer "my" anything. Left
   unguarded, these retrieve a chunk that is genuinely *about* credit
   scores or applications in general and present it as if it answered
   the personal question, which relevance scoring cannot distinguish
   from a real answer since the vocabulary genuinely overlaps.
   Verified live: "What is my account balance?" retrieved a
   loan-to-value paragraph at 72.7% confidence, and "What is my credit
   score?" retrieved general minimum-score requirements at 100%.

2. Requests for help committing document or income fraud ("how do I
   forge a pay stub", "how do I fake proof of income"). The knowledge
   base's own compliance documentation (which pay stubs are required,
   how income is verified) sits close enough in vocabulary to a fraud
   question that it was returned as a 95.7%-confidence "answer" to "How
   do I forge a pay stub?" -- a compliance tool confidently engaging
   with that question is a liability regardless of the fact that the
   architecture cannot generate actual fraud instructions.

Both are intent classification, not relevance scoring: the question is
rejected for what kind of question it is, not for how well the answer
covers its words.
"""

from __future__ import annotations

import re

# Nouns that only ever refer to instance/session-specific account state --
# never a general policy figure. "my credit score" (a personal fact) is
# guarded; "the minimum credit score" or "credit score requirements" (a
# policy question the KB can genuinely answer) is not, because those
# phrasings don't match this pattern at all.
_PERSONAL_DATA_RE = re.compile(
    r"\bmy\s+(?:"
    r"account(?:\s+balance)?|balance|"
    r"credit\s+score|"
    r"(?:loan|application|approval)\s+status|"
    r"loan\s+(?:file|case)|application|"
    r"payment\s+history|"
    r"case\s+status|file\s+status"
    r")\b",
    re.IGNORECASE,
)

# "Status of my X" reads naturally with the possessive at the end
# ("What is the status of my loan application?") rather than the front,
# so it needs its own pattern -- _PERSONAL_DATA_RE anchors on "my <noun>"
# and would miss it.
_STATUS_OF_MINE_RE = re.compile(
    r"\bstatus\s+of\s+my\b",
    re.IGNORECASE,
)

# Verbs that turn an otherwise-legitimate compliance question ("what
# documents prove income?") into a request for help deceiving a lender.
_FRAUD_VERB_RE = re.compile(
    r"\b(?:forge|forging|fake|faking|falsify|falsifying|fabricate|"
    r"fabricating|doctor|doctoring|counterfeit|misrepresent|"
    r"misrepresenting|conceal|concealing|hide|hiding|lie\s+(?:about|on|to))\b",
    re.IGNORECASE,
)

# Restricted to documents/facts a lender actually relies on, so a verb
# like "hide" or "conceal" elsewhere in an unrelated sentence doesn't
# trip the guard -- both a verb and one of these targets must be present.
_FRAUD_TARGET_RE = re.compile(
    r"\b(?:pay\s?stub|income|tax\s+return|bank\s+statement|w-?2|1099|"
    r"credit\s+score|application|employment|debt|asset|down\s?payment)\b",
    re.IGNORECASE,
)


def is_personal_data_request(question: str) -> bool:
    """True for a request for the asker's own account-instance data."""
    q = question or ""
    return bool(_PERSONAL_DATA_RE.search(q) or _STATUS_OF_MINE_RE.search(q))


def is_fraud_intent(question: str) -> bool:
    """True for a request for help deceiving a lender."""
    q = question or ""
    return bool(_FRAUD_VERB_RE.search(q) and _FRAUD_TARGET_RE.search(q))


def out_of_scope_reason(question: str) -> str | None:
    """Why ``question`` is out of scope, or None if it isn't.

    Checked independently of retrieval and confidence: no amount of
    ranking or relevance tuning changes whether a static document lookup
    can answer "what is my balance" or should engage with "how do I
    forge a pay stub", so this is evaluated on the question text alone.
    """
    if is_personal_data_request(question):
        return "personal_data"
    if is_fraud_intent(question):
        return "fraud_intent"
    return None
