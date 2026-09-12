import json

import pytest

from app.brain import classifier, demo_drafting
from app.demo_pair import offer_body
from app.state import Position, Tier, new_negotiation


def test_ai_wording_preserves_offer_and_demo_footer(monkeypatch):
    monkeypatch.setattr(demo_drafting, "complete", lambda *a, **k: json.dumps({"sentence": "Thank you for considering our proposal."}))
    body = offer_body(11, 21, agreed=True)
    result, model = demo_drafting.draft_fixed_offer(body, role="supplier", tier=Tier.ROUTINE, context="Market evidence")
    assert result.splitlines()[0] == body.splitlines()[0]
    assert result.endswith(body.split("\n\n")[1])
    assert "Thank you" in result
    assert model == "openai/gpt-4o-mini"


@pytest.mark.parametrize("sentence", ["The new price is 9 EUR.", "We agree to exclusivity.", "Payment due on receipt.", "", ["invalid"]])
def test_ai_cannot_add_numeric_or_structural_terms(monkeypatch, sentence):
    monkeypatch.setattr(demo_drafting, "complete", lambda *a, **k: json.dumps({"sentence": sentence}))
    body = offer_body(11, 21)
    result, model = demo_drafting.draft_fixed_offer(body, role="buyer", tier=Tier.ROUTINE, context="")
    assert result == body
    assert model == "demo rules (AI wording rejected)"


def test_provider_failure_keeps_fixed_offer_and_labels_fallback(monkeypatch):
    def fail(*a, **k):
        raise TimeoutError()
    monkeypatch.setattr(demo_drafting, "complete", fail)
    body = offer_body(11, 21)
    result, model = demo_drafting.draft_fixed_offer(body, role="buyer", tier=Tier.ROUTINE, context="")
    assert result == body
    assert model == "demo rules (AI unavailable)"


@pytest.mark.parametrize("raw", ['[]', '{"extracted": "bad"}', '{"extracted": {"unit_price_eur": "free"}}'])
def test_malformed_classification_escalates(monkeypatch, raw):
    monkeypatch.setattr(classifier, "complete", lambda *a, **k: raw)
    tier, _, _ = classifier.classify(new_negotiation(), "Supplier reply")
    assert tier is Tier.ESCALATE


def test_delivery_only_breach_is_enforced_without_price(monkeypatch):
    state = new_negotiation()
    assert state.mandate.floor_price_eur == 12.5
    assert not state.is_within_mandate(Position(lead_time_days=40))
    monkeypatch.setattr(classifier, "complete", lambda *a, **k: '{"tier":"routine","extracted":{"lead_time_days":40}}')
    tier, _, _ = classifier.classify(state, "Delivery will take 40 days.")
    assert tier is Tier.ESCALATE
