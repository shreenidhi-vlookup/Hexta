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
from evaluation.metrics.latency_benchmark import measure_latency, percentile_latencies


def _try_retrieval_phase(dataset: list[dict]) -> tuple[dict, bool]:
    """Attempt to run retrieval against the DB.

    Returns (retrieval_results, success). If the DB is unavailable or
    seeding fails, returns an empty dict and False so the benchmark
    can still report query-processing results.

    Also records end-to-end search latencies for the latency benchmark.
    """
    try:
        from app.db.postgres.session import acquire
        from app.api.v1.search import _rank_sub_query
        from app.config import settings
        from app.ranking.reranker import rerank
        from evaluation.datasets.seed_benchmark_data import seed_benchmark_data, clear_benchmark_data
    except (ImportError, Exception):
        return {}, False

    try:
        clear_benchmark_data()
        topic_mapping = seed_benchmark_data()
    except Exception as exc:
        print(f"  Retrieval setup failed (skipping retrieval metrics): {exc}")
        return {}, False

    # Build expected_chunk_ids for each dataset item from topic_keys
    user = {"id": "benchmark", "role": "super_admin", "departments": ["general"], "allowed_departments": ["general"]}

    retrieved_ranked: list[list[int]] = []
    relevant_sets: list[set[int]] = []
    per_query_retrieval: list[dict] = []
    e2e_latencies: list[float] = []

    for item in dataset:
        topic_keys = item.get("topic_keys", [])
        expected_ids = set()
        for key in topic_keys:
            expected_ids.update(topic_mapping.get(key, set()))

        retrieved_ids: list[int] = []
        if item.get("question") and expected_ids:
            try:
                start = time.perf_counter()
                with acquire() as conn:
                    # Mirror the production ranking path, not just the raw
                    # candidate fetch. This used to call
                    # search_knowledge_base() directly, which skips both RRF
                    # fusion and the reranker -- so every rank-sensitive
                    # metric here (hit_rate@1, MRR, nDCG) described an
                    # ordering no user ever sees, and no ranking change
                    # could be measured by the benchmark meant to gate it
                    # (CLAUDE.md rule 7).
                    ranked = _rank_sub_query(conn, item["question"], user)
                    if settings.rerank_enabled and ranked:
                        candidates = [
                            {"chunk_id": c.chunk_id, "content": c.content}
                            for c in ranked[: settings.bm25_limit]
                        ]
                        reranked = rerank(
                            query=item["question"],
                            candidates=candidates,
                            top_k=min(settings.rerank_top_k, len(candidates)),
                        )
                        order = {c["chunk_id"]: i for i, c in enumerate(reranked)}
                        ranked.sort(
                            key=lambda c: order.get(c.chunk_id, len(order))
                        )
                    e2e_latencies.append((time.perf_counter() - start) * 1000)
                retrieved_ids = [c.chunk_id for c in ranked]
            except Exception:
                retrieved_ids = []

        retrieved_ranked.append(retrieved_ids)
        relevant_sets.append(expected_ids)

        per_query_retrieval.append({
            "id": item["id"],
            "question": item["question"],
            "retrieved_count": len(retrieved_ids),
            "relevant_count": len(expected_ids),
            "hits": list(set(retrieved_ids) & expected_ids),
        })

    return {
        "retrieved_ranked": retrieved_ranked,
        "relevant_sets": relevant_sets,
        "per_query": per_query_retrieval,
        "topic_mapping": {k: sorted(v) for k, v in topic_mapping.items()},
        "_e2e_latencies": e2e_latencies,
    }, True


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

    # Phase 3: Retrieval quality metrics (optional — requires DB)
    print("  Running retrieval quality tests...")
    retrieval_data, retrieval_ok = _try_retrieval_phase(dataset)

    if retrieval_ok and retrieval_data["retrieved_ranked"]:
        rank_lists = retrieval_data["retrieved_ranked"]
        relevant_sets = retrieval_data["relevant_sets"]

        k_values = [1, 3, 5, 10]
        retrieval_metrics: dict = {}

        for k in k_values:
            retrieval_metrics[f"hit_rate@{k}"] = round(
                hit_rate(rank_lists, relevant_sets, k), 4
            )
            retrieval_metrics[f"mrr@{k}"] = round(
                mean_reciprocal_rank(
                    [rl[:k] for rl in rank_lists], relevant_sets
                ), 4
            )
            retrieval_metrics[f"precision@{k}"] = round(
                sum(precision_at_k(rl, rs, k) for rl, rs in zip(rank_lists, relevant_sets))
                / len(rank_lists), 4
            )
            retrieval_metrics[f"recall@{k}"] = round(
                sum(recall_at_k(rl, rs, k) for rl, rs in zip(rank_lists, relevant_sets))
                / len(rank_lists), 4
            )

        # nDCG@10
        ndcg_scores = []
        for rl, rs in zip(rank_lists, relevant_sets):
            if rs:
                # Create binary relevance scores (1 for relevant, 0 otherwise)
                relevance_scores = {doc_id: 1.0 for doc_id in rs}
                ndcg_scores.append(ndcg_at_k(rl, relevance_scores, 10))
        retrieval_metrics["ndcg@10"] = round(
            sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0, 4
        )

        # MRR (full ranked list, no cutoff)
        retrieval_metrics["mrr"] = round(
            mean_reciprocal_rank(rank_lists, relevant_sets), 4
        )

        results["retrieval_metrics"] = retrieval_metrics
        results["retrieval_per_query"] = retrieval_data["per_query"]
        results["retrieval_topic_mapping"] = retrieval_data["topic_mapping"]

        print(f"  Retrieval metrics: {len(rank_lists)} queries with DB")
        for k in k_values:
            print(f"    hit_rate@{k}: {retrieval_metrics[f'hit_rate@{k}']:.1%}")
            print(f"    mrr@{k}:       {retrieval_metrics[f'mrr@{k}']:.1%}")
        print(f"    ndcg@10:       {retrieval_metrics['ndcg@10']:.1%}")
    else:
        results["retrieval_metrics"] = {"status": "skipped — no DB or seeding failed"}
        print("  Retrieval tests skipped (no DB connection available)")

    # Phase 4: Latency benchmarking (optional — requires DB + retrieval)
    if retrieval_ok and retrieval_data:
        print("  Running latency benchmarks...")
        try:
            from app.config import settings

            latency_metrics: dict = {}

            # End-to-end search latency (measured during retrieval phase)
            latencies = retrieval_data.get("_e2e_latencies", [])

            if latencies:
                percentiles = percentile_latencies(latencies, [50, 95, 99])
                latency_metrics["end_to_end_search"] = {
                    "count": len(latencies),
                    "p50_ms": round(percentiles[50], 2),
                    "p95_ms": round(percentiles[95], 2),
                    "p99_ms": round(percentiles[99], 2),
                }
                print(f"    Search p50: {percentiles[50]:.1f}ms  p95: {percentiles[95]:.1f}ms")

            # Reranker latency (if enabled and module available)
            if settings.rerank_enabled:
                try:
                    from app.ranking.reranker import rerank

                    rerank_latencies = []
                    mock_candidates = [{"chunk_id": i + 1, "content": f"test content {i}"} for i in range(10)]
                    for item in dataset:
                        if not item.get("question"):
                            continue
                        lat = measure_latency(
                            rerank,
                            query=item["question"],
                            candidates=mock_candidates,
                            top_k=10,
                        )
                        rerank_latencies.append(lat)

                    if rerank_latencies:
                        r_p = percentile_latencies(rerank_latencies, [50, 95, 99])
                        budget_ok = r_p[95] < 200.0
                        latency_metrics["reranker"] = {
                            "count": len(rerank_latencies),
                            "p50_ms": round(r_p[50], 2),
                            "p95_ms": round(r_p[95], 2),
                            "p99_ms": round(r_p[99], 2),
                            "budget_ok": budget_ok,
                        }
                        print(f"    Reranker p95: {r_p[95]:.1f}ms  (budget <200ms: {'PASS' if budget_ok else 'FAIL'})")
                except ImportError:
                    latency_metrics["reranker"] = {"status": "skipped — not installed"}

            # Cold-start latency (embedding model loading)
            try:
                import importlib
                import app.search.pgvector_search as pvs_mod
                importlib.reload(pvs_mod)
                cold_lat = measure_latency(
                    pvs_mod.embed_query,
                    "what is the minimum credit score",
                )
                latency_metrics["cold_start"] = {
                    "first_query_ms": round(cold_lat, 2),
                    "budget_ok": cold_lat < 10000.0,
                }
                print(f"    Cold start: {cold_lat:.1f}ms  (budget <10s: {'PASS' if cold_lat < 10000 else 'FAIL'})")
            except Exception:
                pass

            if latency_metrics:
                results["latency_metrics"] = latency_metrics

        except Exception as exc:
            print(f"  Latency benchmarking failed (skipping): {exc}")

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
    if "retrieval_metrics" in results and "status" not in results["retrieval_metrics"]:
        print(f"\n  --- Retrieval Quality ---")
        for key, val in results["retrieval_metrics"].items():
            print(f"  {key:20s} {val:.1%}")
    else:
        print(f"\n  Retrieval Quality: skipped (no DB)")
    if "latency_metrics" in results:
        print(f"\n  --- Latency ---")
        for metric_name, vals in results["latency_metrics"].items():
            if isinstance(vals, dict) and "status" not in vals:
                p50 = vals.get("p50_ms", vals.get("first_query_ms", "?"))
                p95 = vals.get("p95_ms", "?")
                print(f"  {metric_name:20s} p50={p50}ms  p95={p95}ms")
            elif isinstance(vals, dict):
                print(f"  {metric_name:20s} {vals.get('status', 'unknown')}")
    print(f"\n  Report: {results['report_path']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
