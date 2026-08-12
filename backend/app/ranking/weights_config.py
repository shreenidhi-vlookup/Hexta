"""Ranking weights configuration.

Ranking weights are configuration, not constants (CLAUDE.md rule 7).
Defaults come from Final_Tech_Stack.md and are documented here. Any
change must be backed by an evaluation/run_benchmark.py run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankingWeights:
    bm25_weight: float = 0.3
    vector_weight: float = 0.7
    top_k: int = 25
    # Minimum cosine similarity for a chunk to be admitted into the
    # candidate set on semantic grounds alone (zero BM25 keyword overlap).
    # search/hybrid_orchestrator.py used to require BM25 lexeme overlap as
    # a hard WHERE-clause gate, which made a well-formed, correctly-spelled
    # paraphrase that shares no vocabulary with the relevant chunk return
    # zero candidates — vector similarity never got a chance to rescue it.
    # Dropping that gate entirely let true gibberish through too (some
    # chunk is always "nearest" in embedding space). This floor is the
    # replacement gate: calibrated against bge-small-en-v1.5 embeddings,
    # where genuine in-KB paraphrases scored >=0.71 at rank 1 and
    # off-topic/gibberish queries topped out around 0.61 (see
    # hybrid_orchestrator.py for the calibration queries). Any change must
    # be backed by an evaluation/run_benchmark.py run (CLAUDE.md rule 7).
    min_vector_similarity: float = 0.65


DEFAULT_WEIGHTS = RankingWeights()
