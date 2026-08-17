"""Retrieval regression suite — grades the live /search endpoint.

Complements ``run_benchmark.py``. That measures *ranking* quality
(hit-rate/MRR/nDCG over a seeded corpus with known-relevant chunk ids);
this measures what the user actually receives: did the answer come from
the right source, and did an unanswerable question correctly get "no
answer"? Several defects found during the retrieval audit were invisible
to rank metrics because the right chunk *was* retrieved and ranked first,
and the failure happened afterwards — in answer-phrase selection, in the
relevance gate, or before retrieval in query processing.

Every case here is a bug that was found and fixed; see
``RETRIEVAL_AUDIT.md`` for the root causes. Categories match the audit's
test matrix:

    exact       a question naming a defined term directly
    paraphrase  the same question asked in different words
    comparison  two entities that must be retrieved independently
    multi       coordinated lists that must decompose per entity
    table       a specific row of a structured table
    negative    a question the corpus cannot answer

Usage (the corpus below must be indexed first):

    python -m evaluation.retrieval_regression --token-file token.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

NO_ANSWER = "__NO_ANSWER__"

# (category, query, expectation)
#   list  -> every regex must appear in the primary answer block
#   dict  -> every regex in ["each"] must be covered by *some* answered block
#   NO_ANSWER -> no block may be answered
CASES: list[tuple[str, str, object]] = [
    # --- exact -------------------------------------------------------
    ("exact", "What is amortization?", [r"paying off a loan through regular"]),
    ("exact", "What is APR?", [r"broader measure of the cost of borrowing"]),
    ("exact", "What is principal in a loan?", [r"original sum of money borrowed"]),
    ("exact", "What is equity?", [r"difference between a property's current market value"]),
    ("exact", "What is underwriting?", [r"evaluates the risk of a loan application"]),
    ("exact", "What are discount points?", [r"upfront fees paid at closing"]),
    ("exact", "What is a prepayment penalty?", [r"fee some lenders charge if a borrower pays off"]),
    ("exact", "What does a loan servicer do?", [r"collecting monthly payments"]),
    ("exact", "What is an adjustable-rate mortgage?", [r"fixed for an initial period"]),
    ("exact", "What is a fixed-rate mortgage?", [r"remains the same for the entire loan term"]),
    ("exact", "What is TILA?", [r"disclose key loan terms and costs"]),
    # RESPA regression: spell correction rewrote the query to "repay".
    ("exact", "What is RESPA?", [r"settlement costs"]),
    ("exact", "What does RESPA regulate?", [r"settlement costs"]),
    ("exact", "What is the Truth in Lending Act?", [r"disclose key loan terms and costs"]),
    ("exact", "What is a point on a mortgage?", [r"upfront fees paid at closing"]),

    # --- paraphrase --------------------------------------------------
    ("paraphrase", "How does a loan gradually get paid off?",
     [r"paying off a loan through regular"]),
    ("paraphrase", "How can I calculate the value I have in my property?",
     [r"difference between a property's current market value"]),
    ("paraphrase", "What does a lender check before approving a mortgage?",
     [r"evaluates the risk of a loan application"]),
    ("paraphrase", "Can paying extra fees upfront lower my mortgage rate?",
     [r"upfront fees paid at closing"]),
    ("paraphrase", "Who collects my monthly mortgage payment after closing?",
     [r"collecting monthly payments"]),
    ("paraphrase", "Which loan type has a payment that never changes?",
     [r"remains the same for the entire loan term"]),
    ("paraphrase", "Am I charged for paying my mortgage off early?",
     [r"fee some lenders charge if a borrower pays off"]),
    ("paraphrase", "Which cost measure includes fees on top of the interest rate?",
     [r"broader measure of the cost of borrowing"]),
    ("paraphrase", "What law stops kickbacks between settlement service providers?",
     [r"kickbacks"]),
    ("paraphrase",
     "What portion of a mortgage represents the amount I still owe excluding interest?",
     [r"original sum of money borrowed"]),

    # --- comparison --------------------------------------------------
    ("comparison", "What's the difference between a fixed mortgage and an ARM?",
     {"each": [r"remains the same for the entire loan term", r"fixed for an initial period"]}),
    ("comparison", "Compare amortization and principal.",
     {"each": [r"paying off a loan through regular", r"original sum of money borrowed"]}),
    ("comparison", "How is equity different from principal?",
     {"each": [r"difference between a property's current market value",
               r"original sum of money borrowed"]}),
    ("comparison", "TILA vs RESPA",
     {"each": [r"disclose key loan terms and costs", r"settlement costs"]}),
    ("comparison", "What is the difference between a 5/1 ARM and a 10/1 ARM?",
     {"each": [r"5/1 ARM", r"10/1 ARM"]}),

    # --- multi-intent ------------------------------------------------
    ("multi", "What is APR and what is principal?",
     {"each": [r"broader measure of the cost of borrowing", r"original sum of money borrowed"]}),
    ("multi", "Explain equity and underwriting.",
     {"each": [r"difference between a property's current market value",
               r"evaluates the risk of a loan application"]}),
    ("multi", "What are TILA and RESPA?",
     {"each": [r"disclose key loan terms and costs", r"settlement costs"]}),
    ("multi", "Explain 5/1, 7/1, and 10/1 ARMs.",
     {"each": [r"5/1 ARM", r"7/1 ARM", r"10/1 ARM"]}),
    ("multi", "Define amortization, equity, and underwriting.",
     {"each": [r"paying off a loan through regular",
               r"difference between a property's current market value",
               r"evaluates the risk of a loan application"]}),
    ("multi", "What is a discount point and what is a prepayment penalty?",
     {"each": [r"upfront fees paid at closing",
               r"fee some lenders charge if a borrower pays off"]}),

    # --- table -------------------------------------------------------
    ("table", "How does a 5/1 ARM work?", [r"5/1 ARM", r"5 years"]),
    ("table", "How does a 7/1 ARM work?", [r"7/1 ARM", r"7 years"]),
    ("table", "How does a 10/1 ARM work?", [r"10/1 ARM", r"10 years"]),
    ("table", "Which ARM has a 10-year initial fixed period?", [r"10/1 ARM", r"10 years"]),
    ("table", "After the fixed period, how often does a 7/1 ARM adjust?",
     [r"7/1 ARM", r"Annually"]),
    ("table", "What is the fixed period on a 7/1 ARM?", [r"7/1 ARM", r"7 years"]),

    # --- negative ----------------------------------------------------
    ("negative", "What is the maximum FHA loan amount?", NO_ANSWER),
    ("negative", "What is the current VA funding fee?", NO_ANSWER),
    ("negative", "What is the FHA upfront MIP percentage?", NO_ANSWER),
    # Was a negative case when the glossary was the only document in the
    # corpus. Moved to paraphrase once the SOP joined it (2026-08-17):
    # "Step 2.3 — Upload Documents" genuinely lists the required
    # documents ("Existing mortgage statements", "Mortgage offers",
    # "Fact Find", "ID documents", ...), so a no_answer here would now be
    # the system missing real content, not correctly declining. Ground
    # truth was stale, not the retrieval.
    ("paraphrase", "What documents are required for a mortgage application?",
     [r"[Mm]ove all relevant documents into the folder"]),
    ("negative", "What is today's mortgage interest rate?", NO_ANSWER),
    ("negative", "How often should HVAC filters be replaced?", NO_ANSWER),
    ("negative", "What credit score do I need for a conventional loan?", NO_ANSWER),
    ("negative", "What is the minimum down payment for an investment property?", NO_ANSWER),
    ("negative", "Who is the CEO of the bank?", NO_ANSWER),
    ("negative", "What is the capital of France?", NO_ANSWER),
]

# Cases that do not pass today. Listed explicitly rather than deleted so
# the suite reports the real score and a fix shows up as a new pass.
# See RETRIEVAL_AUDIT.md "Remaining issues".
KNOWN_FAILURES = {
    # Answered at 97% from the Adjustable-Rate Mortgage definition. The
    # corpus explains what an interest rate *is* but holds no rate sheet,
    # and nothing in the question's wording distinguishes "define this"
    # from "give me today's figure" by the signals available here: the
    # cross-encoder scores it -0.79, inside the range of genuinely
    # answerable questions, so the answerability veto cannot reject it
    # without also rejecting real answers.
    "What is today's mortgage interest rate?",
}


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
        phrase = (top.get("answer_phrase") or "")[:60]
        return False, f"answered {top['confidence']:.0f}% {top['routing']}: {phrase!r}"

    if isinstance(expect, dict):
        missing = [p for p in expect["each"]
                   if not any(re.search(p, _block_text(b), re.I) for b in answered)]
        if not missing:
            return True, f"{len(answered)}/{len(blocks)} blocks cover all"
        return False, f"missing {missing}"

    if not answered:
        return False, "no_answer (expected an answer)"
    text = _block_text(answered[0])
    if all(re.search(p, text, re.I) for p in expect):
        return True, f"{answered[0]['confidence']:.0f}%"
    return False, f"wrong source: {(answered[0].get('answer_phrase') or '')[:60]!r}"


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
        print(f"{status:5} [{category:10}] {query[:58]:58} {detail[:60]}")

    print("\n" + "=" * 96)
    by_category: dict[str, list[bool]] = {}
    for category, _q, ok, _known, _d in results:
        by_category.setdefault(category, []).append(ok)
    for category, oks in by_category.items():
        print(f"{category:12} {sum(oks):2}/{len(oks):2}  {100 * sum(oks) / len(oks):5.1f}%")
    passed = sum(1 for _c, _q, ok, _k, _d in results if ok)
    print(f"{'TOTAL':12} {passed:2}/{len(results):2}  {100 * passed / len(results):5.1f}%")

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump([{"category": c, "query": q, "pass": ok,
                        "known_failure": k, "detail": d}
                       for c, q, ok, k, d in results], fh, indent=2)

    # Fail the run only on *unexpected* regressions.
    regressions = [q for _c, q, ok, known, _d in results if not ok and not known]
    if regressions:
        print(f"\nREGRESSIONS ({len(regressions)}):")
        for query in regressions:
            print(f"  - {query}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
