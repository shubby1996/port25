import json

import pytest

from app.brain import classifier, context, demo_drafting
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


def test_market_research_extracts_regional_movement(monkeypatch):
    monkeypatch.setattr(context, "fetch_market_context", lambda *a, **k: "- Current aluminium source")
    monkeypatch.setattr(context, "complete", lambda *a, **k: json.dumps({
        "benchmark_price_per_metric_tonne": 3_100,
        "currency": "USD",
        "buyer_region_price_per_metric_tonne": 3_000,
        "supplier_region_price_per_metric_tonne": 3_255,
        "change_pct_30d": 4.2,
        "change_period": "monthly",
        "buyer_region_change_pct": -2.5,
        "supplier_region_change_pct": 1.2,
        "buyer_region_adjustment_pct": 2.5,
        "supplier_region_adjustment_pct": 7.0,
        "summary": "Recent evidence shows aluminium rising with a higher North American premium.",
    }))
    brief = context.research_commodity_market(
        "Primary aluminium", "Europe", "North America", fallback_benchmark=2_900,
    )
    assert brief.benchmark_price_per_metric_tonne == 3_100
    assert brief.currency == "USD"
    assert brief.change_pct_30d == 4.2
    assert brief.buyer_region_change_pct == -2.5
    assert brief.buyer_region_adjustment_pct == -3.2
    assert brief.supplier_region_adjustment_pct == 5.0
    assert not brief.used_fallback
    assert "Current aluminium source" in brief.display(
        commodity="Primary aluminium", buyer_region="Europe", supplier_region="North America",
    )


def test_market_research_falls_back_when_values_are_not_safe(monkeypatch):
    monkeypatch.setattr(context, "fetch_market_context", lambda *a, **k: "- Ambiguous result")
    monkeypatch.setattr(context, "complete", lambda *a, **k: '{"benchmark_price_per_metric_tonne": 999999999, "currency": "USD"}')
    brief = context.research_commodity_market(
        "Primary aluminium", "Europe", "North America", fallback_benchmark=2_900,
    )
    assert brief.used_fallback
    assert brief.benchmark_price_per_metric_tonne == 2_900


def test_market_context_filters_irrelevant_titles_and_compacts_display(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "Aluminium regional price index", "publishedDate": "2026-09-01", "url": "https://market.example/aluminium", "text": "Useful aluminium evidence"},
                {"title": "Industrial pump catalogue", "publishedDate": "2026-09-01", "url": "https://market.example/pump", "text": "An aluminium pump housing"},
            ]}
    monkeypatch.setenv("EXA_API_KEY", "test")
    monkeypatch.setattr(context.httpx, "post", lambda *a, **k: Response())
    evidence = context.fetch_market_context("aluminium", title_terms=("aluminium", "aluminum"))
    assert "Aluminium regional price index" in evidence
    assert "pump catalogue" not in evidence
    brief = context.MarketBrief(
        benchmark_price_per_metric_tonne=3_300, currency="USD", change_pct_30d=-2,
        buyer_region_adjustment_pct=-5, supplier_region_adjustment_pct=1,
        summary="Current aluminium benchmark with two regional price signals.", evidence=evidence,
    )
    displayed = brief.display(commodity="Aluminium", buyer_region="Europe", supplier_region="North America")
    assert "https://market.example/aluminium" in displayed
    assert "Useful aluminium evidence" not in displayed
