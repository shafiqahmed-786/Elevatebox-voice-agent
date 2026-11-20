"""
Turns raw tool-call input (from OmniDimension's Custom API action, or from
our own Claude-based extraction fallback) into a validated ExtractedSignals.

This module exists because of one explicit requirement: "The system must
never crash because an LLM returns malformed data." An LLM tool call can
legally send us almost anything -- wrong types, extra keys, missing keys, a
string where a bool was expected, or a budget written as "50k" instead of
50000. None of that should ever propagate an exception up into a live call.

Everything here is defensive: bad/missing fields are dropped (and logged),
never allowed to crash the request or silently corrupt state.
"""

from __future__ import annotations

import logging
import re

from pydantic import ValidationError

from app.models.schemas import ExtractedSignals

logger = logging.getLogger("elevatebox.extraction")

_NUMBER_WITH_SUFFIX = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(k|thousand|l|lakh|lac)?\s*$", re.I)
_SUFFIX_MULTIPLIER = {"k": 1_000, "thousand": 1_000, "l": 100_000, "lakh": 100_000, "lac": 100_000}


def coerce_budget_to_inr(raw: object) -> int | None:
    """Best-effort coercion of a caller-style budget value ('50k', '1.5 lakh',
    70000, '70000') into a plain integer. Returns None (never raises) if it
    can't confidently parse -- a missing budget is fine, a wrong one is not."""
    if raw is None:
        return None
    if isinstance(raw, bool):  # bool is a subclass of int in Python -- guard explicitly
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        match = _NUMBER_WITH_SUFFIX.match(raw.replace(",", "").replace("₹", "").replace("Rs", "").replace("rs", ""))
        if not match:
            return None
        value = float(match.group(1))
        suffix = (match.group(2) or "").lower()
        multiplier = _SUFFIX_MULTIPLIER.get(suffix, 1)
        return int(value * multiplier)
    return None


def safe_parse_extracted_signals(raw: dict, *, call_id: str = "") -> ExtractedSignals:
    """
    Validate a raw dict (typically straight from an LLM tool call) into an
    ExtractedSignals instance. Never raises -- on any problem, drops the
    offending field(s) and returns the best signal set it could build,
    logging what was dropped and why so it's visible in the per-call log.
    """
    if not isinstance(raw, dict):
        logger.warning("call=%s extraction payload was not a dict (got %s); ignoring", call_id, type(raw))
        return ExtractedSignals()

    cleaned: dict = dict(raw)

    if "budget_inr" in cleaned:
        coerced = coerce_budget_to_inr(cleaned.get("budget_inr"))
        if coerced is None and cleaned.get("budget_inr") is not None:
            logger.warning(
                "call=%s dropped unparseable budget_inr=%r", call_id, cleaned.get("budget_inr")
            )
        cleaned["budget_inr"] = coerced

    if "concrete_budget_inr" in cleaned:
        coerced = coerce_budget_to_inr(cleaned.get("concrete_budget_inr"))
        cleaned["concrete_budget_inr"] = coerced

    # Support both a plain "budget_inr" (matches the tool schema exposed to
    # the voice platform) and "concrete_budget_inr" (matches ExtractedSignals'
    # own field name) so extraction stays forgiving about which name the
    # caller used.
    if "budget_inr" in cleaned and "concrete_budget_inr" not in cleaned:
        cleaned["concrete_budget_inr"] = cleaned.pop("budget_inr")

    for list_field in ("features", "specific_feature_questions"):
        if list_field in cleaned and not isinstance(cleaned[list_field], list):
            logger.warning(
                "call=%s dropped non-list %s=%r", call_id, list_field, cleaned[list_field]
            )
            cleaned[list_field] = []

    if "features" in cleaned and "specific_feature_questions" not in cleaned:
        cleaned["specific_feature_questions"] = cleaned.pop("features")

    # "timeline" is the name used in the tool schema exposed to the voice
    # platform (see app/decision/signal_schema.py); ExtractedSignals calls
    # it "concrete_timeline" to make clear it only holds an actually-stated
    # value, never an inference. Same rename pattern as budget_inr/features
    # above -- without it, a perfectly well-formed tool call naming the
    # field "timeline" would silently vanish as an "unrecognized field".
    if "timeline" in cleaned and "concrete_timeline" not in cleaned:
        cleaned["concrete_timeline"] = cleaned.pop("timeline")

    # key_quote (singular, from the tool schema) isn't a field on
    # ExtractedSignals itself -- it's merged into LeadState.key_quotes by the
    # orchestrator, not here. Drop it quietly rather than letting Pydantic's
    # `extra="ignore"` hide it silently from the log.
    dropped_extra = [
        k for k in cleaned
        if k not in ExtractedSignals.model_fields and k != "key_quote"
    ]
    if dropped_extra:
        logger.info("call=%s ignoring unrecognized extraction fields: %s", call_id, dropped_extra)

    try:
        return ExtractedSignals.model_validate(cleaned)
    except ValidationError as exc:
        logger.warning("call=%s extraction payload failed validation, retrying field-by-field: %s", call_id, exc)
        return _salvage_field_by_field(cleaned, call_id=call_id)


def _salvage_field_by_field(cleaned: dict, *, call_id: str) -> ExtractedSignals:
    """Last-resort path: if the whole payload fails validation together
    (e.g. one field has a wildly wrong type), build the signal set field by
    field, keeping everything that's individually valid and dropping only
    the field(s) that aren't -- rather than throwing away an entire turn's
    worth of correctly-extracted signals over one bad field."""
    salvaged: dict = {}
    for field_name in ExtractedSignals.model_fields:
        if field_name not in cleaned:
            continue
        try:
            salvaged[field_name] = cleaned[field_name]
            ExtractedSignals.model_validate(salvaged)
        except ValidationError:
            logger.warning("call=%s dropped invalid field %s=%r", call_id, field_name, cleaned[field_name])
            salvaged.pop(field_name, None)
    return ExtractedSignals.model_validate(salvaged)
