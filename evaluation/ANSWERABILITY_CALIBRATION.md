# Answerability threshold calibration

Derivation of `app/response/answerability.py::MIN_RERANK_SCORE`.
Re-run this measurement before changing that value (CLAUDE.md rule 7).

## Method

For each query, the full ranking pipeline was run (hybrid search → RRF →
fragment penalty → cross-encoder rerank at `rerank_top_k=5`) and the top
cross-encoder score recorded. Corpus: the General Banking and Mortgage
Glossary (13 chunks). Model: `Xenova/ms-marco-MiniLM-L-6-v2`.

"Answerable" = the corpus contains the answer. "Unanswerable" = it does
not. 28 answerable and 15 unanswerable queries; 3 unanswerable ones
retrieved no candidate at all and are excluded from the table below.

## Distributions

| set | min | median | max |
|---|---|---|---|
| answerable (n=28) | -5.91 | 7.94 | 10.79 |
| unanswerable (n=12) | -11.13 | -8.03 | 3.13 |

The distributions overlap between roughly -6 and +3, so no threshold
separates them cleanly. Three unanswerable queries score inside the
answerable range (-1.81, -0.79, 3.13); they ask for figures the corpus
plausibly *would* contain, and the ranked chunk is genuinely on-topic.

## Threshold sweep

| threshold | keeps answerable | rejects unanswerable |
|---|---|---|
| -9.0 | 100.0% | 41.7% |
| -8.0 | 100.0% | 58.3% |
| -7.0 | 100.0% | 66.7% |
| **-6.5** | **100.0%** | **75.0%** |
| -6.0 | 100.0% | 75.0% |
| -5.0 | 96.4% | 75.0% |
| -4.0 | 92.9% | 75.0% |
| -2.0 | 85.7% | 75.0% |
| 0.0 | 78.6% | 91.7% |

## Chosen value: -6.5

The last point before recall starts costing anything. It sits just under
the worst observed answerable query (-5.91), so the gate only fires where
the cross-encoder is affirmatively negative rather than merely uncertain.
Everything above it is left to the existing confidence and relevance
routing.

Raising it to 0.0 would reject 91.7% of unanswerable queries but discard
21.4% of real answers. For a system whose value is that its answers are
trustworthy *and* that it finds what it holds, silently losing one answer
in five is the worse failure — and the queries it would drop are the
paraphrases, exactly the class this audit was fixing.

This is why the gate is a veto rather than a classifier: it is not asked
to decide answerability on its own, only to overrule the rest of the
pipeline when it is confident the evidence is wrong.

## Residual

One unanswerable query survives every gate: *"What is today's mortgage
interest rate?"* (score -0.79) is answered from the Adjustable-Rate
Mortgage definition. Tracked as a known failure in
`evaluation/retrieval_regression.py`.
