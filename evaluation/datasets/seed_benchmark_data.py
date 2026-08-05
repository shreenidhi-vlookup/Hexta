"""Seed documents and chunks for benchmark retrieval testing.

Creates predictable content matching the eval dataset topics, then
returns a mapping of topic-key -> set of chunk_ids so the benchmark
can compute recall, MRR, nDCG, hit rate, precision.

The content is designed to match the questions in eval_questions.py.
Run this before running the retrieval phase of run_benchmark.py.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from app.db.postgres.session import acquire


BENCHMARK_DOCS = [
    {
        "title": "Mortgage Eligibility Guidelines",
        "doc_type": "policy",
        "department": "general",
        "chunks": [
            ("Credit score requirements", "paragraph",
             "The minimum credit score for a conventional loan is 620. For FHA loans, a score of 580 or higher is required with a 3.5% down payment. VA loans typically require a minimum credit score of 580."),
            ("LTV limits", "paragraph",
             "The maximum loan-to-value ratio for a conventional loan is 80% without private mortgage insurance. With PMI, borrowers can qualify with up to 97% LTV. Investment properties typically require a lower LTV of 75% or less."),
            ("Down payment", "paragraph",
             "Conventional loans typically require a minimum down payment of 3%. FHA loans require as little as 3.5%. VA loans require no down payment for eligible veterans."),
            ("Employment", "paragraph",
             "Borrowers must demonstrate stable employment history for at least two years. Income and employment verification includes recent pay stubs, W-2 forms, and tax returns."),
        ],
    },
    {
        "title": "Required Documentation for Loan Applications",
        "doc_type": "checklist",
        "department": "general",
        "chunks": [
            ("Documentation requirements", "checklist",
             "Required documents include: proof of income (pay stubs, W-2s, tax returns), bank statements for the past two months, employment verification letter, government-issued photo ID, and proof of residence."),
        ],
    },
    {
        "title": "FHA and VA Loan Comparison Guide",
        "doc_type": "reference",
        "department": "general",
        "chunks": [
            ("FHA loans", "paragraph",
             "Federal Housing Administration (FHA) loans are government-backed mortgages with lower credit score requirements and smaller down payments. Key benefits include lower credit score thresholds and higher debt-to-income ratios allowed."),
            ("VA loans", "paragraph",
             "Veterans Affairs (VA) loans are available to eligible veterans, active-duty service members, and qualifying spouses. These loans require no down payment and no private mortgage insurance, with competitive interest rates."),
            ("FHA vs VA differences", "table",
             "FHA loans require a 3.5% down payment and have annual mortgage insurance premiums. VA loans require no down payment and no PMI, but include a funding fee. FHA is for primary residences only; VA also allows secondary residences."),
        ],
    },
    {
        "title": "Closing Process and Fee Schedule",
        "doc_type": "process",
        "department": "general",
        "chunks": [
            ("Closing process", "paragraph",
             "The closing process involves a final walk-through, signing of loan documents, and payment of closing costs. The closing disclosure must be provided at least three business days before closing."),
            ("Closing costs", "paragraph",
             "Typical closing costs include loan origination fees, appraisal fees, title insurance, credit report fees, and prepaid items like property taxes and homeowner's insurance. Total closing costs typically range from 2% to 5% of the loan amount."),
            ("Fees", "checklist",
             "Common fees paid at closing: loan origination fee, discount points, appraisal fee, credit report fee, title search and insurance, attorney fees, recording fees, and prepaid interest."),
        ],
    },
]


def seed_benchmark_data() -> dict[str, set[int]]:
    """Seed documents and chunks, returning a mapping of topic -> chunk_ids.

    The keys correspond to topics referenced in the eval dataset:
    - "credit_score"
    - "documents"
    - "ltv"
    - "down_payment"
    - "employment"
    - "fha"
    - "va"
    - "fha_va"
    - "closing"
    - "fees"
    """
    topic_to_chunks: dict[str, set[int]] = defaultdict(set)

    with acquire() as conn:
        with conn.cursor() as cur:
            for doc in BENCHMARK_DOCS:
                cur.execute(
                    "INSERT INTO documents (title, doc_type, department, is_active, is_approved, version) "
                    "VALUES (%s, %s, %s, true, true, 1) RETURNING id",
                    (doc["title"], doc["doc_type"], doc["department"]),
                )
                doc_id = cur.fetchone()["id"]

            for doc in BENCHMARK_DOCS:
                cur.execute(
                    "SELECT id FROM documents WHERE title = %s",
                    (doc["title"],),
                )
                doc_id = cur.fetchone()["id"]

                for section, chunk_type, content in doc["chunks"]:
                    content_hash = hashlib.md5(content.encode()).hexdigest()
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(document_id, content, content_hash, section, chunk_type, department, is_active, is_approved) "
                        "VALUES (%s, %s, %s, %s, %s, %s, true, true) RETURNING id",
                        (doc_id, content, content_hash, section, chunk_type, doc["department"]),
                    )
                    chunk_id = cur.fetchone()["id"]

                    # Categorize chunk by topic for the mapping
                    lower = content.lower()
                    if "credit score" in lower:
                        topic_to_chunks["credit_score"].add(chunk_id)
                    if "documents" in lower or "documentation" in lower:
                        topic_to_chunks["documents"].add(chunk_id)
                    if "loan-to-value" in lower or "ltv" in lower:
                        topic_to_chunks["ltv"].add(chunk_id)
                    if "down payment" in lower:
                        topic_to_chunks["down_payment"].add(chunk_id)
                    if "employment" in lower:
                        topic_to_chunks["employment"].add(chunk_id)
                    if "federal housing administration" in lower or "fha" in lower:
                        topic_to_chunks["fha"].add(chunk_id)
                    if "veterans affairs" in lower or "va loan" in lower:
                        topic_to_chunks["va"].add(chunk_id)
                    if "fha" in lower and "va" in lower:
                        topic_to_chunks["fha_va"].add(chunk_id)
                    if "closing" in lower:
                        topic_to_chunks["closing"].add(chunk_id)
                    if "fees" in lower or "fee" in lower:
                        topic_to_chunks["fees"].add(chunk_id)

            # Generate embedding vectors for all chunks (required for vector search)
            try:
                from app.search.pgvector_search import embed_query
                import numpy as np

                cur.execute("SELECT id, content FROM document_chunks WHERE embedding IS NULL")
                rows = cur.fetchall()
                for row in rows:
                    chunk_id = row["id"]
                    content = row["content"]
                    embedding = embed_query(content)
                    cur.execute(
                        "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                        (embedding, chunk_id),
                    )
            except Exception:
                pass

            conn.commit()

    return dict(topic_to_chunks)


def clear_benchmark_data() -> None:
    """Remove all seeded benchmark documents and chunks."""
    with acquire() as conn:
        with conn.cursor() as cur:
            titles = list(d["title"] for d in BENCHMARK_DOCS)
            cur.execute(
                "DELETE FROM document_chunks WHERE content IN ("
                "    SELECT content FROM document_chunks c "
                "    JOIN documents d ON d.id = c.document_id "
                "    WHERE d.title = ANY(%s)"
                ")",
                (titles,),
            )
            cur.execute(
                "DELETE FROM documents WHERE title = ANY(%s)",
                (titles,),
            )
            conn.commit()


if __name__ == "__main__":
    topics = seed_benchmark_data()
    print(f"Seeded benchmark data. Topic mapping:")
    for topic, ids in sorted(topics.items()):
        print(f"  {topic}: {ids}")
