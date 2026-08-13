"""Unit tests for domain vocabulary and scenario → concept mapping."""

from __future__ import annotations

from app.query_processing import domain_terms
from app.query_processing.domain_terms import scenario_concepts_for


class TestNewVocabulary:
    def test_sar_alias_resolves(self):
        assert domain_terms.canonical_of("sar") == "subject access request"

    def test_lifetime_mortgage_alias(self):
        assert domain_terms.canonical_of("lifetime mortgage") == "lifetime mortgage"

    def test_bridging_alias(self):
        assert domain_terms.canonical_of("bridging finance") == "bridging finance"

    def test_data_erasure_alias(self):
        assert domain_terms.canonical_of("delete my data") == "data erasure"

    def test_relevance_synonyms_job_employment_symmetric(self):
        assert "employment" in domain_terms.relevance_synonyms_of("job")
        assert "job" in domain_terms.relevance_synonyms_of("employment")

    def test_relevance_synonyms_unknown_term_empty(self):
        assert domain_terms.relevance_synonyms_of("mortgage") == frozenset()

    def test_unknown_alias_returns_itself_unchanged(self):
        """Regression: canonical_of() used to be
        ``_ALIAS_INDEX.get(alias, alias)[0]`` — for an alias with no index
        entry, the fallback ``alias`` (a string) was itself indexed with
        ``[0]``, silently truncating it to its first character instead of
        returning it unchanged."""
        assert domain_terms.canonical_of("verify") == "verify"
        assert domain_terms.canonical_of("job") == "job"
        assert domain_terms.canonical_of("xyz") == "xyz"


class TestScenarioConcepts:
    def test_older_homeowner_equity_release(self):
        concepts = scenario_concepts_for(
            "my client is 70, owns their home and wants access to some money without selling the property"
        )
        assert "equity release" in concepts

    def test_retired_release_equity(self):
        assert "equity release" in scenario_concepts_for("i am retired and want to release cash")

    def test_bridging_scenario(self):
        assert "bridging finance" in scenario_concepts_for("i need a bridge loan for the chain")

    def test_no_concept_match(self):
        assert scenario_concepts_for("what is the minimum credit score?") == []


class TestDeathScenarioConcepts:
    """Death / repayment-on-death questions should expand to the lifetime
    mortgage repayment concept so retrieval finds the 'home is sold to
    repay the loan' answer instead of unrelated chunks."""

    def test_property_when_they_die(self):
        concepts = scenario_concepts_for("what happens to the property when they die")
        assert any("lifetime mortgage" in c for c in concepts)

    def test_borrower_dies(self):
        concepts = scenario_concepts_for("what happens when the borrower dies")
        assert any("lifetime mortgage" in c for c in concepts)

    def test_when_i_die(self):
        concepts = scenario_concepts_for("what happens to my home when i die")
        assert any("lifetime mortgage" in c for c in concepts)

    def test_repaid_on_death(self):
        concepts = scenario_concepts_for("how is the loan repaid on death")
        assert any("lifetime mortgage" in c for c in concepts)

    def test_sold_to_repay(self):
        concepts = scenario_concepts_for("is the home sold to repay the mortgage on death")
        assert any("lifetime mortgage" in c for c in concepts)

    def test_no_death_no_match(self):
        assert scenario_concepts_for("is a lifetime mortgage repaid") == []

    def test_unrelated_die_usage_not_matched(self):
        assert scenario_concepts_for("the insurance pays out on diagnosis") == []


class TestContainsKnownConcept:
    """Used by multi_question.py to tell a bare noun-phrase list item
    ("the VA down payment") apart from an incomplete attribute
    ("income")."""

    def test_single_token_lender_alias(self):
        assert domain_terms.contains_known_concept("the va down payment")

    def test_multiword_metric_alias(self):
        assert domain_terms.contains_known_concept("what is the down payment")

    def test_metric_abbreviation(self):
        assert domain_terms.contains_known_concept("max dti")

    def test_bare_attribute_not_a_known_concept(self):
        assert not domain_terms.contains_known_concept("income")
        assert not domain_terms.contains_known_concept("employment")

    def test_empty_text(self):
        assert not domain_terms.contains_known_concept("")
        assert not domain_terms.contains_known_concept(None)
