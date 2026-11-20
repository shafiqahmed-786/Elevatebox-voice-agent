#!/usr/bin/env python3
"""
Runs a complete, realistic call through the REAL production pipeline --
extraction contract, merge logic, classifier, idempotency guard, message
generation -- with no external credentials and no network calls. This is
not a separate demo path: it calls exactly the same
app.services.call_orchestrator.apply_turn / finalize_call functions the
live webhook handlers call.

Two modes:
  --offline (default)  Turn-by-turn signals are hand-written per scenario
                        below (no LLM call at all) -- runs anywhere,
                        instantly, with zero setup. This is what CI / a
                        fresh clone / an evaluator with no API keys runs.
  --llm                 Each scenario's full transcript is instead run
                        through Claude via app.conversation.engine to
                        extract signals for real, exercising the actual
                        extraction call. Requires ANTHROPIC_API_KEY.

Usage:
    python scripts/simulate_call.py                 # all scenarios, offline
    python scripts/simulate_call.py --scenario hot   # just one
    python scripts/simulate_call.py --llm            # use real Claude extraction
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.schemas import ExtractedSignals, LeadState  # noqa: E402
from app.scheduler.callback_service import InvalidCallbackError, schedule_callback_from_phrase  # noqa: E402
from app.services.call_orchestrator import apply_turn, finalize_call  # noqa: E402
from app.services.idempotency import IdempotencyGuard  # noqa: E402
from app.telephony.voice_provider_client import MockVoiceProviderClient  # noqa: E402
from app.whatsapp.client import MockWhatsAppClient  # noqa: E402

AGENT_NAME = "Shafiq"
AGENT_PHONE = "+91-XXXXXXXXXX"


# Each scenario is a list of (caller_line, ExtractedSignals, key_quote,
# callback_phrase) tuples standing in for what a live call's turn-by-turn
# tool calls would produce. callback_phrase is None for turns that don't
# name a callback time; when set, it's run through the REAL
# schedule_callback_from_phrase(), exercising the same parser tested in
# tests/test_time_parser.py, not a simulation-only shortcut.
SCENARIOS: dict[str, list[tuple[str, ExtractedSignals, str | None, str | None]]] = {
    "hot": [
        ("I run a clothing shop, thinking of finally taking it online.",
         ExtractedSignals(business_type="clothing", has_business_context=True), None, None),
        ("We've got around 200 products. Budget mera around 70 thousand hai and mujhe Razorpay integration chahiye.",
         ExtractedSignals(product_count=200, concrete_budget_inr=70000, specific_feature_questions=["Razorpay"], has_business_context=True),
         "Budget mera around 70 thousand hai and mujhe Razorpay integration chahiye", None),
        ("Honestly if it can be live in 3 weeks that would be perfect -- how soon can you actually start?",
         ExtractedSignals(concrete_timeline="3 weeks", asked_start_timeline=True, has_business_context=True),
         "if it can be live in 3 weeks that would be perfect", None),
    ],
    "warm_budget_barrier": [
        ("I sell handmade jewellery, mostly through Instagram right now.",
         ExtractedSignals(business_type="handmade jewellery", sells_online_currently=True, has_business_context=True), None, None),
        ("I'd love a proper website honestly, but budget abhi thoda tight hai after the festival season.",
         ExtractedSignals(budget_barrier=True, general_interest=True, has_business_context=True),
         "budget abhi thoda tight hai after the festival season", None),
        ("Call me next week, maybe things will be clearer by then.",
         ExtractedSignals(), None, "next week"),
    ],
    "warm_approval_barrier": [
        ("We run a small electronics store, two branches.",
         ExtractedSignals(business_type="electronics", has_business_context=True), None, None),
        ("Sounds good honestly -- but my brother handles all the tech decisions, I'd need to loop him in.",
         ExtractedSignals(approval_barrier="brother", general_interest=True, has_business_context=True),
         "my brother handles all the tech decisions, I'd need to loop him in", None),
        ("Kal subah call kar lena, main usse baat kar lunga tab tak.",
         ExtractedSignals(), None, "kal subah"),
    ],
    "cold": [
        ("Not really sure, just saw an ad and got curious I guess.",
         ExtractedSignals(just_browsing=True, has_business_context=False), None, None),
        ("Yeah just checking options for now, nothing concrete.",
         ExtractedSignals(just_browsing=True), "just checking options for now, nothing concrete", None),
    ],
}


async def run_scenario(name: str, turns: list[tuple[str, ExtractedSignals, str | None, str | None]], use_llm: bool) -> dict:
    print(f"\n{'=' * 70}\nSCENARIO: {name}\n{'=' * 70}")
    lead = LeadState(call_id=f"sim_{name}", caller_phone="+919999999999")
    wa = MockWhatsAppClient()
    voice = MockVoiceProviderClient()
    guard = IdempotencyGuard()

    for i, (caller_line, hand_signals, key_quote, callback_phrase) in enumerate(turns, start=1):
        print(f"\n[turn {i}] Caller: {caller_line}")

        if use_llm:
            from app.conversation.engine import extract_signals_from_transcript

            signals = await extract_signals_from_transcript(caller_line, call_id=lead.call_id)
            print(f"          (extracted via live Claude call: {signals.model_dump(exclude_defaults=True)})")
        else:
            signals = hand_signals

        result = await apply_turn(
            lead, signals, agent_name=AGENT_NAME, agent_phone=AGENT_PHONE,
            whatsapp_client=wa, guard=guard, key_quote=key_quote,
        )
        print(f"          -> classification: {lead.intent.classification.value} "
              f"(confidence {lead.intent.confidence}, signals: {lead.intent.signals})")
        if result.actions_fired:
            print(f"          -> ACTIONS FIRED: {result.actions_fired}")

        if callback_phrase:
            try:
                callback = await schedule_callback_from_phrase(lead, callback_phrase, guard)
                print(f"          -> CALLBACK SCHEDULED: '{callback_phrase}' -> "
                      f"{callback.interpreted_datetime.strftime('%a %d %b %Y, %I:%M %p IST')} "
                      f"(confidence {callback.confidence}; {callback.interpretation_note})")
            except InvalidCallbackError as exc:
                print(f"          -> CALLBACK REJECTED: {exc}")

    final = await finalize_call(lead, agent_name=AGENT_NAME, agent_phone=AGENT_PHONE, whatsapp_client=wa, guard=guard)
    print(f"\n[call ended] final actions this step: {final.actions_fired}")

    print("\n--- WhatsApp messages actually sent (via MockWhatsAppClient) ---")
    for i, msg in enumerate(wa.sent_messages, start=1):
        print(f"\n  Message {i} (to {msg['to']}):")
        print("  " + msg["text"].replace("\n", "\n  "))

    print("\n--- Final structured lead state ---")
    print(json.dumps(lead.as_example_dict(), indent=2, default=str))

    return {
        "scenario": name,
        "final_classification": lead.intent.classification.value if lead.intent else None,
        "whatsapp_messages_sent": len(wa.sent_messages),
        "callback_scheduled": lead.callback is not None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=list(SCENARIOS) + ["all"], default="all")
    parser.add_argument("--llm", action="store_true", help="use real Claude extraction instead of hand-written signals")
    args = parser.parse_args()

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    summary = []
    for name in names:
        summary.append(await run_scenario(name, SCENARIOS[name], use_llm=args.llm))

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    for row in summary:
        print(f"  {row['scenario']:<24} classification={row['final_classification']:<5} "
              f"whatsapp_sent={row['whatsapp_messages_sent']} callback={row['callback_scheduled']}")


if __name__ == "__main__":
    asyncio.run(main())
