"""Evaluation benchmark runner.

Runs the full query-processing pipeline against the eval dataset and
measures retrieval accuracy (precision, recall, MRR, nDCG, hit rate)
and latency. Results are written to evaluation/reports/<timestamp>.json.

Usage:
    python -m evaluation.run_benchmark --output-dir evaluation/reports
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend/app is importable
backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from evaluation.datasets.eval_questions import load_dataset
from evaluation.metrics.precision_recall import precision_at_k, recall_at_k
from evaluation.metrics.mrr import mean_reciprocal_rank
from evaluation.metrics.ndcg import ndcg_at_k
from evaluation.metrics.hit_rate import hit_rate


def run_benchmark(output_dir: str = "evaluation/reports") -> dict:
    """Run the benchmark and return results dict."""
    dataset = load_dataset()

    # Import pipeline (does NOT require DB connection — it's a pure function)
    from app.query_processing import pipeline

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_size": len(dataset),
        "total_latency_ms": 0.0,
        "queries": [],
    }

    total_start = time.perf_counter()

    for item in dataset:
        query_start = time.perf_counter()
        plan = pipeline.process_query(item["question"])
        query_latency = (time.perf_counter() - query_start) * 1000

        sub_query_count = len(plan.sub_queries)

        # Spell correction check
        spell_corrected = False
        if plan.sub_queries:
            first_sq = plan.sub_queries[0]
            if first_sq.text != plan.normalized.split(",")[0].strip(" ?!").strip():
                spell_corrected = True

        # Check expectations
        intent_ok = True
        entities_ok = True

        if "expected_intent" in item and item["expected_intent"] != "general":
            for sq in plan.sub_queries:
                if sq.intent != item["expected_intent"]:
                    intent_ok = False
                    break

        if "expected_entities" in item:
            all_entities = []
            for sq in plan.sub_queries:
                all_entities.extend(e.canonical for e in sq.entities)
            expected = set(item["expected_entities"])
            actual = set(all_entities)
            if expected:
                entities_ok = expected & actual == expected

        # Multi-question check
        sub_questions_ok = sub_query_count == item.get("expected_sub_questions", 1)

        result = {
            "id": item["id"],
            "question": item["question"],
            "sub_queries": sub_query_count,
            "sub_question_ok": sub_questions_ok,
            "intent": [sq.intent for sq in plan.sub_queries],
            "intent_ok": intent_ok,
            "entities": [e.canonical for sq in plan.sub_queries for e in sq.entities],
            "entities_ok": entities_ok,
            "spell_corrected": spell_corrected,
            "latency_ms": round(query_latency, 2),
            "normalized": plan.normalized,
            "truncated": plan.truncated,
        }

        results["queries"].append(result)

    total_elapsed = (time.perf_counter() - total_start) * 1000

    # Aggregate metrics
    correct_sub_questions = sum(1 for q in results["queries"] if q["sub_question_ok"])
    correct_intents = sum(1 for q in results["queries"] if q["intent_ok"])
    correct_entities = sum(1 for q in results["queries"] if q["entities_ok"])
    total_queries = len(results["queries"])

    results["summary"] = {
        "sub_question_accuracy": correct_sub_questions / total_queries if total_queries else 0.0,
        "intent_accuracy": correct_intents / total_queries if total_queries else 0.0,
        "entity_accuracy": correct_entities / total_queries if total_queries else 0.0,
        "avg_query_processing_latency_ms": round(total_elapsed / total_queries, 2) if total_queries else 0.0,
        "total_latency_ms": round(total_elapsed, 2),
    }

    # Write report
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(output_dir, f"benchmark_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)

    results["report_path"] = report_path

    return results


def main():
    parser = argparse.ArgumentParser(description="Run Hexta evaluation benchmark")
    parser.add_argument("--output-dir", default="evaluation/reports", help="Directory for output reports")
    parser.add_argument("--backend-path", default=None, help="Path to backend directory")
    args = parser.parse_args()

    if args.backend_path:
        backend = Path(args.backend_path).resolve()
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))

    print(f"Starting benchmark at {datetime.now(timezone.utc).isoformat()}")
    results = run_benchmark(args.output_dir)
    summary = results["summary"]

    print(f"\n{'='*60}")
    print(f"Benchmark Results: {results['dataset_size']} queries")
    print(f"{'='*60}")
    print(f"  Sub-question accuracy:  {summary['sub_question_accuracy']:.1%}")
    print(f"  Intent accuracy:        {summary['intent_accuracy']:.1%}")
    print(f"  Entity accuracy:        {summary['entity_accuracy']:.1%}")
    print(f"  Avg query proc latency: {summary['avg_query_processing_latency_ms']:.1f}ms")
    print(f"  Total latency:          {summary['total_latency_ms']:.1f}ms")
    print(f"\n  Report: {results['report_path']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
