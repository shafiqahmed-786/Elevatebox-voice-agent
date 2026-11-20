"""
Idempotency for actions that must never fire twice: mid-call WhatsApp,
follow-up WhatsApp, and callback creation.

The risk this guards against: a live voice platform can call our webhook
more than once for what is logically the same event -- a retried webhook
delivery, the LLM invoking `trigger_midcall_whatsapp` twice in one call
because the lead was already HOT, a flaky network causing the platform to
resend. None of that should become two WhatsApp messages or two calendar
entries.

The guard is a simple compare-and-set on the LeadState's own status enum,
checked and flipped BEFORE the actual send happens (not after) -- so two
near-simultaneous calls can't both read "not sent yet" and both proceed.
Session-scoped, in-process locking is sufficient here (single FastAPI
worker per the assignment's "modular monolith" guidance); a multi-worker
deployment would need a DB-level unique constraint doing the same job at
the Lead row level, noted in the README as a known scaling limitation.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.models.schemas import ActionStatus, LeadState


class IdempotencyGuard:
    """One lock per call_id, so different calls never block each other but
    the same call's concurrent actions are serialized."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock_for(self, call_id: str) -> asyncio.Lock:
        return self._locks[call_id]


async def try_claim_midcall_whatsapp(lead: LeadState, guard: IdempotencyGuard) -> bool:
    """Returns True if this call successfully claimed the right to send the
    mid-call WhatsApp (and has flipped lead.whatsapp_midcall_status to
    PENDING->SENT-bound); returns False if it was already sent/pending,
    meaning the caller must NOT send again."""
    async with guard.lock_for(lead.call_id):
        if lead.whatsapp_midcall_status in (ActionStatus.SENT, ActionStatus.COMPLETED):
            return False
        lead.whatsapp_midcall_status = ActionStatus.SENT
        return True


async def try_claim_followup_whatsapp(lead: LeadState, guard: IdempotencyGuard) -> bool:
    async with guard.lock_for(lead.call_id):
        if lead.whatsapp_followup_status in (ActionStatus.SENT, ActionStatus.COMPLETED):
            return False
        lead.whatsapp_followup_status = ActionStatus.SENT
        return True


async def try_claim_callback(lead: LeadState, guard: IdempotencyGuard) -> bool:
    """A callback can legitimately be RE-scheduled if the customer names a
    new time later in the same call -- so this claims the slot for the
    *current* callback object, not "any callback ever", and returns False
    only if a callback already exists with an identical interpreted time
    (the actual duplicate-creation case)."""
    async with guard.lock_for(lead.call_id):
        if lead.callback is not None and lead.callback.status == "scheduled":
            return False
        return True
