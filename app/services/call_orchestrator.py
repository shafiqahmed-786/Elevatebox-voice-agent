"""
The single place that turns "new information arrived about a call" into
"lead state updated, classification (re)computed, and the right action
fired" -- used identically by the live webhook handler and by
scripts/simulate_call.py, so the simulation is a genuine end-to-end
exercise of production logic, not a separate demo-only path.

    apply_turn()
      -> merges ExtractedSignals into LeadState (never overwrites a known
         fact with an unknown one -- see _merge_signals)
      -> re-runs classify_lead()
      -> if now HOT and not already sent: sends mid-call WhatsApp
      -> returns the updated LeadState + whatever actions fired this turn
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.decision.classifier import classify_lead, merge_signals
from app.models.schemas import ActionStatus, ConversationStatus, ExtractedSignals, IntentClassification, LeadState
from app.services.idempotency import IdempotencyGuard, try_claim_followup_whatsapp, try_claim_midcall_whatsapp
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.payload_builder import (
    build_cold_brochure_message,
    build_followup_whatsapp_message,
    build_midcall_whatsapp_message,
)

logger = logging.getLogger("elevatebox.orchestrator")


@dataclass
class TurnResult:
    lead: LeadState
    actions_fired: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _apply_signals(lead: LeadState, signals: ExtractedSignals) -> None:
    """
    Folds this turn's signals into `lead.cumulative_signals` (the single
    accumulated record of everything said so far -- see
    app.decision.classifier.merge_signals for field-by-field merge
    semantics), then re-derives the display fields on `lead` (budget,
    timeline, features, barriers) FROM that accumulated record.

    Earlier versions of this function accumulated `lead.budget_inr` /
    `lead.timeline` / `lead.features` / `lead.barriers` directly, in
    parallel with (and separately from) whatever the classifier saw --
    which is what let classification silently regress on a neutral turn:
    the display fields were accumulating safely, but classify_lead() was
    still being called with only that turn's raw signals. Keeping ONE
    accumulated signal set as the single source of truth for both the
    display fields and the classifier closes that gap by construction --
    there is no longer a second, independently-maintained accumulation
    path for classification-relevant facts to fall out of sync with.
    """
    lead.cumulative_signals = merge_signals(lead.cumulative_signals, signals)
    cs = lead.cumulative_signals

    if cs.business_type:
        lead.business_type = cs.business_type
    if cs.sells_online_currently is not None:
        lead.sells_online_currently = cs.sells_online_currently
    if cs.product_count is not None:
        lead.product_count = cs.product_count
    if cs.decision_maker:
        lead.decision_maker = cs.decision_maker
    if cs.concrete_budget_inr is not None:
        lead.budget_inr = cs.concrete_budget_inr
    if cs.concrete_timeline:
        lead.timeline = cs.concrete_timeline
    lead.features = list(cs.specific_feature_questions)

    barriers = []
    if cs.budget_barrier:
        barriers.append("budget constraint")
    if cs.approval_barrier:
        barriers.append(f"needs approval from {cs.approval_barrier}")
    if cs.timing_barrier:
        barriers.append(cs.timing_barrier)
    lead.barriers = barriers


async def apply_turn(
    lead: LeadState,
    signals: ExtractedSignals,
    *,
    agent_name: str,
    agent_phone: str,
    whatsapp_client: WhatsAppClient,
    guard: IdempotencyGuard,
    key_quote: str | None = None,
) -> TurnResult:
    result = TurnResult(lead=lead)

    _apply_signals(lead, signals)
    if key_quote:
        lead.key_quotes.append(key_quote)

    lead.intent = classify_lead(lead.cumulative_signals)
    logger.info(
        "call=%s classification=%s confidence=%.2f signals=%s",
        lead.call_id, lead.intent.classification.value, lead.intent.confidence, lead.intent.signals,
    )

    if lead.intent.classification == IntentClassification.HOT:
        if await try_claim_midcall_whatsapp(lead, guard):
            message = build_midcall_whatsapp_message(lead, agent_name, agent_phone)
            send_result = await whatsapp_client.send_text_message(
                to_phone_e164=lead.caller_phone or "", text=message
            )
            if send_result.success:
                lead.whatsapp_midcall_sent_at = datetime.now(timezone.utc)
                result.actions_fired.append("whatsapp_midcall")
                logger.info("call=%s mid-call WhatsApp sent, provider_id=%s", lead.call_id, send_result.provider_message_id)
            else:
                # Per the assignment: WhatsApp failure must never crash or
                # interrupt the live conversation. Roll the claim back so a
                # later retry (e.g. next turn, or call-end fallback) can
                # still succeed instead of being permanently blocked by a
                # transient failure.
                lead.whatsapp_midcall_status = ActionStatus.FAILED
                result.errors.append(f"whatsapp_midcall_failed: {send_result.error}")
                logger.error("call=%s mid-call WhatsApp FAILED: %s", lead.call_id, send_result.error)

    return result


async def finalize_call(
    lead: LeadState,
    *,
    agent_name: str,
    agent_phone: str,
    whatsapp_client: WhatsAppClient,
    guard: IdempotencyGuard,
) -> TurnResult:
    """Called once when the call ends. Sends the follow-up WhatsApp
    (content depends on final classification) unless the mid-call message
    already covered a HOT lead and no new information arrived since --
    still sends a shorter closing note in that case so the customer always
    gets a final message with the callback time / next step, per the
    assignment's requirement #9 (send yourself, with context, after every call)."""
    result = TurnResult(lead=lead)
    lead.conversation_status = ConversationStatus.COMPLETED

    if not await try_claim_followup_whatsapp(lead, guard):
        return result

    if lead.intent and lead.intent.classification == IntentClassification.COLD:
        message = build_cold_brochure_message(lead, agent_name, agent_phone)
    else:
        message = build_followup_whatsapp_message(lead, agent_name, agent_phone)

    send_result = await whatsapp_client.send_text_message(to_phone_e164=lead.caller_phone or "", text=message)
    if send_result.success:
        lead.whatsapp_followup_sent_at = datetime.now(timezone.utc)
        result.actions_fired.append("whatsapp_followup")
        logger.info("call=%s follow-up WhatsApp sent, provider_id=%s", lead.call_id, send_result.provider_message_id)
    else:
        lead.whatsapp_followup_status = ActionStatus.FAILED
        result.errors.append(f"whatsapp_followup_failed: {send_result.error}")
        logger.error("call=%s follow-up WhatsApp FAILED: %s", lead.call_id, send_result.error)

    return result
