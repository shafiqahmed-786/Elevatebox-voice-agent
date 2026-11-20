"""
Turns a raw callback phrase into a persisted, idempotent ScheduledCallback,
and (separately) the piece that actually fires due callbacks by re-dispatching
a call through the same VoiceProviderClient used for the first call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.schemas import CallbackRequest, LeadState
from app.scheduler.time_parser import parse_callback_phrase
from app.services.idempotency import IdempotencyGuard, try_claim_callback
from app.telephony.voice_provider_client import VoiceProviderClient

logger = logging.getLogger("elevatebox.scheduler")


class InvalidCallbackError(Exception):
    pass


async def schedule_callback_from_phrase(
    lead: LeadState, raw_phrase: str, guard: IdempotencyGuard, *, reference_dt: datetime | None = None
) -> CallbackRequest:
    """
    Parses `raw_phrase`, validates it lands in the future, applies the
    idempotency guard, and attaches the result to `lead.callback`.
    Raises InvalidCallbackError (never a bare exception) if the phrase
    resolves to something unusable, so the caller can respond to the voice
    platform with a clean error instead of a 500.
    """
    if not await try_claim_callback(lead, guard):
        logger.info("call=%s duplicate callback request ignored (already scheduled)", lead.call_id)
        assert lead.callback is not None
        return lead.callback

    parsed = parse_callback_phrase(raw_phrase, reference_dt=reference_dt)

    now = reference_dt or datetime.now(parsed.interpreted_datetime.tzinfo or timezone.utc)
    if parsed.interpreted_datetime <= now:
        raise InvalidCallbackError(
            f"parsed callback time {parsed.interpreted_datetime.isoformat()} is not in the future"
        )

    callback = CallbackRequest(
        raw_phrase=raw_phrase,
        interpreted_datetime=parsed.interpreted_datetime,
        interpretation_note=parsed.interpretation_note,
        confidence=parsed.confidence,
        status="scheduled",
    )
    lead.callback = callback
    logger.info(
        "call=%s callback scheduled for %s (confidence=%.2f, note=%s)",
        lead.call_id, callback.interpreted_datetime.isoformat(), callback.confidence, callback.interpretation_note,
    )
    return callback


async def fire_due_callbacks(
    due_callbacks: list[tuple[LeadState, CallbackRequest]],
    voice_client: VoiceProviderClient,
) -> list[str]:
    """
    Re-dispatches a call for every due, still-scheduled callback. Intended
    to be invoked by a periodic background task (see app/main.py) or a
    scripts/run_due_callbacks.py cron entry in production -- deliberately
    NOT a Celery/Redis job queue, per the assignment's "Redis/background
    jobs only if genuinely useful" guidance; a callback backlog of dozens
    of leads doesn't need one.
    """
    fired: list[str] = []
    for lead, callback in due_callbacks:
        if callback.status != "scheduled":
            continue
        result = await voice_client.dispatch_call(
            to_phone_e164=lead.caller_phone or "",
            call_context={"reason": "scheduled_callback", "call_id": lead.call_id, "prior_notes": lead.notes or ""},
        )
        if result.success:
            callback.status = "fired"
            fired.append(lead.call_id)
            logger.info("call=%s callback fired successfully, provider_call_id=%s", lead.call_id, result.provider_call_id)
        else:
            logger.error("call=%s callback dispatch FAILED: %s", lead.call_id, result.error)
    return fired
