import asyncio

import pytest

from app.models.schemas import ActionStatus, LeadState
from app.services.idempotency import (
    IdempotencyGuard,
    try_claim_callback,
    try_claim_followup_whatsapp,
    try_claim_midcall_whatsapp,
)


@pytest.mark.asyncio
async def test_second_midcall_whatsapp_claim_is_rejected():
    lead = LeadState(call_id="dup1")
    guard = IdempotencyGuard()

    first = await try_claim_midcall_whatsapp(lead, guard)
    second = await try_claim_midcall_whatsapp(lead, guard)

    assert first is True
    assert second is False
    assert lead.whatsapp_midcall_status == ActionStatus.SENT


@pytest.mark.asyncio
async def test_concurrent_midcall_claims_only_one_wins():
    """Simulates the real failure mode: the platform fires the trigger tool
    twice almost simultaneously (e.g. two conversation turns both see a HOT
    classification before the first send completes)."""
    lead = LeadState(call_id="dup2")
    guard = IdempotencyGuard()

    results = await asyncio.gather(
        try_claim_midcall_whatsapp(lead, guard),
        try_claim_midcall_whatsapp(lead, guard),
        try_claim_midcall_whatsapp(lead, guard),
    )
    assert sum(results) == 1  # exactly one caller got permission to send


@pytest.mark.asyncio
async def test_followup_and_midcall_claims_are_independent():
    lead = LeadState(call_id="dup3")
    guard = IdempotencyGuard()

    assert await try_claim_midcall_whatsapp(lead, guard) is True
    # Follow-up is a DIFFERENT action and must not be blocked by midcall
    # already having fired.
    assert await try_claim_followup_whatsapp(lead, guard) is True
    # But a second follow-up claim must be rejected.
    assert await try_claim_followup_whatsapp(lead, guard) is False


@pytest.mark.asyncio
async def test_duplicate_callback_with_no_existing_callback_is_allowed():
    lead = LeadState(call_id="dup4")
    guard = IdempotencyGuard()
    assert await try_claim_callback(lead, guard) is True


@pytest.mark.asyncio
async def test_second_callback_claim_rejected_once_one_is_scheduled():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import CallbackRequest

    lead = LeadState(call_id="dup5")
    guard = IdempotencyGuard()
    assert await try_claim_callback(lead, guard) is True

    lead.callback = CallbackRequest(
        raw_phrase="tomorrow morning",
        interpreted_datetime=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        interpretation_note="test",
        confidence=0.9,
        status="scheduled",
    )
    assert await try_claim_callback(lead, guard) is False


@pytest.mark.asyncio
async def test_cancelled_callback_allows_a_new_claim():
    """If the customer's earlier callback was cancelled/superseded, a new
    one must still be claimable -- idempotency should not permanently lock
    out legitimate re-scheduling."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import CallbackRequest

    lead = LeadState(call_id="dup6")
    guard = IdempotencyGuard()
    lead.callback = CallbackRequest(
        raw_phrase="tomorrow morning",
        interpreted_datetime=datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        interpretation_note="test",
        confidence=0.9,
        status="cancelled",
    )
    assert await try_claim_callback(lead, guard) is True
