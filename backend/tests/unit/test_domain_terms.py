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
