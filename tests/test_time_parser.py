from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduler.time_parser import parse_callback_phrase
from tests.fixtures.sample_conversations import CALLBACK_PHRASES

IST = ZoneInfo("Asia/Kolkata")

# Fixed reference point so every test is deterministic regardless of when
# the suite actually runs: Saturday 22 Aug 2026, 12:00 IST.
REFERENCE = datetime(2026, 8, 22, 12, 0, tzinfo=IST)


def test_all_sample_phrases_parse_to_a_future_ist_datetime():
    for phrase in CALLBACK_PHRASES:
        result = parse_callback_phrase(phrase, reference_dt=REFERENCE)
        assert result.interpreted_datetime > REFERENCE, phrase
        assert result.interpreted_datetime.tzinfo is not None
        assert str(result.interpreted_datetime.tzinfo) in ("Asia/Kolkata",) or \
            result.interpreted_datetime.utcoffset().total_seconds() == 5.5 * 3600
        assert result.interpretation_note
        assert 0.0 < result.confidence <= 1.0


def test_tomorrow_morning_uses_default_morning_slot():
    result = parse_callback_phrase("tomorrow morning", reference_dt=REFERENCE)
    assert result.interpreted_datetime.date() == (REFERENCE.date().replace(day=23))
    assert result.interpreted_datetime.hour == 10


def test_friday_at_4_resolves_to_pm_not_am():
    result = parse_callback_phrase("Friday at 4", reference_dt=REFERENCE)
    # 22 Aug 2026 is a Saturday -> next Friday is 28 Aug 2026.
    assert result.interpreted_datetime.weekday() == 4  # Friday
    assert result.interpreted_datetime.hour == 16  # 4 PM, not 4 AM
    assert "PM" in result.interpretation_note or "pm" in result.interpretation_note.lower()


def test_next_tuesday_evening():
    result = parse_callback_phrase("next Tuesday evening", reference_dt=REFERENCE)
    assert result.interpreted_datetime.weekday() == 1  # Tuesday
    assert result.interpreted_datetime.hour == 18
    assert result.interpreted_datetime > REFERENCE


def test_hindi_kal_subah():
    result = parse_callback_phrase("kal subah call karna", reference_dt=REFERENCE)
    assert result.interpreted_datetime.date() == REFERENCE.date().replace(day=23)
    assert result.interpreted_datetime.hour == 10
    assert "normalized" in result.interpretation_note.lower()


def test_telugu_repu_udayam():
    result = parse_callback_phrase("repu udayam call cheyandi", reference_dt=REFERENCE)
    assert result.interpreted_datetime.date() == REFERENCE.date().replace(day=23)
    assert result.interpreted_datetime.hour == 10


def test_next_week_rolls_forward_a_week():
    result = parse_callback_phrase("call me next week", reference_dt=REFERENCE)
    assert (result.interpreted_datetime.date() - REFERENCE.date()).days >= 6


def test_unparseable_phrase_never_crashes_and_flags_low_confidence():
    result = parse_callback_phrase("whenever, you know, sometime", reference_dt=REFERENCE)
    assert result.interpreted_datetime > REFERENCE
    assert result.confidence <= 0.5
    assert "please confirm" in result.interpretation_note.lower() or "could not" in result.interpretation_note.lower()
