"""
Regression tests for the cumulative-signal classification bug found via
scripts/simulate_call.py: classify_lead() was being called with only the
CURRENT turn's ExtractedSignals, so a neutral/empty later turn silently
erased earlier HOT/WARM evidence and could regress the classification
(observed concretely: the warm_budget_barrier scenario went WARM -> COLD
on its third, unrelated turn). The fix is app.decision.classifier.merge_signals
plus app.services.call_orchestrator._apply_signals routing classification
through lead.cumulative_signals instead of the raw per-turn signals.

Each test below exercises the orchestrator across multiple real turns
(not just merge_signals in isolation) because the bug was specifically an
orchestration-layer bug -- merge_signals alone being correct wouldn't have
caught it if apply_turn still classified off the wrong object.
"""

from __future__ import annotations

import pytest

from app.decision.classifier import merge_signals
from app.models.schemas import ExtractedSignals, IntentClassification, LeadState
from app.services.call_orchestrator import apply_turn
from app.services.idempotency import IdempotencyGuard
from app.whatsapp.client import MockWhatsAppClient


async def _run_turns(lead: LeadState, turns: list[ExtractedSignals]) -> None:
    wa = MockWhatsAppClient()
    guard = IdempotencyGuard()
    for signals in turns:
        await apply_turn(
            lead, signals, agent_name="Shafiq", agent_phone="+91-1", whatsapp_client=wa, guard=guard
        )


# --- Scenario A: neutral second turn must not erase WARM evidence --------

@pytest.mark.asyncio
async def test_scenario_a_neutral_turn_does_not_erase_warm_evidence():
    lead = LeadState(call_id="regA", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(budget_barrier=True, general_interest=True, has_business_context=True),
        ExtractedSignals(),  # completely neutral/empty turn, e.g. "okay, sounds good"
    ])
    assert lead.intent.classification == IntentClassification.WARM
    assert "budget constraint" in lead.barriers


# --- Scenario B: HOT stays HOT across an additional confirming turn ------

@pytest.mark.asyncio
async def test_scenario_b_hot_plus_more_hot_evidence_stays_hot():
    lead = LeadState(call_id="regB", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(asked_price=True, has_business_context=True),
        ExtractedSignals(concrete_timeline="3 weeks", asked_start_timeline=True),
    ])
    assert lead.intent.classification == IntentClassification.HOT
    assert lead.timeline == "3 weeks"


# --- Scenario C: WARM evidence followed by a barrier -> still WARM,
# and the specific assignment barrier rule (barrier caps at WARM even with
# strong HOT signals) still holds across turns, not just within one. -------

@pytest.mark.asyncio
async def test_scenario_c_warm_then_barrier_follows_assignment_barrier_rule():
    lead = LeadState(call_id="regC", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(asked_price=True, concrete_budget_inr=200000, has_business_context=True),  # HOT on its own
        ExtractedSignals(approval_barrier="wife"),  # barrier arrives on a LATER turn
    ])
    # Per the assignment's own WARM definition, a real barrier caps the
    # result even though turn 1 alone would have cleared the HOT threshold.
    assert lead.intent.classification == IntentClassification.WARM
    assert any("wife" in s for s in lead.intent.signals)


# --- Scenario D: an empty turn anywhere in the sequence loses nothing ----

@pytest.mark.asyncio
async def test_scenario_d_empty_turn_loses_no_accumulated_evidence():
    lead = LeadState(call_id="regD", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(concrete_budget_inr=50000, has_business_context=True),
        ExtractedSignals(),  # empty
        ExtractedSignals(concrete_timeline="1 month"),
    ])
    assert lead.budget_inr == 50000  # survived the empty turn in between
    assert lead.timeline == "1 month"
    assert lead.cumulative_signals.concrete_budget_inr == 50000


# --- Scenario E: repeated list values across turns don't duplicate -------

@pytest.mark.asyncio
async def test_scenario_e_repeated_feature_mentions_do_not_duplicate():
    lead = LeadState(call_id="regE", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(specific_feature_questions=["Razorpay"], has_business_context=True),
        ExtractedSignals(specific_feature_questions=["Razorpay"]),  # customer says it again
        ExtractedSignals(specific_feature_questions=["Razorpay", "inventory management"]),
    ])
    assert lead.features == ["Razorpay", "inventory management"]
    assert lead.cumulative_signals.specific_feature_questions == ["Razorpay", "inventory management"]


# --- Scenario F: a later, different scalar value replaces the earlier one -

@pytest.mark.asyncio
async def test_scenario_f_revised_budget_on_a_later_turn_replaces_earlier_value():
    lead = LeadState(call_id="regF", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(concrete_budget_inr=50000, has_business_context=True),
        ExtractedSignals(concrete_budget_inr=80000),  # "actually we can stretch to 80k"
    ])
    assert lead.budget_inr == 80000
    assert lead.cumulative_signals.concrete_budget_inr == 80000


# --- Direct unit tests of merge_signals() itself, isolated from the
# orchestrator, for fast/precise coverage of the merge semantics table. ----

def test_merge_signals_booleans_accumulate_with_or():
    a = ExtractedSignals(asked_price=True)
    b = ExtractedSignals(asked_start_timeline=True)
    merged = merge_signals(a, b)
    assert merged.asked_price is True  # preserved from `a`
    assert merged.asked_start_timeline is True  # added from `b`


def test_merge_signals_empty_latest_turn_preserves_everything():
    a = ExtractedSignals(asked_price=True, budget_barrier=True, concrete_budget_inr=70000)
    merged = merge_signals(a, ExtractedSignals())
    assert merged == a


def test_merge_signals_scalar_latest_meaningful_value_wins():
    a = ExtractedSignals(concrete_timeline="3 weeks")
    b = ExtractedSignals(concrete_timeline="")  # not actually provided this turn
    merged = merge_signals(a, b)
    assert merged.concrete_timeline == "3 weeks"  # empty string from b does NOT overwrite

    c = ExtractedSignals(concrete_timeline="next month")
    merged2 = merge_signals(a, c)
    assert merged2.concrete_timeline == "next month"  # genuine new value DOES overwrite


def test_merge_signals_lists_union_without_duplicates():
    a = ExtractedSignals(specific_feature_questions=["Razorpay"])
    b = ExtractedSignals(specific_feature_questions=["Razorpay", "COD"])
    merged = merge_signals(a, b)
    assert merged.specific_feature_questions == ["Razorpay", "COD"]


def test_merge_signals_is_pure_does_not_mutate_inputs():
    a = ExtractedSignals(asked_price=True)
    b = ExtractedSignals(budget_barrier=True)
    merge_signals(a, b)
    assert a.budget_barrier is False  # `a` itself was not mutated
    assert b.asked_price is False  # neither was `b`


# --- End-to-end proof that the previously-dropped discovery fields now
# actually reach LeadState through the real orchestrator, not just
# ExtractedSignals in isolation. -------------------------------------------

@pytest.mark.asyncio
async def test_business_type_and_decision_maker_reach_lead_state_via_orchestrator():
    lead = LeadState(call_id="fields1", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(
            business_type="clothing",
            sells_online_currently=False,
            product_count=200,
            decision_maker="self",
            concrete_timeline="3 weeks",
            has_business_context=True,
        ),
    ])
    assert lead.business_type == "clothing"
    assert lead.sells_online_currently is False
    assert lead.product_count == 200
    assert lead.decision_maker == "self"
    assert lead.timeline == "3 weeks"


@pytest.mark.asyncio
async def test_decision_maker_answered_later_is_not_lost():
    """The decision-maker question is often answered a turn or two after
    business context, not in the same breath -- confirms it isn't reset by
    the intervening turn."""
    lead = LeadState(call_id="fields2", caller_phone="+91900000000")
    await _run_turns(lead, [
        ExtractedSignals(business_type="furniture", has_business_context=True),
        ExtractedSignals(concrete_budget_inr=150000),
        ExtractedSignals(decision_maker="co-owned with my sister"),
    ])
    assert lead.business_type == "furniture"  # survived two unrelated turns
    assert lead.budget_inr == 150000
    assert lead.decision_maker == "co-owned with my sister"
