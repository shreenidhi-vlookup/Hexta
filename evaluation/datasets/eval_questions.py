"""Evaluation dataset: realistic mortgage questions with expected answers.

Each entry has:
- question: the raw user query
- topic_keys: list of topic keys that map to expected_chunk_ids
  (see datasets/seed_benchmark_data.py for the topic -> chunk_id mapping)
- expected_document_id: the document ID that should be retrieved (or null)
- expected_chunk_ids: chunk IDs that contain the answer (populated at runtime
  from the benchmark seed mapping; not stored statically because chunk IDs
  are assigned by the database)
- expected_intent: the expected sub-query intent classification
- sub_question_count: expected number of sub-questions after splitting
- should_correct: whether spell correction should fire
- expected_entities: canonical entities that should be extracted

Build this from ACTUAL ingested content, not invented in the abstract.
"""

DATASET = [
    {
        "id": 1,
        "question": "what is the minimum credit score",
        "normalized": "what is the minimum credit score",
        "expected_corrected": "what is the minimum credit score",
        "expected_intent": "requirements",
        "expected_entities": ["credit score"],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["credit_score"],
    },
    {
        "id": 2,
        "question": "What documents are required, what is the maximum LTV, and also tell me the minimum credit score?",
        "normalized": "what documents are required, what is the maximum ltv, and also tell me the minimum credit score?",
        "expected_corrected": "what documents are required, what is the maximum ltv, and also tell me the minimum credit score?",
        "expected_intent": "documents",
        "expected_entities": ["loan to value", "credit score"],
        "expected_sub_questions": 3,
        "expected_answer": True,
        "topic_keys": ["documents", "ltv", "credit_score"],
    },
    {
        "id": 3,
        "question": "what is the minimun credt scor",
        "normalized": "what is the minimun credt scor",
        "expected_corrected": "what is the minimum credit score",
        "expected_intent": "requirements",
        "expected_entities": ["credit score"],
        "expected_sub_questions": 1,
        "should_correct": True,
        "expected_answer": True,
        "topic_keys": ["credit_score"],
    },
    {
        "id": 4,
        "question": "max ltv for investmnt properti",
        "normalized": "max ltv for investmnt properti",
        "expected_corrected": "max ltv for investment properties",
        "expected_intent": "limits",
        "expected_entities": ["loan to value", "investment property"],
        "expected_sub_questions": 1,
        "should_correct": True,
        "expected_answer": True,
        "topic_keys": ["ltv"],
    },
    {
        "id": 5,
        "question": "What are the income and employment requirements?",
        "normalized": "what are the income and employment requirements?",
        "expected_corrected": "what are the income and employment requirements?",
        "expected_intent": "requirements",
        "expected_entities": [],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["employment"],
    },
    {
        "id": 6,
        "question": "what documnts are requred",
        "normalized": "what documnts are requred",
        "expected_corrected": "what documents are required",
        "expected_intent": "documents",
        "expected_entities": ["document"],
        "expected_sub_questions": 1,
        "should_correct": True,
        "expected_answer": True,
        "topic_keys": ["documents"],
    },
    {
        "id": 7,
        "question": "What is the maximum LTV for a conventional loan?",
        "normalized": "what is the maximum ltv for a conventional loan?",
        "expected_corrected": "what is the maximum ltv for a conventional loan?",
        "expected_intent": "limits",
        "expected_entities": ["loan to value", "conventional"],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["ltv"],
    },
    {
        "id": 8,
        "question": "how much down payment do i need for a house",
        "normalized": "how much down payment do i need for a house",
        "expected_corrected": "how much down payment do i need for a house",
        "expected_intent": "requirements",
        "expected_entities": ["down payment"],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["down_payment"],
    },
    {
        "id": 9,
        "question": "fha vs va loan differences",
        "normalized": "fha vs va loan differences",
        "expected_corrected": "fha vs va loan differences",
        "expected_intent": "definition",
        "expected_entities": ["federal housing administration", "veterans affairs"],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["fha", "va", "fha_va"],
    },
    {
        "id": 10,
        "question": "tell me about the closing process and what fees i will pay",
        "normalized": "tell me about the closing process and what fees i will pay",
        "expected_corrected": "tell me about the closing process and what fees i will pay",
        "expected_intent": "process",
        "expected_entities": ["closing"],
        "expected_sub_questions": 2,
        "expected_answer": True,
        "topic_keys": ["closing", "fees"],
    },
    {
        "id": 11,
        "question": "",
        "normalized": "",
        "expected_corrected": "",
        "expected_intent": "general",
        "expected_entities": [],
        "expected_sub_questions": 0,
        "expected_answer": False,
        "topic_keys": [],
    },
    {
        "id": 12,
        "question": "asdfqwer zxcvbnm",
        "normalized": "asdfqwer zxcvbnm",
        "expected_corrected": "asdfqwer zxcvbnm",
        "expected_intent": "general",
        "expected_entities": [],
        "expected_sub_questions": 1,
        "expected_answer": False,
        "topic_keys": [],
    },
    {
        # Regression coverage for the hybrid_orchestrator hard-BM25-gate bug:
        # this phrasing shares zero vocabulary with the "employment"-topic
        # chunk ("Borrowers must demonstrate stable employment history...
        # employment verification includes recent pay stubs..."), so it can
        # only be retrieved via vector similarity, not keyword overlap. The
        # old unconditional `c.fts @@ to_tsquery(...)` WHERE-clause gate
        # excluded the chunk entirely for this query; search/hybrid_orchestrator.py
        # now admits it via the min_vector_similarity floor instead.
        "id": 13,
        "question": "how do lenders verify I have a job",
        "normalized": "how do lenders verify i have a job",
        "expected_corrected": "how do lenders verify i have a job",
        "expected_intent": "process",
        "expected_entities": [],
        "expected_sub_questions": 1,
        "expected_answer": True,
        "topic_keys": ["employment"],
    },
]


def load_dataset() -> list[dict]:
    return DATASET
