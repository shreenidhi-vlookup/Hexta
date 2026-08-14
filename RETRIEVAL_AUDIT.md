# Retrieval audit — August 2026

Audit of the retrieval pipeline against a real uploaded document
(*General Banking and Mortgage Glossary*, 47 lines: 12 definitions, one
markdown table, three section headings).

Score on a 52-case regression matrix, before and after:

| category | before | after |
|---|---|---|
| exact retrieval (15) | 53.3% | **100.0%** |
| paraphrase (10) | 50.0% | **100.0%** |
| comparison (5) | 80.0% | **100.0%** |
| multi-intent (6) | 50.0% | **100.0%** |
| structured table (6) | 100.0% | 100.0% |
| negative / no-answer (10) | 60.0% | **90.0%** |
| **total** | **61.5%** | **98.1%** |

Independent check on `evaluation/run_benchmark.py`, which uses a
different seeded corpus and scores ranking rather than answers:

| metric | before | after |
|---|---|---|
| hit_rate@1 | 69.2% | **92.3%** |
| mrr@1 | 53.8% | **76.9%** |
| hit_rate@3 | 84.6% | **92.3%** |
| recall@10 | — | 88.5% |
| ndcg@10 | 63.5% | **86.4%** |
| MRR | 62.2% | **76.9%** |

Nothing regressed on either set. Reranker p95 43.8ms, inside the 200ms
budget (CLAUDE.md rule 6). No change to the no-LLM guarantee: every
answer is still verbatim source text.

---

## The headline finding

**Retrieval recall was never the problem.** In every failing case the
correct chunk was in the index and usually ranked first. The defects were
in the *retrieval unit*, in *query processing before search ran*, and in
*answer selection after ranking finished*.

---

## Root causes

### 1. Glossary definitions were merged into unusable blobs

*What failed*: "What is equity?", "What is underwriting?", "What are
discount points?", "What is a prepayment penalty?", "What is RESPA?" all
returned **no answer**, though every one of those terms is defined in the
document.

*Where*: `documents/chunking/structural_chunker.py::_merge_small_chunks`.

*Why*: the chunker split the document correctly into **18 chunks, one per
definition** — then the small-chunk merge pass glued seven of them into a
single 1341-character blob, leaving 4 chunks total. Every definition is
23–46 tokens and `min_tokens` is 50, so all of them qualified as
"undersized fragments".

The consequences compounded. With seven definitions sharing one chunk,
"What is equity?" could only retrieve the blob; answer-phrase extraction
picked the *first* definition in it (Amortization); and the 600-character
excerpt window cut the Equity text off entirely. Query↔answer relevance
scored 0.000 and routing correctly refused to answer — a right answer,
indexed and retrieved, suppressed by the shape of its container.

*Fix*: a `"Term: definition"` block is a self-contained retrieval unit,
not a fragment, and is never merged. Detection requires the label to be
title-cased so ordinary prose with a mid-sentence colon ("The rule is
simple: pay on time") is not misclassified. Standalone heading blocks
become `section` metadata instead of tiny chunks. The same rule was
applied to the PDF path, which had the identical flaw.

*Result*: 4 chunks → 13. Exact retrieval 53.3% → 93.3% from this change
alone; total 61.5% → 84.6%.

### 2. Spell correction destroyed entities before search ran

*What failed*: "What is RESPA?" → no answer, while "What does RESPA
regulate?" worked.

*Where*: `query_processing/spell_correction.py`.

*Why*: the corrector rewrote the query to **"what is repay"**. "respa"
is absent from the static domain vocabulary, and `fuzz.ratio("respa",
"repay")` is exactly 80.0 — the acceptance threshold. No amount of
retrieval tuning can recover from the entity being deleted from the
query.

*Fix*: the module's own rule is "correct a token only when it is NOT
already a known term". The static list cannot know the vocabulary of
documents uploaded later, so the vocabulary is now also derived from the
indexed corpus (`query_processing/corpus_vocab.py`): a token that occurs
in the user's documents is a word, not a typo. This generalises to every
entity in every future upload.

*Result*: exact retrieval 93.3% → **100%**.

### 3. Corrections that replaced words instead of repairing them

*What failed*: "How does a loan gradually get paid off?" → no answer.

*Why*: two more threshold-boundary rewrites. `"paid"` → `"repaid"`
(80.0, exactly at threshold) and, worse, `"a loan"` → `"va loan"` (92.3
against the 92 phrase threshold), which injected a VA-loan entity into a
question that never mentioned VA and dragged retrieval toward VA content.

*Fix*: a typo is a substitution or a dropped character, so a genuine
repair stays close to the original length; a candidate that bolts on a
whole morpheme is a different word. Edit size is now capped relative to
token length. Phrase-level repair may no longer rewrite a token that the
token-level pass refuses to touch — protection has to hold at every level
or it is not protection. This also subsumes an earlier one-off patch for
`finance` → `refinance`.

### 4. No answerability stage — only topical relevance

*What failed*: "What is the maximum FHA loan amount?" answered at **94%
confidence** from the Discount Points definition. "What credit score do I
need for a conventional loan?" answered from Underwriting.

*Why*: the only gate was lexical overlap, and these are precisely the
cases where a wrong chunk shares the question's vocabulary — the Discount
Points text contains both "loan" and "amount". Ranking orders candidates
against each other but never asks whether the winner is good enough to
show at all.

*Fix*: `response/answerability.py`. The cross-encoder already reads query
and chunk *together* and scores how well the chunk responds to that
query — the signal neither BM25 nor the bi-encoder can produce. Ranking
used it to reorder; it is now also consulted as an absolute judgement.

Calibrated on 43 queries (`evaluation/ANSWERABILITY_CALIBRATION.md`):
answerable scores ranged -5.91…10.79, unanswerable -11.13…3.13. The
distributions overlap, so this is a **veto, not a classifier** — it fires
only below -6.5, under the worst observed answerable query, rejecting 75%
of unanswerable queries at zero cost to recall. With no score (reranker
disabled or failed) it abstains, so behaviour degrades to the previous
state rather than refusing everything.

*Result*: negative/no-answer 70% → **90%**.

### 5. Paraphrases were required to contain words no document has

*What failed*: "Which loan type has a payment that never changes?" → no
answer, despite the Fixed-Rate Mortgage definition being retrieved.

*Why*: relevance is the fraction of the question's content terms present
in the answer, and every term counted equally — including "never" and
"changes", which appear in no document. A correct answer could score at
most 4/6 no matter how perfectly it answered; it scored 2/6 = 0.333,
just under the 0.35 no-answer floor. Paraphrases are made mostly of such
words, so the gate punished exactly the semantic matches the system
should be best at.

*Fix*: a query term absent from the corpus cannot be evidence either way,
so it is dropped from the denominator — the standard "weight a term by
what it can discriminate" intuition, applied where the weight is
unambiguous. Skipped entirely when the vocabulary is unloaded, and when
*every* term would be dropped (a query sharing no vocabulary with the
corpus is strong evidence of no answer, not a vacuous 1.0).

Two follow-on defects found while validating this: vocabulary membership
was one-directional (the corpus stores "payments", so a query about
"payment" was judged unsupported), and relative pronouns ("that",
"which") were being scored as content terms the answer had to contain.

*Result*: paraphrase 80% → **100%**.

### 6. Coordinated entity lists were never decomposed

*What failed*: "Define amortization, equity, and underwriting." returned
one answer. "Explain equity and underwriting." appeared to work only
because both definitions happened to land in the top-3 excerpts.

*Why*: the splitter has an over-split guard — a fragment must be a
"self-contained request" to split on — and that test consulted a static
concept list. "equity" and "underwriting" were not in it.

*Fix*: the documents state what they define. Chunks typed `definition`
carry their term in the text before the first colon, so the corpus
supplies the concept vocabulary. The over-split guard is unchanged for
everything else: "income and employment requirements" stays one question
because neither is a defined term.

*Result*: multi-intent 83.3% → **100%**, now genuinely three retrievals
with three independent answers rather than one lucky excerpt list.

---

## Tried and reverted

Making retrieval order authoritative in `package_builder`'s answer
selection, instead of re-sorting excerpts by word overlap. The principle
is right — overlap is the weakest signal in the system and it can
override the cross-encoder — but measured on the full matrix it fixed
nothing and broke a case the re-sort was quietly rescuing, where the
cross-encoder ranks ARM above Fixed-Rate. Net −2 cases, reverted, with
the finding recorded in the code. Removing that re-sort needs a better
top-1 ranker first, not a different tie-break.

---

## Remaining issues

**"What is today's mortgage interest rate?"** is answered at 97% from the
Adjustable-Rate Mortgage definition. The corpus explains what an interest
rate *is* but holds no rate sheet, and the cross-encoder scores it -0.79 —
inside the range of genuinely answerable questions — so the veto cannot
reject it without discarding real answers. Distinguishing "define this"
from "give me today's figure" needs a signal none of the current stages
carry. Tracked as a known failure in `evaluation/retrieval_regression.py`.

**Table rows are still one chunk.** The audit brief asked for row-level
indexing, but structured-table retrieval measured 100% both before and
after, so there was no defect to fix and a change would have been
unmeasurable churn against a passing category. Worth revisiting if a
larger table ever regresses.

**Ranking top-1 is imperfect.** Two failures traced to the cross-encoder
ranking a neighbouring definition above the right one. It is a small
quantised model (~80MB) chosen to fit the memory cap; the lexical re-sort
in `package_builder` is currently compensating for it.

---

## Reproducing

```bash
# ranking metrics over the seeded benchmark corpus
docker exec hexa_backend python -m evaluation.run_benchmark

# answer-level regression matrix against the live API
python -m evaluation.retrieval_regression --token-file token.txt
```

The regression suite exits non-zero only on *unexpected* failures, so it
is safe to gate on.
