"""
The single tool schema that turns raw conversation into ExtractedSignals.

This same JSON schema is used in two places, deliberately kept as ONE
source of truth:

1. Configured as a "Custom API" agent action inside OmniDimension, so the
   in-call LLM calls it naturally whenever the caller says something
   qualification-relevant (OmniDimension docs: "Custom API turns any REST
   endpoint into an agent action").
2. Passed as an Anthropic `tools` definition when we run our own
   extraction/classification pass server-side (app/conversation/extraction.py),
   used for the evaluation harness and as a fallback if the platform-side
   extraction under-fires.

Keeping both on one schema is what stops "the LLM being responsible for
everything" from silently drifting into two different, undocumented shapes.
"""

from __future__ import annotations

UPDATE_LEAD_SIGNALS_TOOL = {
    "name": "update_lead_signals",
    "description": (
        "Record qualification signals extracted from what the customer just said. "
        "Call this after EVERY customer turn that adds new information, even if "
        "the customer was vague or indirect. Only set fields you actually heard "
        "evidence for -- never guess a budget or timeline that wasn't stated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "business_type": {"type": "string", "description": "What the customer sells, e.g. 'clothing', 'handmade jewellery'."},
            "sells_online_currently": {"type": "boolean"},
            "product_count": {"type": "integer"},
            "budget_inr": {"type": "integer", "description": "Budget in INR if a number was stated or clearly implied."},
            "timeline": {"type": "string", "description": "Any timeline phrase stated, verbatim-ish, e.g. '3 weeks', 'by next month'."},
            "features": {"type": "array", "items": {"type": "string"}, "description": "Specific features/integrations asked about, e.g. 'Razorpay', 'inventory management'."},
            "decision_maker": {"type": "string", "description": "'self' if they decide alone, otherwise who else is involved."},
            "asked_price": {"type": "boolean"},
            "asked_start_timeline": {"type": "boolean", "description": "True if they asked how soon work could start."},
            "explicit_next_step_request": {"type": "boolean", "description": "True for things like 'send me the details' or 'let's go ahead'."},
            "specific_feature_questions": {"type": "array", "items": {"type": "string"}},
            "budget_barrier": {"type": "boolean", "description": "True if they signalled budget is tight/an issue right now."},
            "approval_barrier": {"type": "string", "description": "Who else needs to approve, if mentioned, e.g. 'brother', 'business partner'."},
            "timing_barrier": {"type": "string", "description": "Phrase indicating they're not ready yet, e.g. 'maybe next month'."},
            "just_browsing": {"type": "boolean"},
            "general_interest": {"type": "boolean", "description": "True for polite/soft interest with no concrete details yet."},
            "has_business_context": {"type": "boolean", "description": "True once we know what they actually sell or plan to sell."},
            "key_quote": {"type": "string", "description": "A short verbatim line worth reusing in the follow-up message, if this turn had one."},
        },
        "required": [],
    },
}

SCHEDULE_CALLBACK_TOOL = {
    "name": "schedule_callback",
    "description": (
        "Call this the moment the customer names any callback time, in any "
        "language or mix of languages -- 'tomorrow morning', 'kal subah', "
        "'Friday around 4', 'next week', etc. Pass the phrase mostly as said."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "raw_phrase": {"type": "string", "description": "The callback time as the customer said it."},
        },
        "required": ["raw_phrase"],
    },
}

TRIGGER_WHATSAPP_TOOL = {
    "name": "trigger_midcall_whatsapp",
    "description": (
        "Call this AS SOON AS the lead looks HOT -- do not wait for the call "
        "to end. Safe to call more than once; the backend de-duplicates."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

ALL_TOOLS = [UPDATE_LEAD_SIGNALS_TOOL, SCHEDULE_CALLBACK_TOOL, TRIGGER_WHATSAPP_TOOL]
