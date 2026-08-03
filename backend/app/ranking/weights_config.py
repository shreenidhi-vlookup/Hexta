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


DEFAULT_WEIGHTS = RankingWeights()
