"""
The one place the Anthropic API is actually called from our own backend.

Two jobs, both off the latency-critical path in a real OmniDimension-hosted
call (there, OmniDimension's own configured LLM handles turn-by-turn
conversation and calls our tools directly -- see app/decision/signal_schema.py):

  1. `extract_signals_from_transcript` -- used by scripts/simulate_call.py
     to drive the local simulation end-to-end from a plain-text transcript,
     and available as a server-side fallback extraction pass.
  2. `polish_followup_message` -- an optional rewrite of the deterministic
     template from app/whatsapp/payload_builder.py into looser prose.
     Never required: if this fails or ANTHROPIC_API_KEY isn't set, the
     deterministic template IS the message, unchanged. This satisfies the
     assignment's own "LLM failure" item in the failure-handling list --
     there is no code path where an LLM outage blocks the WhatsApp send.

Not exercised against the live Anthropic API in this environment: no
ANTHROPIC_API_KEY is available in the build sandbox. Written against the
current Messages API tool-use shape (model, max_tokens, system, messages,
tools -> tool_use content blocks).
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.conversation.extraction import safe_parse_extracted_signals
from app.decision.signal_schema import UPDATE_LEAD_SIGNALS_TOOL
from app.models.schemas import ExtractedSignals

logger = logging.getLogger("elevatebox.conversation")


async def extract_signals_from_transcript(transcript: str, *, call_id: str = "") -> ExtractedSignals:
    """
    Runs the full transcript of a (simulated or real) call through Claude
    with the `update_lead_signals` tool forced, and returns validated
    signals. Used by the simulation script so it exercises the SAME
    extraction contract a live call would use, not a separate code path.
    """
    settings = get_settings()
    if not settings.has_live_llm:
        logger.warning(
            "call=%s ANTHROPIC_API_KEY not set; skipping live extraction, returning empty signals. "
            "Configure it or use scripts/simulate_call.py --offline for a fully local run.",
            call_id,
        )
        return ExtractedSignals()

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.extraction_model,
            max_tokens=1024,
            system=(
                "You extract structured qualification signals from a sales call transcript. "
                "Call update_lead_signals exactly once with everything you can confidently infer "
                "from the WHOLE transcript below. Only set fields you have real evidence for."
            ),
            messages=[{"role": "user", "content": transcript}],
            tools=[UPDATE_LEAD_SIGNALS_TOOL],
            tool_choice={"type": "tool", "name": "update_lead_signals"},
        )
    except Exception as exc:  # noqa: BLE001 -- any provider/network failure must degrade, never crash the call
        logger.error("call=%s extraction LLM call failed (%s); returning empty signals", call_id, exc.__class__.__name__)
        return ExtractedSignals()

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "update_lead_signals":
            return safe_parse_extracted_signals(block.input, call_id=call_id)

    logger.warning("call=%s extraction response had no tool_use block; returning empty signals", call_id)
    return ExtractedSignals()


async def polish_followup_message(draft: str, transcript_excerpt: str, *, call_id: str = "") -> str:
    """Best-effort rewrite of the deterministic draft into looser prose.
    ALWAYS falls back to returning `draft` unchanged on any failure --
    this function is not allowed to be a reason the WhatsApp send doesn't
    happen or is delayed past the call ending."""
    settings = get_settings()
    if not settings.has_live_llm:
        return draft

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.extraction_model,
            max_tokens=400,
            system=(
                "Rewrite the given WhatsApp draft to sound like a real person typed it right after a "
                "sales call -- warm, brief, natural. Keep every specific fact (numbers, features, "
                "names, times) exactly as given. Do not add any claim that isn't already in the draft. "
                "Return only the rewritten message, nothing else."
            ),
            messages=[{
                "role": "user",
                "content": f"Relevant transcript excerpt:\n{transcript_excerpt}\n\nDraft to rewrite:\n{draft}",
            }],
        )
        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        polished = "".join(text_blocks).strip()
        return polished or draft
    except Exception as exc:  # noqa: BLE001
        logger.warning("call=%s follow-up polish failed (%s); using deterministic draft unchanged", call_id, exc.__class__.__name__)
        return draft
