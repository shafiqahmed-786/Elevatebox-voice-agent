import pytest

from app.models.schemas import ExtractedSignals, IntentClassification, LeadState
from app.services.call_orchestrator import apply_turn, finalize_call
from app.services.idempotency import IdempotencyGuard
from app.whatsapp.client import MockWhatsAppClient


@pytest.mark.asyncio
async def test_hot_turn_fires_midcall_whatsapp_exactly_once():
    lead = LeadState(call_id="orch1", caller_phone="+919876543210", business_type="clothing")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()

    signals = ExtractedSignals(
        asked_price=True,
        concrete_budget_inr=70000,
        concrete_timeline="3 weeks",
        specific_feature_questions=["Razorpay"],
        has_business_context=True,
    )
    result = await apply_turn(
        lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
    )

    assert lead.intent.classification == IntentClassification.HOT
    assert "whatsapp_midcall" in result.actions_fired
    assert len(wa.sent_messages) == 1
    assert "clothing" in wa.sent_messages[0]["text"]
    assert "70,000" in wa.sent_messages[0]["text"]

    # A second HOT-triggering turn in the same call must NOT send again.
    result2 = await apply_turn(
        lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
    )
    assert "whatsapp_midcall" not in result2.actions_fired
    assert len(wa.sent_messages) == 1  # still just one


@pytest.mark.asyncio
async def test_warm_turn_does_not_fire_whatsapp():
    lead = LeadState(call_id="orch2", caller_phone="+919876543210")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()

    signals = ExtractedSignals(budget_barrier=True, general_interest=True, has_business_context=True)
    result = await apply_turn(
        lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
    )

    assert lead.intent.classification == IntentClassification.WARM
    assert result.actions_fired == []
    assert wa.sent_messages == []


@pytest.mark.asyncio
async def test_state_accumulates_across_multiple_turns_without_forgetting():
    """Regression guard for 'maintain conversation memory... do not
    repeatedly ask the same question' -- a later turn that doesn't repeat
    the budget must not erase the budget captured earlier."""
    lead = LeadState(call_id="orch3", caller_phone="+919876543210")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()

    await apply_turn(
        lead, ExtractedSignals(concrete_budget_inr=70000, has_business_context=True),
        agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard,
    )
    assert lead.budget_inr == 70000

    await apply_turn(
        lead, ExtractedSignals(concrete_timeline="3 weeks", has_business_context=True),
        agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard,
    )
    assert lead.budget_inr == 70000  # still remembered
    assert lead.timeline == "3 weeks"


@pytest.mark.asyncio
async def test_whatsapp_provider_failure_does_not_raise_and_allows_retry():
    lead = LeadState(call_id="orch4", caller_phone="+919876543210")
    wa = MockWhatsAppClient(fail_next=True)
    guard = IdempotencyGuard()

    signals = ExtractedSignals(asked_price=True, has_business_context=True)
    result = await apply_turn(
        lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
    )

    assert result.errors  # failure recorded, not raised
    assert lead.whatsapp_midcall_status.value == "failed"

    # A subsequent turn should be able to retry since the claim was rolled back.
    result2 = await apply_turn(
        lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
    )
    assert "whatsapp_midcall" in result2.actions_fired
    assert len(wa.sent_messages) == 1


@pytest.mark.asyncio
async def test_finalize_call_sends_followup_for_warm_lead():
    lead = LeadState(call_id="orch5", caller_phone="+919876543210", business_type="furniture")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()

    await apply_turn(
        lead, ExtractedSignals(timing_barrier="maybe next month", general_interest=True, has_business_context=True),
        agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard,
    )
    result = await finalize_call(lead, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard)

    assert "whatsapp_followup" in result.actions_fired
    assert len(wa.sent_messages) == 1
    assert "furniture" in wa.sent_messages[0]["text"]
    assert lead.conversation_status.value == "completed"


@pytest.mark.asyncio
async def test_finalize_call_sends_brochure_for_cold_lead():
    lead = LeadState(call_id="orch6", caller_phone="+919876543210")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()

    await apply_turn(
        lead, ExtractedSignals(just_browsing=True, has_business_context=False),
        agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard,
    )
    result = await finalize_call(lead, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard)

    assert "whatsapp_followup" in result.actions_fired
    assert "no pressure" in wa.sent_messages[0]["text"].lower()


@pytest.mark.asyncio
async def test_finalize_call_is_idempotent():
    lead = LeadState(call_id="orch7", caller_phone="+919876543210")
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()
    await apply_turn(
        lead, ExtractedSignals(just_browsing=True), agent_name="Shafiq", agent_phone="+91-1",
        whatsapp_client=wa, guard=guard,
    )
    await finalize_call(lead, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard)
    await finalize_call(lead, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard)
    assert len(wa.sent_messages) == 1
