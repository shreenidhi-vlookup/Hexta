"""Retrieval regression suite for the firm's process SOP.

Companion to ``retrieval_regression.py``, which covers the mortgage
glossary. This one covers a very differently-shaped document: a 22-page
procedure SOP that reached the index through OCR, full of numbered steps,
short bullet lists and colon-terminated preambles.

Every question below is answerable from the SOP's own text — none are
invented, and the expected fragments are quoted from the document. The
negative cases are questions the SOP genuinely does not answer *and*
which the glossary does not answer either, so they exercise the
answerability gate rather than accidentally matching the other document
in the corpus.

Usage (the SOP must be ingested and approved first):

    python -m evaluation.sop_regression --token-file token.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

NO_ANSWER = "__NO_ANSWER__"

# (category, query, expectation)
CASES: list[tuple[str, str, object]] = [
    # --- process facts: a specific figure or rule -------------------
    ("process", "How far in advance should clients be contacted before their product expires?",
     [r"4\s*-\s*6 months"]),
    ("process", "How often should PT rates be reviewed?", [r"3 weeks"]),
    ("process", "When should the suitability letter be sent?", [r"5 working days"]),
    ("process", "Are there any fees for a product transfer?", [r"No Fees"]),
    ("process", "What is the property folder naming format?",
     [r"Property Type", r"Postcode"]),
    ("process", "How often is the ongoing rate monitoring review?", [r"3 weeks"]),

    # --- procedure: what must be done or checked --------------------
    ("procedure", "What should I check to identify upcoming expiries?",
     [r"diary|maturity"]),
    ("procedure", "What must be verified before submitting the mortgage?",
     [r"ERC|Interest rate|Monthly payment"]),
    ("procedure", "What actions are required for the AML check?",
     [r"AML search|Verify identity|fraud"]),
    ("procedure", "What must CRM notes include after mortgage research?",
     [r"Products researched|Payment comparisons|rationale"]),
    ("procedure", "What should be reviewed during mortgage research?",
     [r"Fixed rates|Tracker rates|Product fees|ERC"]),
    ("procedure", "What risks must the suitability letter cover?",
     [r"rate increases|fixed period|Product limitations"]),
    ("procedure", "What is included in the client objectives section of the suitability letter?",
     [r"Product transfer|Lower payments|Stability|ERC"]),
    ("procedure", "What documents go in the property folder?",
     [r"Mortgage offers|Illustrations|Fact Find|AML"]),

    # --- workflow: order and structure ------------------------------
    ("workflow", "What are the plan status updates after implementation?",
     [r"Submitted to Provider|Offer Made"]),
    ("workflow", "What happens if a better rate becomes available during monitoring?",
     [r"[Rr]e-secure|lower rate"]),
    ("workflow", "What information is needed to add a proposal?",
     [r"Proposal Type|Product Type|Product Provider"]),
    ("workflow", "What must be updated in the fact find for liabilities?",
     [r"Loans|Credit cards|commitments"]),

    # --- negative: neither the SOP nor the glossary answers these ---
    ("negative", "What is the maximum FHA loan amount?", NO_ANSWER),
    ("negative", "What commission percentage do we charge clients?", NO_ANSWER),
    ("negative", "Which lender currently offers the best rate?", NO_ANSWER),
    ("negative", "How many staff work at the firm?", NO_ANSWER),
    ("negative", "What is the capital of France?", NO_ANSWER),
    ("negative", "How often should HVAC filters be replaced?", NO_ANSWER),
]

# Cases that do not pass today. Listed rather than deleted so the suite
# reports the real score and a fix shows up as a new pass.
KNOWN_FAILURES: set[str] = set()


def ask(api: str, token: str, query: str) -> dict:
    body = json.dumps({"query": query, "history": []}).encode()
    req = urllib.request.Request(
        api, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def _block_text(block: dict) -> str:
    return "\n".join(
        [block.get("answer_phrase") or ""]
        + [e.get("text", "") for e in block.get("excerpts", [])]
    )


def grade(expect, response: dict) -> tuple[bool, str]:
    blocks = response.get("answers", [])
    answered = [b for b in blocks if b.get("routing") in ("answer", "partial")]

    if expect == NO_ANSWER:
        if not answered:
            return True, "no_answer"
        top = answered[0]
        return False, (
            f"answered {top['confidence']:.0f}% {top['routing']}: "
            f"{(top.get('answer_phrase') or '')[:55]!r}"
        )

    if not answered:
        return False, "no_answer (expected an answer)"
    text = _block_text(answered[0])
    missing = [p for p in expect if not re.search(p, text, re.I)]
    if not missing:
        return True, f"{answered[0]['confidence']:.0f}%"
    return False, f"wrong source: {(answered[0].get('answer_phrase') or '')[:55]!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8001/api/v1/search/")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    token = open(args.token_file).read().strip()
    results = []
    for category, query, expect in CASES:
        try:
            response = ask(args.api, token, query)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"ERROR {exc}"
        else:
            ok, detail = grade(expect, response)
        known = query in KNOWN_FAILURES
        status = "PASS" if ok else ("KNOWN" if known else "FAIL")
        results.append((category, query, ok, known, detail))
        print(f"{status:5} [{category:9}] {query[:58]:58} {detail[:52]}")

    print("\n" + "=" * 92)
    by_category: dict[str, list[bool]] = {}
    for category, _q, ok, _k, _d in results:
        by_category.setdefault(category, []).append(ok)
    for category, oks in by_category.items():
        print(f"{category:11} {sum(oks):2}/{len(oks):2}  {100 * sum(oks) / len(oks):5.1f}%")
    passed = sum(1 for _c, _q, ok, _k, _d in results if ok)
    print(f"{'TOTAL':11} {passed:2}/{len(results):2}  {100 * passed / len(results):5.1f}%")

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump([{"category": c, "query": q, "pass": ok,
                        "known_failure": k, "detail": d}
                       for c, q, ok, k, d in results], fh, indent=2)

    regressions = [q for _c, q, ok, known, _d in results if not ok and not known]
    if regressions:
        print(f"\nFAILING ({len(regressions)}):")
        for query in regressions:
            print(f"  - {query}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
