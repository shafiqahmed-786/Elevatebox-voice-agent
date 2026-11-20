"""
These three endpoints are what get configured as OmniDimension "Custom API"
agent actions (see app/decision/signal_schema.py for the matching tool
schemas the in-call LLM is given) plus a call-ended webhook. OmniDimension
calls these DURING the live call; each request carries the call_id OmniDimension
was given at dispatch time so state ties back to the right Lead row.

Every handler here follows the same shape: validate -> load state -> apply
via the orchestrator -> save state -> return a small JSON result the voice
platform's LLM can react to ("ok": true/false, "message": ...). None of
these ever raise an unhandled exception back to the platform -- a 5xx here
would either break the live call or (worse) get silently swallowed by the
platform with no visibility, so every failure mode is caught and turned
into a structured `{"ok": false, "detail": ...}` response instead.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_idempotency_guard, get_whatsapp_client
from app.config import Settings, get_settings
from app.conversation.extraction import safe_parse_extracted_signals
from app.scheduler.callback_service import InvalidCallbackError, schedule_callback_from_phrase
from app.services.call_orchestrator import apply_turn, finalize_call
from app.services.idempotency import IdempotencyGuard
from app.services.lead_repository import get_lead_state, save_lead_state
from app.whatsapp.client import WhatsAppClient

logger = logging.getLogger("elevatebox.api.webhooks")
router = APIRouter(prefix="/webhooks/voice", tags=["webhooks"])


class SignalsWebhookRequest(BaseModel):
    call_id: str
    signals: dict  # raw tool-call input; validated defensively, see extraction.py
    key_quote: str | None = None


class CallbackWebhookRequest(BaseModel):
    call_id: str
    raw_phrase: str


class CallEndedRequest(BaseModel):
    call_id: str


async def _load_or_404(session: AsyncSession, call_id: str):
    lead = await get_lead_state(session, call_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"unknown call_id: {call_id}")
    return lead


@router.post("/signals")
async def receive_signals(
    body: SignalsWebhookRequest,
    session: AsyncSession = Depends(get_db_session),
    whatsapp_client: WhatsAppClient = Depends(get_whatsapp_client),
    guard: IdempotencyGuard = Depends(get_idempotency_guard),
    settings: Settings = Depends(get_settings),
) -> dict:
    lead = await _load_or_404(session, body.call_id)
    raw_signals = dict(body.signals)
    # The tool schema (app/decision/signal_schema.py) defines key_quote as
    # ONE property alongside the others inside a single tool call's
    # arguments -- so a real call from OmniDimension will send it nested
    # inside `signals`, not as a sibling field. Prefer that; fall back to
    # the top-level `key_quote` for callers (or older clients) that send it
    # separately, so both shapes work rather than one silently losing it.
    key_quote = raw_signals.pop("key_quote", None) or body.key_quote
    signals = safe_parse_extracted_signals(raw_signals, call_id=body.call_id)

    try:
        turn_result = await apply_turn(
            lead, signals,
            agent_name=settings.agent_name, agent_phone=settings.agent_phone,
            whatsapp_client=whatsapp_client, guard=guard, key_quote=key_quote,
        )
    except Exception as exc:  # noqa: BLE001 -- must never 500 back to a live call
        logger.exception("call=%s unhandled error applying signals turn", body.call_id)
        return {"ok": False, "detail": f"internal error: {exc.__class__.__name__}"}

    await save_lead_state(session, lead)
    return {
        "ok": True,
        "classification": lead.intent.classification.value if lead.intent else None,
        "actions_fired": turn_result.actions_fired,
        "errors": turn_result.errors,
    }


@router.post("/callback")
async def receive_callback_request(
    body: CallbackWebhookRequest,
    session: AsyncSession = Depends(get_db_session),
    guard: IdempotencyGuard = Depends(get_idempotency_guard),
) -> dict:
    lead = await _load_or_404(session, body.call_id)
    try:
        callback = await schedule_callback_from_phrase(lead, body.raw_phrase, guard)
    except InvalidCallbackError as exc:
        logger.warning("call=%s invalid callback phrase '%s': %s", body.call_id, body.raw_phrase, exc)
        return {"ok": False, "detail": str(exc)}

    await save_lead_state(session, lead)
    return {
        "ok": True,
        "confirmed_datetime_ist": callback.interpreted_datetime.isoformat(),
        "confirmation_note": callback.interpretation_note,
    }


@router.post("/call-ended")
async def call_ended(
    body: CallEndedRequest,
    session: AsyncSession = Depends(get_db_session),
    whatsapp_client: WhatsAppClient = Depends(get_whatsapp_client),
    guard: IdempotencyGuard = Depends(get_idempotency_guard),
    settings: Settings = Depends(get_settings),
) -> dict:
    lead = await _load_or_404(session, body.call_id)
    try:
        turn_result = await finalize_call(
            lead, agent_name=settings.agent_name, agent_phone=settings.agent_phone,
            whatsapp_client=whatsapp_client, guard=guard,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("call=%s unhandled error finalizing call", body.call_id)
        return {"ok": False, "detail": f"internal error: {exc.__class__.__name__}"}

    await save_lead_state(session, lead)
    return {"ok": True, "actions_fired": turn_result.actions_fired, "errors": turn_result.errors}
