"""Unit tests for corpus-derived vocabulary protection in spell correction.

Regression coverage for a retrieval failure found by auditing a real
glossary upload: "What is RESPA?" returned "no answer" while "What does
RESPA regulate?" worked. The cause was not retrieval at all -- the spell
corrector rewrote the query to "what is repay" before any search ran,
because "respa" is absent from the static domain vocabulary and scores
exactly 80.0 (the acceptance threshold) against "repay".

The corrector's own stated rule is "correct a token only when it is NOT
already a known term". The indexed corpus is the authoritative source of
what counts as a known term -- a token that literally occurs in the
user's documents is a word, not a typo -- so the vocabulary is now
derived from the corpus in addition to the static lists. This
generalises to any entity in any document the user uploads later,
instead of requiring every acronym to be hardcoded up front.
"""

from __future__ import annotations

import pytest

from app.query_processing import corpus_vocab, spell_correction


@pytest.fixture(autouse=True)
def _reset_vocab():
    corpus_vocab.reset()
    yield
    corpus_vocab.reset()


class TestCorpusProtection:
    def test_corpus_term_is_not_corrected(self):
        """The exact bug: RESPA -> repay."""
        assert spell_correction.correct("what is respa") == "what is repay"
        corpus_vocab.install(["respa", "tila"])
        assert spell_correction.correct("what is respa") == "what is respa"

    def test_protection_is_scoped_to_the_corpus(self):
        """A token absent from both the static vocab and the corpus is
        still eligible for correction -- this must not become a blanket
        disable of spell correction."""
        corpus_vocab.install(["respa"])
        assert spell_correction.correct("minimum credt score") == "minimum credit score"

    def test_real_typos_still_corrected_with_corpus_loaded(self):
        corpus_vocab.install(["respa", "tila", "escrow"])
        assert spell_correction.correct("inocme requirements") == "income requirements"

    def test_reset_restores_unprotected_behaviour(self):
        corpus_vocab.install(["respa"])
        assert spell_correction.correct("what is respa") == "what is respa"
        corpus_vocab.reset()
        assert spell_correction.correct("what is respa") == "what is repay"

    def test_short_and_nonalpha_entries_are_ignored(self):
        """Guards the vocabulary against junk that would weaken matching."""
        corpus_vocab.install(["a", "5/1", "", "respa"])
        assert corpus_vocab.active_vocabulary() == frozenset({"respa"})

    def test_entries_are_lowercased(self):
        corpus_vocab.install(["RESPA"])
        assert corpus_vocab.active_vocabulary() == frozenset({"respa"})


class TestLoadFromDatabase:
    class _Cursor:
        def __init__(self, rows):
            self._rows = rows
            self.queries = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.queries.append(sql)

        def fetchall(self):
            return self._rows.pop(0)

    class _Conn:
        def __init__(self, rows):
            self._rows = rows
            self.cursors = []

        def cursor(self):
            cur = TestLoadFromDatabase._Cursor(self._rows)
            self.cursors.append(cur)
            return cur

    def test_load_merges_words_aliases_and_concepts(self):
        conn = self._Conn([
            [{"word": "respa"}, {"word": "equity"}],
            [{"alias": "TILA", "canonical": "truth in lending act"}],
            [{"term": "Equity"}, {"term": "Annual Percentage Rate (APR)"}],
        ])
        words = corpus_vocab.load(conn)
        assert "respa" in words
        assert "tila" in words
        # Multi-word canonicals contribute their component words.
        assert "lending" in words
        assert corpus_vocab.active_concepts() >= {
            "equity", "annual percentage rate", "apr",
        }

    def test_load_failure_is_non_fatal(self):
        """A vocabulary problem must degrade correction, never fail search."""
        class _Boom:
            def cursor(self):
                raise RuntimeError("db down")

        assert corpus_vocab.load(_Boom()) == frozenset()


class TestRelevanceDenominator:
    """A query term absent from the corpus must not be a requirement."""

    def test_absent_terms_drop_out_of_the_denominator(self):
        from app.query_processing.relevance import relevance_factor

        question = "Which loan type has a payment that never changes?"
        answer = ("Fixed-Rate Mortgage: A mortgage where the interest rate "
                  "remains the same for the entire loan term, providing "
                  "predictable monthly payments.")

        corpus_vocab.reset()
        before = relevance_factor(question, answer)

        corpus_vocab.install(["loan", "payment", "type", "mortgage",
                              "interest", "rate", "term"])
        after = relevance_factor(question, answer)

        # "never" and "changes" appear in no document, so requiring the
        # answer to contain them only drags a correct answer down.
        assert after > before
        # Comfortably clear of the 0.35 no-answer floor this query used to
        # fall under (it scored 0.333 live).
        assert after >= 0.5

    def test_no_filtering_without_a_loaded_vocabulary(self):
        from app.query_processing import relevance

        corpus_vocab.reset()
        groups = [{"never"}, {"loan"}]
        assert relevance.corpus_supported_groups(groups) == groups

    def test_all_unsupported_falls_back_to_unfiltered(self):
        """A query sharing no vocabulary with the corpus is evidence of no
        answer; it must not collapse to a vacuous 1.0."""
        from app.query_processing import relevance

        corpus_vocab.install(["mortgage", "escrow"])
        groups = [{"capital"}, {"france"}]
        assert relevance.corpus_supported_groups(groups) == groups

    def test_supported_terms_are_kept(self):
        from app.query_processing import relevance

        corpus_vocab.install(["loan", "mortgage"])
        kept = relevance.corpus_supported_groups([{"never"}, {"loan"}])
        assert kept == [{"loan"}]


class TestConceptDecomposition:
    """A coordinated list of corpus-defined terms is several questions."""

    GLOSSARY_CONCEPTS = [
        "Amortization", "Annual Percentage Rate (APR)", "Principal",
        "Equity", "Underwriting", "Points (Discount Points)",
        "Prepayment Penalty", "Loan Servicer",
    ]

    def _install(self):
        corpus_vocab.install(["loan", "equity"], self.GLOSSARY_CONCEPTS)

    def test_defined_term_is_a_known_concept(self):
        self._install()
        assert corpus_vocab.is_known_concept("equity")
        assert corpus_vocab.is_known_concept("underwriting")

    def test_request_verb_is_stripped(self):
        self._install()
        assert corpus_vocab.is_known_concept("define amortization")

    def test_parenthesised_acronym_is_its_own_concept(self):
        self._install()
        assert corpus_vocab.is_known_concept("apr")
        assert corpus_vocab.is_known_concept("annual percentage rate")

    def test_undefined_term_is_not_a_concept(self):
        self._install()
        assert not corpus_vocab.is_known_concept("employment")

    def test_nothing_is_a_concept_before_loading(self):
        corpus_vocab.reset()
        assert not corpus_vocab.is_known_concept("equity")

    def test_two_term_list_splits(self):
        from app.query_processing.multi_question import split_questions

        self._install()
        assert split_questions("explain equity and underwriting") == [
            "explain equity", "underwriting",
        ]

    def test_three_term_list_splits(self):
        from app.query_processing.multi_question import split_questions

        self._install()
        assert split_questions("define amortization, equity, and underwriting") == [
            "define amortization", "equity", "underwriting",
        ]

    def test_joint_noun_phrase_still_stays_one_question(self):
        """The over-split guard must survive: these are not defined terms,
        so 'income and employment requirements' is a single request."""
        from app.query_processing.multi_question import split_questions

        self._install()
        assert split_questions("income and employment requirements") == [
            "income and employment requirements",
        ]


class TestMorphologySymmetry:
    """Vocabulary membership must work in both directions.

    The corpus stores "payments"; a query asks about "payment". Looking
    the term up only strips suffixes from the query side, so the match
    failed and "payment" was treated as a word the documents do not
    cover -- dropping it from the relevance denominator and suppressing a
    correct answer ("Which loan type has a payment that never changes?"
    -> the Fixed-Rate Mortgage definition).
    """

    def test_singular_query_term_matches_plural_corpus_word(self):
        corpus_vocab.install(["payments"])
        assert "payment" in corpus_vocab.active_vocabulary()

    def test_plural_query_term_matches_singular_corpus_word(self):
        corpus_vocab.install(["payment"])
        assert "payment" in corpus_vocab.active_vocabulary()

    def test_relative_pronouns_are_not_content_terms(self):
        from app.query_processing.relevance import content_term_groups

        flat = {t for g in content_term_groups(
            "Which loan type has a payment that never changes?") for t in g}
        assert "that" not in flat
        assert "which" not in flat
        assert "loan" in flat
