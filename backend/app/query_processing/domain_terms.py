"""Mortgage domain vocabulary.

A single, curated source of truth for three deterministic behaviours:

1. **Typo correction** — the vocabulary gates which tokens may be
   corrected, so domain terms, acronyms, numbers and percentages are
   never "corrected" away.
2. **Entity extraction** — aliases map onto canonical terms with a type.
3. **Query expansion** — aliases/acronyms expand into their canonical
   phrase so both BM25 and the embedding model see richer text.

Canonical key = canonical phrase. ``aliases`` = accepted surface forms
(abbreviations, acronyms, common variants, plurals). Everything is
lowercase — normalization lowercases before these tables are used.
"""

from __future__ import annotations

import re

# term_type values:
#   lender / program, product, document, property, metric, process, status
DOMAIN_TERMS: dict[str, dict] = {
    # --- Lenders / programs ---
    "federal housing administration": {
        "type": "lender",
        "aliases": ["fha", "fha loan", "fha loans"],
    },
    "veterans affairs": {
        "type": "lender",
        "aliases": ["va", "va loan", "va loans", "veterans administration"],
    },
    "united states department of agriculture": {
        "type": "lender",
        "aliases": ["usda", "usda loan", "usda loans"],
    },
    "conventional": {
        "type": "lender",
        "aliases": ["conventional loan", "conventional loans", "conforming loan", "conforming"],
    },
    "jumbo": {
        "type": "lender",
        "aliases": ["jumbo loan", "jumbo loans", "non conforming", "non-conforming"],
    },
    "fannie mae": {"type": "lender", "aliases": ["fannie mae", "fnma"]},
    "freddie mac": {"type": "lender", "aliases": ["freddie mac", "fhlmc"]},
    "fha 203k": {"type": "product", "aliases": ["203k", "203k loan", "fha 203k"]},

    # --- Products ---
    "adjustable rate mortgage": {
        "type": "product",
        "aliases": ["arm", "arms", "adjustable rate", "adjustable-rate mortgage", "adjustable rate mortgage"],
    },
    "fixed rate mortgage": {
        "type": "product",
        "aliases": ["fixed rate", "fixed-rate", "fixed rate mortgage", "fixed-rate mortgage"],
    },
    "helic home equity line of credit": {
        "type": "product",
        "aliases": ["heloc", "home equity line of credit", "home equity"],
    },
    "reverse mortgage": {
        "type": "product",
        "aliases": ["reverse mortgage", "reverse", "hecm", "home equity conversion mortgage"],
    },

    # --- Metrics / requirements ---
    "loan to value": {"type": "metric", "aliases": ["ltv", "loan to value", "loan-to-value", "loan to value ratio", "ltv ratio"]},
    "combined loan to value": {
        "type": "metric",
        "aliases": ["cltv", "combined loan to value", "combined ltv"],
    },
    "debt to income": {"type": "metric", "aliases": ["dti", "debt to income", "debt-to-income", "debt to income ratio"]},
    "credit score": {"type": "metric", "aliases": ["credit score", "credit scores", "fico", "fico score", "fico scores", "credit rating"]},
    "down payment": {"type": "metric", "aliases": ["down payment", "downpayment", "down payment amount"]},
    "interest rate": {"type": "metric", "aliases": ["interest rate", "interest rates", "mortgage rate", "mortgage rates", "rate", "rates"]},
    "annual percentage rate": {"type": "metric", "aliases": ["apr", "annual percentage rate"]},
    "private mortgage insurance": {
        "type": "metric",
        "aliases": ["pmi", "private mortgage insurance", "mortgage insurance"],
    },
    "mortgage insurance premium": {"type": "metric", "aliases": ["mip", "mortgage insurance premium"]},
    "closing costs": {"type": "metric", "aliases": ["closing costs", "closing fees", "closing cost"]},
    "loan amount": {"type": "metric", "aliases": ["loan amount", "loan size", "loan amounts"]},
    "origination fee": {"type": "metric", "aliases": ["origination fee", "origination fees"]},
    "appraisal fee": {"type": "metric", "aliases": ["appraisal fee", "appraisal fees"]},

    # --- Documents ---
    "w-2": {"type": "document", "aliases": ["w2", "w-2", "w 2"]},
    "pay stub": {"type": "document", "aliases": ["pay stub", "pay stubs", "paystub", "paystubs", "pay check", "paycheck", "paychecks"]},
    "bank statement": {"type": "document", "aliases": ["bank statement", "bank statements", "bank statement pages"]},
    "tax return": {"type": "document", "aliases": ["tax return", "tax returns", "tax paperwork"]},
    "1099": {"type": "document", "aliases": ["1099", "1099 form", "1099 forms", "1099s"]},
    "credit report": {"type": "document", "aliases": ["credit report", "credit reports"]},
    "loan estimate": {"type": "document", "aliases": ["loan estimate", "loan estimates"]},
    "closing disclosure": {"type": "document", "aliases": ["closing disclosure", "closing disclosures", "cd"]},
    "hud-1": {"type": "document", "aliases": ["hud 1", "hud-1", "hud1"]},
    "driver's license": {"type": "document", "aliases": ["driver license", "drivers license", "driver's license", "drivers licence", "id"]},
    "social security card": {"type": "document", "aliases": ["social security card", "ssn card", "social security number", "ssn"]},
    "green card": {"type": "document", "aliases": ["green card", "green card holder"]},
    "proof of income": {"type": "document", "aliases": ["proof of income", "income proof", "income documents"]},
    "proof of employment": {"type": "document", "aliases": ["proof of employment", "employment verification"]},
    "gift letter": {"type": "document", "aliases": ["gift letter", "gift letters"]},
    "purchase agreement": {"type": "document", "aliases": ["purchase agreement", "sales contract", "purchase contract"]},
    "pre approval letter": {"type": "document", "aliases": ["pre approval letter", "preapproval letter", "pre approval", "preapproval"]},
    "appraisal report": {"type": "document", "aliases": ["appraisal report", "appraisal"]},
    "title insurance": {"type": "document", "aliases": ["title insurance", "title commitment", "title report"]},
    "homeowners insurance": {"type": "document", "aliases": ["homeowners insurance", "home insurance", "hazard insurance", "homeowner's insurance"]},
    "flood insurance": {"type": "document", "aliases": ["flood insurance"]},
    "earnest money": {"type": "document", "aliases": ["earnest money", "earnest money deposit", "earnest"]},
    "promissory note": {"type": "document", "aliases": ["promissory note", "note", "mortgage note"]},

    # --- Property types ---
    "primary residence": {"type": "property", "aliases": ["primary residence", "primary home", "owner occupied", "owner-occupied", "owner occupied home"]},
    "second home": {"type": "property", "aliases": ["second home", "vacation home", "secondary residence", "second residence"]},
    "investment property": {"type": "property", "aliases": ["investment property", "investment properties", "investment property loan"]},
    "multi unit": {"type": "property", "aliases": ["multi unit", "multi-unit", "multifamily", "multi family", "2-4 unit", "two to four unit", "multifamily property"]},
    "condominium": {"type": "property", "aliases": ["condo", "condos", "condominium", "condominiums"]},
    "co-op": {"type": "property", "aliases": ["co op", "co-op", "coop", "cooperative"]},
    "manufactured home": {"type": "property", "aliases": ["manufactured home", "manufactured homes", "mobile home"]},

    # --- Process / status ---
    "pre approval": {"type": "process", "aliases": ["pre approval", "preapproval", "getting pre approved", "pre-qualification", "prequalification"]},
    "underwriting": {"type": "process", "aliases": ["underwriting", "underwriter", "underwriting conditions"]},
    "closing": {"type": "process", "aliases": ["closing", "closing day", "closing process", "settlement"]},
    "appraisal": {"type": "process", "aliases": ["appraisal", "home appraisal", "house appraisal"]},
    "escrow": {"type": "process", "aliases": ["escrow", "escrow account"]},
    "title search": {"type": "process", "aliases": ["title search", "title"]},
    "rate lock": {"type": "process", "aliases": ["rate lock", "rate locking", "lock rate"]},
    "occupancy": {"type": "status", "aliases": ["occupancy", "occupancy requirement", "owner occupancy"]},
    "seasoning": {"type": "status", "aliases": ["seasoning", "seasoning requirement"]},
    "cash out": {"type": "process", "aliases": ["cash out", "cash-out", "cash out refinance"]},
    "bankruptcy": {"type": "status", "aliases": ["bankruptcy", "bankruptcies"]},
    "foreclosure": {"type": "status", "aliases": ["foreclosure", "foreclosures"]},
    "loan program": {"type": "process", "aliases": ["loan program", "loan programs", "program guidelines"]},
    "underwriting conditions": {"type": "process", "aliases": ["conditions", "loan conditions", "underwriting conditions"]},

    # --- Later life / equity release ---
    "equity release": {
        "type": "product",
        "aliases": ["equity release", "equity release scheme", "later life lending", "later life equity release", "release equity", "release money from home"],
    },
    "lifetime mortgage": {
        "type": "product",
        "aliases": ["lifetime mortgage", "lifetime mortgages", "equity release lifetime mortgage", "mortgage for life"],
    },
    "home reversion": {"type": "product", "aliases": ["home reversion", "home reversion scheme"]},

    # --- Protection ---
    "critical illness insurance": {
        "type": "product",
        "aliases": ["critical illness", "critical illness insurance", "critical illness cover", "critical illness policy"],
    },
    "income protection": {
        "type": "product",
        "aliases": ["income protection", "income protection insurance", "income protection policy"],
    },
    "deferred period": {"type": "metric", "aliases": ["deferred period", "deferral period"]},

    # --- Lending processes ---
    "product transfer": {
        "type": "process",
        "aliases": ["product transfer", "product switch", "switching products", "switch products", "switch mortgage product"],
    },
    "bridging finance": {
        "type": "product",
        "aliases": ["bridging finance", "bridging loan", "bridge loan", "bridging finance loan"],
    },

    # --- Data protection / privacy ---
    "subject access request": {
        "type": "process",
        "aliases": ["subject access request", "sar", "data access request"],
    },
    "data erasure": {
        "type": "process",
        "aliases": ["data erasure", "erase my data", "erase my information", "erase my personal details", "delete my data", "delete my information", "delete my personal details", "remove my data", "remove my information"],
    },
}

# Additional common English / query words that must never be "corrected"
# into a domain term, and which join the typo-correction vocabulary.
COMMON_WORDS: set[str] = {
    "a", "about", "above", "after", "again", "all", "allowed", "also", "amount",
    "an", "and", "any", "are", "as", "at", "be", "because", "before", "between",
    "but", "by", "can", "cannot", "could", "do", "does", "during", "each", "eligible",
    "eligibility", "employment", "even", "for", "from", "get", "give", "has", "have",
    "he", "her", "his", "how", "i", "if", "in", "income", "into", "is", "it", "its",
    "just", "like", "list", "many", "may", "me", "might", "more", "most", "much",
    "must", "my", "need", "needed", "needs", "no", "not", "now", "of", "on", "one",
    "only", "or", "other", "our", "out", "over", "please", "plus", "required",
    "requires", "show", "some", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "us", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "without",
    "would", "you", "your", "minimum", "maximum", "max", "min", "limit", "limits",
     "required", "requirement", "requirements", "threshold", "document", "documents",
     "paperwork", "form", "forms", "month", "months", "year", "years", "percent",
     "percentage", "process", "steps", "step", "time", "day", "days", "checklist",
     "credit", "score", "fico", "loan", "money", "funds", "down", "payment",
     "investment", "property", "properties", "value", "home", "house",
     "lender", "borrower", "applicant", "mortgage", "refinance",
     "finance", "financial", "financing", "borrow", "borrowing", "borrowed",
     "deposit", "deposits", "debt", "debts", "repay", "repayment",
     "repayments", "repaid", "remortgage", "protection", "insurance",
     "affordability", "collateral", "creditworthiness",
     "verify", "verified", "verification", "job", "jobs",
}

# Phrases that indicate a new question when they start a fragment.
QUESTION_STARTERS: set[str] = {
    "what", "how", "why", "when", "where", "who", "which", "whose",
    "is", "are", "do", "does", "did", "can", "could", "will", "would",
    "should", "may", "might", "must",
    "tell", "list", "show", "give", "provide", "need", "explain", "define", "describe",
    "max", "min", "maximum", "minimum",
}

# Words that are noise when a "question" fragment collapses to just them.
NOISE_WORDS: set[str] = {"help", "please", "hi", "hey", "hello", "ok", "okay", "thanks", "thank", "urgent", "asap"}

# Conjunctive/connective prefixes stripped before testing independence.
CONNECTIVE_RE = re.compile(r"^(?:and\s+)?(?:also|plus|additionally|in addition|then|or|and)\s+", re.IGNORECASE)

# Terms whose presence signals a particular intent (used by intent detection).
INTENT_KEYWORDS: dict[str, set[str]] = {
    "limits": {"max", "min", "maximum", "minimum", "limit", "limits", "threshold", "cap", "high", "low"},
    "documents": {"document", "documents", "paperwork", "forms", "form", "checklist", "what do i need"},
    "eligibility": {"eligible", "eligibility", "qualify", "qualification", "can i", "allowed"},
    "requirements": {"require", "requires", "required", "requirement", "requirements", "need", "needed", "must"},
    "process": {"process", "steps", "step", "how to", "how do", "procedure", "timeline", "how long"},
    "costs": {"rate", "rates", "cost", "costs", "fee", "fees", "apr", "pmi", "mip", "premium", "insurance", "price"},
    "definition": {"what is", "what are", "define", "meaning", "explain"},
}

# doc_type boost map for intents (used by ranking metadata boost).
INTENT_DOC_TYPE_BOOST: dict[str, set[str]] = {
    "documents": {"checklist", "form_guide"},
    "process": {"process", "program_guide"},
    "requirements": {"policy", "program_guide"},
    "limits": {"policy", "program_guide"},
}

# Alias table: every surface form -> (canonical, type). Built once.
_ALIAS_INDEX: dict[str, tuple[str, str]] = {}
for _canonical, _meta in DOMAIN_TERMS.items():
    _aliases = set(_meta["aliases"]) | {_canonical}
    for _alias in _aliases:
        _ALIAS_INDEX[_alias] = (_canonical, _meta["type"])


def aliases() -> set[str]:
    return set(_ALIAS_INDEX.keys())


def canonical_of(alias: str) -> str:
    """Canonical form of a known alias, or ``alias`` unchanged if unknown.

    Bug history: this used to be ``_ALIAS_INDEX.get(alias, alias)[0]`` — when
    ``alias`` wasn't in the index, the fallback was the bare string ``alias``,
    and the trailing ``[0]`` then indexed into *that string*, silently
    returning just its first character instead of the alias itself. Callers
    that don't happen to filter short results (unlike search.py's
    ``_query_content_terms``, which drops anything under 3 chars) would get
    a corrupted single-character "canonical" term.
    """
    entry = _ALIAS_INDEX.get(alias)
    return entry[0] if entry else alias


def type_of(alias: str) -> str | None:
    entry = _ALIAS_INDEX.get(alias)
    return entry[1] if entry else None


def multiword_aliases() -> list[str]:
    return [a for a in _ALIAS_INDEX if " " in a]


# Scenario → concept mapping. Users describe a situation instead of
# naming the underlying product/concept. When a pattern matches a
# sub-query, its concept is appended to the expanded search text so the
# retrieval step sees the canonical term. Patterns are applied to
# lowercased, normalized query text.
SCENARIO_CONCEPTS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"(?:over\s+(?:5[5-9]|[6-8]\d)\b"
            r"|(?:aged?|is|are|turns?)\s+(?:5[5-9]|[6-9]\d)\b"
            r"|(?:5[5-9]|[6-9]\d)\s+years?\s+old\b"
            r"|retir(?:e|ed|ing)?\b"
            r"|pension(?:er|ers| income)?\b"
            r"|(?:not|without)\s+sell(?:ing)?\s+(?:the\s+)?(?:home|house|property)\b"
            r"|stay(?:ing)?\s+in\s+(?:my|the|their|our)?\s*(?:home|house|property)\b"
            r"|access\s+(?:to\s+)?(?:some\s+)?(?:money|cash)\s+(?:from|out\s+of|in)\s+(?:the\s+|my\s+)?(?:home|house|property)\b"
            r"|access\s+to\s+(?:some\s+)?(?:money|cash)\b"
            r"|release\s+(?:cash|money|equity)\b"
            r"|raise\s+money\s+(?:from|against)\s+(?:the\s+|my\s+)?(?:home|property)\b"
            r"|equity\s+in\s+(?:my\s+)?(?:home|property)\b)"
        ),
        "equity release",
    ),
    (
        re.compile(
            r"(?:bridging\s+finance\b|bridge\s+loan\b|short[-\s]?term\s+gap\b|"
            r"buying\s+before\s+selling\b|chain\s+(?:break|broken)\b)"
        ),
        "bridging finance",
    ),
    (
        re.compile(
            r"(?:switch(?:ing)?\s+(?:my\s+)?(?:mortgage\s+)?product\b|"
            r"change\s+(?:my\s+)?mortgage\s+product\b|new\s+product\s+with\s+same\s+lender\b)"
        ),
        "product transfer",
    ),
    (
        re.compile(
            r"\b(?:when|if|after|once|until|should|before)\s+"
            r"(?:(?:the|my|your|their|our)\s+)?"
            r"(?:borrower|homeowner|owner|someone|somebody|they|them|i|you|we|he|she|both|either)\s+"
            r"(?:die[sd]?|died|pass(?:es|ed)?\s+away|pass(?:es|ed)?\s+on|decease[sd]?)\b"
            r"|\b(?:repay|repaid|repayment|repayments)\s+on\s+death|in\s+the\s+event\s+of\s+death|"
            r"sold\s+to\s+repay|sale\s+of\s+the\s+(?:home|house|property)\s+to\s+repay\b"
        ),
        "lifetime mortgage equity release loan repaid from the sale of the property",
    ),
]


def scenario_concepts_for(text: str) -> list[str]:
    """Return canonical concepts whose scenario pattern matches ``text``.

    Deterministic and dependency-free; used by the query pipeline to
    enrich the expanded search text with the canonical term.
    """
    lower = text.lower()
    seen: set[str] = set()
    out: list[str] = []
    for pattern, concept in SCENARIO_CONCEPTS:
        if pattern.search(lower) and concept not in seen:
            seen.add(concept)
            out.append(concept)
    return out
