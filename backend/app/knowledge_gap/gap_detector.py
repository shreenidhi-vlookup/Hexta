"""Knowledge gap detection.

Logs queries that result in low confidence or no answer, so the
content team can identify gaps in the knowledge base and prioritize
document ingestion.
"""

from __future__ import annotations

from app.db.postgres.session import acquire


def detect_and_log(
    query: str,
    intent: str | None = None,
    confidence: float | None = None,
) -> None:
    """Log a knowledge gap if confidence is below threshold.

    A knowledge gap is any query where:
    - No documents were retrieved (confidence == 0), or
    - The confidence score is below the no-answer threshold
      (config.min_confidence_no_answer, default 50)

    These are written to the knowledge_gaps table for analytics review.
    Never raises — gap detection must not break the request path.
    """
    from app.config import settings

    threshold = settings.min_confidence_no_answer
    if confidence is not None and confidence >= threshold:
        return  # high enough confidence — not a gap

    try:
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO knowledge_gaps (query, intent, confidence) "
                    "VALUES (%s, %s, %s)",
                    (query, intent, confidence),
                )
                conn.commit()
    except Exception:
        pass  # silently fail — gap detection is best-effort
