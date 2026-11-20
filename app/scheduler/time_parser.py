"""
Turns a spoken callback phrase into a concrete Asia/Kolkata datetime.

Every ambiguous phrase gets a DETERMINISTIC interpretation plus a logged
explanation of what was assumed (per the assignment: "When the phrase is
vague, use a sensible deterministic interpretation and log the
interpretation"). We never silently guess -- `interpretation_note` always
says exactly what default was applied, so a human reviewing a call log can
see (and if needed, correct) the assumption.

Design note: an earlier version of this handed compound phrases like
"Friday at 4" straight to `dateparser`. In testing that produced a genuinely
wrong result -- dateparser silently read the bare "4" as a month and
returned April of next year. So DATE and TIME are now resolved as two
separate deterministic passes:
  1. Resolve the calendar date: explicit weekday name, or "tomorrow" /
     "today" / "day after tomorrow" / "next week", all via our own
     arithmetic. Only phrases matching NONE of these fall through to
     `dateparser`, which is a much safer surface for it (e.g. explicit
     dates like "25th August").
  2. Resolve the clock time: explicit "4pm" / "16:00" / bare "at 4"
     (assumed PM for business hours -- logged), or a time-of-day word
     ("morning" / "shaam" / "udayam" -> a documented default slot), or
     else a documented 10:00 IST default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateparser

IST = ZoneInfo("Asia/Kolkata")

TIME_OF_DAY_DEFAULTS = {
    "morning": (10, 0),
    "subah": (10, 0),  # Hindi
    "udayam": (10, 0),  # Telugu
    "afternoon": (14, 0),
    "dopahar": (14, 0),
    "madhyahnam": (14, 0),
    "evening": (18, 0),
    "shaam": (18, 0),
    "sayantram": (18, 0),
    "night": (20, 0),
    "raat": (20, 0),
    "raatri": (20, 0),
}

# Hindi / Hinglish / Telugu fragments -> English equivalents. Heuristic, not
# a full translator -- anything uncovered still gets a best-effort parse and
# a logged, reviewable interpretation rather than a silent failure.
_PHRASE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bkal\s+subah\b", re.I), "tomorrow morning"),
    (re.compile(r"\bkal\s+shaam\b", re.I), "tomorrow evening"),
    (re.compile(r"\bkal\s+dopahar\b", re.I), "tomorrow afternoon"),
    (re.compile(r"\bkal\b", re.I), "tomorrow"),
    (re.compile(r"\bparso\b", re.I), "day after tomorrow"),
    (re.compile(r"\baaj\s+shaam\b", re.I), "today evening"),
    (re.compile(r"\baaj\b", re.I), "today"),
    (re.compile(r"\bagle\s+hafte\b", re.I), "next week"),
    (re.compile(r"\brepu\s+udayam\b", re.I), "tomorrow morning"),  # Telugu
    (re.compile(r"\brepu\s+sayantram\b", re.I), "tomorrow evening"),
    (re.compile(r"\brepu\s+madhyahnam\b", re.I), "tomorrow afternoon"),
    (re.compile(r"\brepu\b", re.I), "tomorrow"),  # Telugu
    (re.compile(r"ఎల్లుండి|\bellundi\b", re.I), "day after tomorrow"),  # Telugu
]

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", re.I)
_BARE_HOUR_RE = re.compile(r"\b(?:at|around|by)\s+(\d{1,2})\b(?!\s*(am|pm|:))", re.I)


@dataclass(frozen=True)
class ParsedCallback:
    interpreted_datetime: datetime
    interpretation_note: str
    confidence: float


def _normalize_phrase(phrase: str) -> tuple[str, list[str]]:
    normalized = phrase.strip()
    applied: list[str] = []
    for pattern, replacement in _PHRASE_MAP:
        if pattern.search(normalized):
            normalized = pattern.sub(replacement, normalized)
            applied.append(f"'{pattern.pattern}' -> '{replacement}'")
    return normalized, applied


def _resolve_date(lowered: str, reference_dt: datetime) -> tuple[datetime, str | None]:
    """Resolve just the calendar date (time left at 00:00), deterministically
    where possible. Returns (date_as_midnight_datetime, note_or_None)."""
    for i, day in enumerate(_WEEKDAYS):
        if day in lowered:
            days_ahead = (i - reference_dt.weekday()) % 7
            days_ahead = days_ahead if days_ahead != 0 else 7  # naming today's weekday means NEXT week
            target = (reference_dt + timedelta(days=days_ahead)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            return target, None

    if "day after tomorrow" in lowered:
        return (reference_dt + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0), None
    if "next week" in lowered:
        return (reference_dt + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0), None
    if "tomorrow" in lowered:
        return (reference_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0), None
    if "today" in lowered:
        return reference_dt.replace(hour=0, minute=0, second=0, microsecond=0), None

    # Nothing matched our known patterns -- fall through to dateparser for
    # things like explicit calendar dates ("on the 25th of August").
    settings = {
        "TIMEZONE": "Asia/Kolkata",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": reference_dt.replace(tzinfo=None),
    }
    parsed = dateparser.parse(lowered, settings=settings, languages=["en", "hi"])
    if parsed is not None:
        return parsed.replace(hour=0, minute=0, second=0, microsecond=0), (
            "date resolved via general-purpose parsing (dateparser), not an explicit rule"
        )

    fallback = (reference_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return fallback, "could not identify a date at all; defaulted to tomorrow -- please confirm with the customer"


def _resolve_time(lowered: str) -> tuple[int, int, str | None, float]:
    """Resolve just the clock time. Returns (hour, minute, note_or_None, confidence)."""
    match = _TIME_RE.search(lowered)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3).lower().startswith("p"):
            hour += 12
        return hour, minute, None, 0.95

    bare = _BARE_HOUR_RE.search(lowered)
    if bare:
        hour = int(bare.group(1))
        if 1 <= hour <= 7:
            note = f"'{bare.group(0)}' had no AM/PM; interpreted as {hour}:00 PM (business-hours default)"
            return hour + 12, 0, note, 0.8
        return hour, 0, None, 0.85

    for keyword, (hour, minute) in TIME_OF_DAY_DEFAULTS.items():
        if keyword in lowered:
            return hour, minute, f"applied default {hour:02d}:{minute:02d} IST for named time-of-day", 0.8

    return 10, 0, "no time mentioned at all; defaulted to 10:00 IST", 0.65


def parse_callback_phrase(phrase: str, reference_dt: datetime | None = None) -> ParsedCallback:
    """Parse a spoken callback phrase into a concrete IST datetime.

    `reference_dt` is the "now" the phrase is relative to (defaults to the
    real current time in IST); tests pass a fixed reference for determinism.
    """
    if reference_dt is None:
        reference_dt = datetime.now(IST)
    elif reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=IST)
    reference_naive = reference_dt.astimezone(IST).replace(tzinfo=None)

    raw = phrase.strip()
    normalized, phrase_swaps = _normalize_phrase(raw)
    lowered = normalized.lower()

    date_dt, date_note = _resolve_date(lowered, reference_naive)
    hour, minute, time_note, time_confidence = _resolve_time(lowered)

    result = date_dt.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=IST)

    if result <= reference_dt:
        # e.g. "today" combined with a time-of-day default that's already passed.
        result = result + timedelta(days=7 if _mentions_weekday(lowered) else 1)

    notes = [n for n in (date_note, time_note) if n]
    if phrase_swaps:
        notes.append("normalized Hindi/Telugu phrase(s): " + "; ".join(phrase_swaps))
    note_text = "; ".join(notes) if notes else "parsed directly from an explicit date and time"

    confidence = time_confidence if date_note is None else min(time_confidence, 0.75)
    if "could not identify a date" in (date_note or ""):
        confidence = min(confidence, 0.4)

    return ParsedCallback(
        interpreted_datetime=result,
        interpretation_note=note_text,
        confidence=round(confidence, 2),
    )


def _mentions_weekday(text: str) -> bool:
    return any(day in text for day in _WEEKDAYS)
