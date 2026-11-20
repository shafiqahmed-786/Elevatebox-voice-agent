from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.schemas import CallbackRequest, IntentClassification, IntentResult, LeadState
from app.whatsapp.payload_builder import (
    build_cold_brochure_message,
    build_followup_whatsapp_message,
    build_midcall_whatsapp_message,
)

IST = ZoneInfo("Asia/Kolkata")


def _hot_lead() -> LeadState:
    return LeadState(
        call_id="call_1",
        business_type="clothing",
        product_count=200,
        budget_inr=70000,
        timeline="3 weeks",
        features=["Razorpay integration"],
        intent=IntentResult(classification=IntentClassification.HOT, confidence=0.9, signals=["asked pricing"]),
    )


def test_midcall_message_references_actual_captured_fields():
    msg = build_midcall_whatsapp_message(_hot_lead(), agent_name="Shafiq", agent_phone="+91-XXXXXXXXXX")
    assert "clothing" in msg
    assert "200" in msg
    assert "70,000" in msg
    assert "3 weeks" in msg
    assert "Razorpay" in msg
    assert "+91-XXXXXXXXXX" in msg
    assert "Shafiq" in msg


def test_midcall_message_omits_fields_that_were_never_captured():
    sparse = LeadState(call_id="call_2", business_type="jewellery")
    msg = build_midcall_whatsapp_message(sparse, agent_name="Shafiq", agent_phone="+91-XXXXXXXXXX")
    assert "jewellery" in msg
    # Must not claim a budget or timeline that was never actually stated.
    assert "Rs" not in msg
    assert "budget" not in msg.lower()


def test_two_different_leads_produce_meaningfully_different_messages():
    """This is effectively the anti-genericism test: run the same generator
    on two different leads and confirm the outputs actually differ,
    ie. content-derived rather than a fixed template with a name slotted in."""
    lead_a = LeadState(call_id="a", business_type="clothing", budget_inr=70000)
    lead_b = LeadState(call_id="b", business_type="furniture", budget_inr=250000)
    msg_a = build_midcall_whatsapp_message(lead_a, "Shafiq", "+91-1")
    msg_b = build_midcall_whatsapp_message(lead_b, "Shafiq", "+91-1")
    assert msg_a != msg_b
    assert "clothing" in msg_a and "clothing" not in msg_b
    assert "furniture" in msg_b and "furniture" not in msg_a


def test_followup_message_includes_callback_time_when_present():
    lead = _hot_lead()
    lead.callback = CallbackRequest(
        raw_phrase="tomorrow morning",
        interpreted_datetime=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
        interpretation_note="default morning slot",
        confidence=0.9,
    )
    msg = build_followup_whatsapp_message(lead, "Shafiq", "+91-XXXXXXXXXX")
    assert "10:00" in msg or "10:00 AM" in msg
    assert "Monday" in msg  # 24 Aug 2026 is a Monday


def test_followup_message_reuses_a_verbatim_key_quote():
    lead = _hot_lead()
    lead.key_quotes = ["I really need this live before the festival season"]
    msg = build_followup_whatsapp_message(lead, "Shafiq", "+91-XXXXXXXXXX")
    assert "I really need this live before the festival season" in msg


def test_followup_message_surfaces_barriers_gently():
    lead = LeadState(call_id="c", business_type="clothing", barriers=["budget is tight right now"])
    msg = build_followup_whatsapp_message(lead, "Shafiq", "+91-XXXXXXXXXX")
    assert "budget is tight right now" in msg
    assert "no pressure" in msg.lower()


def test_cold_message_is_soft_not_pushy():
    lead = LeadState(call_id="d")
    msg = build_cold_brochure_message(lead, "Shafiq", "+91-XXXXXXXXXX")
    assert "no pressure" in msg.lower()
    assert "+91-XXXXXXXXXX" in msg
