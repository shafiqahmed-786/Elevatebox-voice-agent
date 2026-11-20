from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.schemas import LeadState
from app.scheduler.callback_service import InvalidCallbackError, fire_due_callbacks, schedule_callback_from_phrase
from app.services.idempotency import IdempotencyGuard
from app.telephony.voice_provider_client import MockVoiceProviderClient

IST = ZoneInfo("Asia/Kolkata")
REFERENCE = datetime(2026, 8, 22, 12, 0, tzinfo=IST)


@pytest.mark.asyncio
async def test_schedule_callback_from_phrase_attaches_to_lead():
    lead = LeadState(call_id="cb1")
    guard = IdempotencyGuard()
    callback = await schedule_callback_from_phrase(lead, "tomorrow morning", guard, reference_dt=REFERENCE)
    assert lead.callback is callback
    assert callback.status == "scheduled"
    assert callback.interpreted_datetime > REFERENCE


@pytest.mark.asyncio
async def test_duplicate_schedule_request_returns_existing_callback_unchanged():
    lead = LeadState(call_id="cb2")
    guard = IdempotencyGuard()
    first = await schedule_callback_from_phrase(lead, "tomorrow morning", guard, reference_dt=REFERENCE)
    second = await schedule_callback_from_phrase(lead, "Friday at 4", guard, reference_dt=REFERENCE)
    # Second call must NOT overwrite the first -- idempotency guard blocks it.
    assert second is first
    assert lead.callback.raw_phrase == "tomorrow morning"


@pytest.mark.asyncio
async def test_past_resolved_datetime_raises_invalid_callback_error(monkeypatch):
    """`parse_callback_phrase` is itself designed to always roll forward
    into the future (see time_parser.py), so no real phrase can trigger
    this path through the parser alone -- the guard in callback_service is
    defense-in-depth against a parser bug or clock drift. Test it in
    isolation by patching the parser to (deliberately, for this test only)
    return something in the past, so the guard clause itself is proven to
    actually fire rather than being dead code."""
    import app.scheduler.callback_service as callback_service_module
    from app.scheduler.time_parser import ParsedCallback

    def fake_parse(phrase, reference_dt=None):
        return ParsedCallback(
            interpreted_datetime=REFERENCE.replace(year=2020),  # unambiguously in the past
            interpretation_note="forced for test",
            confidence=0.9,
        )

    monkeypatch.setattr(callback_service_module, "parse_callback_phrase", fake_parse)

    lead = LeadState(call_id="cb3")
    guard = IdempotencyGuard()
    with pytest.raises(InvalidCallbackError):
        await schedule_callback_from_phrase(lead, "some phrase", guard, reference_dt=REFERENCE)


@pytest.mark.asyncio
async def test_fire_due_callbacks_dispatches_and_marks_fired():
    lead = LeadState(call_id="cb4", caller_phone="+919876543210")
    guard = IdempotencyGuard()
    callback = await schedule_callback_from_phrase(lead, "tomorrow morning", guard, reference_dt=REFERENCE)
    voice_client = MockVoiceProviderClient()

    fired = await fire_due_callbacks([(lead, callback)], voice_client)

    assert fired == ["cb4"]
    assert callback.status == "fired"
    assert len(voice_client.dispatched_calls) == 1
    assert voice_client.dispatched_calls[0]["to"] == "+919876543210"
    assert voice_client.dispatched_calls[0]["call_context"]["reason"] == "scheduled_callback"


@pytest.mark.asyncio
async def test_fire_due_callbacks_skips_non_scheduled_status():
    lead = LeadState(call_id="cb5", caller_phone="+919876543210")
    guard = IdempotencyGuard()
    callback = await schedule_callback_from_phrase(lead, "tomorrow morning", guard, reference_dt=REFERENCE)
    callback.status = "cancelled"
    voice_client = MockVoiceProviderClient()

    fired = await fire_due_callbacks([(lead, callback)], voice_client)

    assert fired == []
    assert len(voice_client.dispatched_calls) == 0
