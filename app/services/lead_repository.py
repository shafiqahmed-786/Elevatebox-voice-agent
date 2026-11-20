"""
Bridges LeadState (the Pydantic model everything else works with) and the
Lead SQLAlchemy row (JSONB `state_json` column). Kept as its own thin
layer so nothing else in the codebase needs to know the persistence
representation -- business logic reads and writes LeadState objects only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Lead
from app.models.schemas import LeadState


async def get_lead_state(session: AsyncSession, call_id: str) -> LeadState | None:
    row = await session.get(Lead, call_id)
    if row is None:
        return None
    return LeadState.model_validate(row.state_json)


async def save_lead_state(session: AsyncSession, lead: LeadState) -> None:
    lead.updated_at = datetime.now(timezone.utc)
    row = await session.get(Lead, lead.call_id)
    payload = lead.model_dump(mode="json")
    if row is None:
        row = Lead(
            id=lead.call_id,
            call_id=lead.call_id,
            phone=lead.caller_phone or "",
            state_json=payload,
        )
        session.add(row)
    else:
        row.state_json = payload
    row.classification = lead.intent.classification.value if lead.intent else None
    row.confidence = lead.intent.confidence if lead.intent else None
    row.whatsapp_midcall_status = lead.whatsapp_midcall_status.value
    row.whatsapp_followup_status = lead.whatsapp_followup_status.value
    await session.commit()


async def list_leads_with_due_callbacks(session: AsyncSession, now_iso: str) -> list[LeadState]:
    result = await session.execute(select(Lead))
    leads = [LeadState.model_validate(row.state_json) for row in result.scalars().all()]
    return [
        lead for lead in leads
        if lead.callback is not None
        and lead.callback.status == "scheduled"
        and lead.callback.interpreted_datetime.isoformat() <= now_iso
    ]
