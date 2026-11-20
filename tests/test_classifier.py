from app.decision.classifier import classify_lead
from app.models.schemas import IntentClassification
from tests.fixtures.sample_conversations import COLD_CASES, HOT_CASES, WARM_CASES


def test_hot_cases():
    for label, signals in HOT_CASES:
        result = classify_lead(signals)
        assert result.classification == IntentClassification.HOT, (
            f"Expected HOT for [{label}], got {result.classification} "
            f"(scores hot={result.hot_score} warm={result.warm_score})"
        )
        assert result.confidence >= 0.5
        assert result.signals  # always explains itself


def test_warm_cases():
    for label, signals in WARM_CASES:
        result = classify_lead(signals)
        assert result.classification == IntentClassification.WARM, (
            f"Expected WARM for [{label}], got {result.classification} "
            f"(scores hot={result.hot_score} warm={result.warm_score})"
        )


def test_cold_cases():
    for label, signals in COLD_CASES:
        result = classify_lead(signals)
        assert result.classification == IntentClassification.COLD, (
            f"Expected COLD for [{label}], got {result.classification} "
            f"(scores hot={result.hot_score} warm={result.warm_score})"
        )


def test_barrier_always_caps_at_warm_even_with_strong_hot_signals():
    """This is the trickiest real-world case: a lead that looks HOT on
    paper (asked price, gave a big budget) but also has a real barrier
    (needs partner approval). The assignment's own definitions put the
    ACTION (schedule callback vs. fire WhatsApp now) ahead of the raw
    enthusiasm level, so this must resolve to WARM, not HOT."""
    from app.models.schemas import ExtractedSignals

    signals = ExtractedSignals(
        asked_price=True,
        asked_start_timeline=True,
        concrete_budget_inr=200000,
        concrete_timeline="2 weeks",
        approval_barrier="wife",
        has_business_context=True,
    )
    result = classify_lead(signals)
    assert result.classification == IntentClassification.WARM
    assert result.hot_score >= 5  # would have cleared HOT on its own
    assert any("sign-off" in s or "approval" in s for s in result.signals)


def test_empty_signals_is_cold_not_a_crash():
    from app.models.schemas import ExtractedSignals

    result = classify_lead(ExtractedSignals())
    assert result.classification == IntentClassification.COLD
    assert 0.0 <= result.confidence <= 1.0
