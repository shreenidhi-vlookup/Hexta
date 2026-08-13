"""Unit tests for scope_guard: questions no document lookup can answer."""

from __future__ import annotations

from app.query_processing.scope_guard import (
    is_fraud_intent,
    is_personal_data_request,
    out_of_scope_reason,
)


class TestPersonalDataRequests:
    def test_my_account_balance(self):
        assert is_personal_data_request("What is my account balance?")

    def test_my_credit_score(self):
        assert is_personal_data_request("What is my credit score?")

    def test_my_loan_application_status(self):
        assert is_personal_data_request(
            "What is the status of my loan application?"
        )

    def test_my_application(self):
        assert is_personal_data_request("Can you check my application?")

    def test_general_credit_score_requirement_is_not_personal(self):
        """The KB genuinely answers this -- it must not be guarded."""
        assert not is_personal_data_request(
            "What is the minimum credit score for a conventional loan?"
        )

    def test_general_documentation_question_is_not_personal(self):
        assert not is_personal_data_request(
            "What documents do I need to apply?"
        )


class TestFraudIntent:
    def test_forge_pay_stub(self):
        assert is_fraud_intent("How do I forge a pay stub?")

    def test_fake_proof_of_income(self):
        assert is_fraud_intent("How do I fake proof of income?")

    def test_falsify_tax_return(self):
        assert is_fraud_intent("Can I falsify my tax return?")

    def test_hide_debt_from_lender(self):
        assert is_fraud_intent("How do I hide debt from the lender?")

    def test_legitimate_documentation_question_is_not_fraud(self):
        assert not is_fraud_intent(
            "What documents do I need to apply for a mortgage?"
        )

    def test_verb_without_financial_target_is_not_fraud(self):
        """"Hide" alone, with no lender-relevant target, must not trip
        the guard -- both a verb and a target are required."""
        assert not is_fraud_intent("Where can I hide during a storm?")


class TestOutOfScopeReason:
    def test_personal_data_reason(self):
        assert out_of_scope_reason("What is my account balance?") == "personal_data"

    def test_fraud_reason(self):
        assert out_of_scope_reason("How do I forge a pay stub?") == "fraud_intent"

    def test_legitimate_question_has_no_reason(self):
        assert out_of_scope_reason("What is the FHA down payment?") is None

    def test_empty_question(self):
        assert out_of_scope_reason("") is None
        assert out_of_scope_reason(None) is None
