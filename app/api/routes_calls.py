from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_voice_client
from app.config import Settings, get_settings
from app.models.schemas import LeadState
from app.services.lead_repository import get_lead_state, save_lead_state
from app.telephony.voice_provider_client import VoiceProviderClient

logger = logging.getLogger("elevatebox.api.calls")
router = APIRouter(prefix="/calls", tags=["calls"])


class TriggerCallRequest(BaseModel):
    phone_number: str | None = None  # defaults to the assignment's evaluator number if omitted


class TriggerCallResponse(BaseModel):
    call_id: str
    provider_call_id: str | None
    dispatched: bool
    to_phone: str
    detail: str | None = None


@router.post("/trigger", response_model=TriggerCallResponse)
async def trigger_call(
    body: TriggerCallRequest,
    voice_client: VoiceProviderClient = Depends(get_voice_client),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TriggerCallResponse:
    to_phone = body.phone_number or settings.evaluator_phone_e164
    call_id = f"call_{uuid.uuid4().hex[:12]}"

    result = await voice_client.dispatch_call(
        to_phone_e164=to_phone,
        call_context={"call_id": call_id, "reason": "outbound_sales"},
    )

    now = datetime.now(timezone.utc)
    lead = LeadState(call_id=call_id, caller_phone=to_phone, created_at=now, updated_at=now)
    await save_lead_state(session, lead)

    if not result.success:
        logger.error("call=%s dispatch failed: %s", call_id, result.error)
        return TriggerCallResponse(
            call_id=call_id, provider_call_id=None, dispatched=False, to_phone=to_phone, detail=result.error
        )

    logger.info("call=%s dispatched to %s, provider_call_id=%s", call_id, to_phone, result.provider_call_id)
    return TriggerCallResponse(
        call_id=call_id, provider_call_id=result.provider_call_id, dispatched=True, to_phone=to_phone
    )


@router.get("/{call_id}")
async def get_call(call_id: str, session: AsyncSession = Depends(get_db_session)) -> dict:
    lead = await get_lead_state(session, call_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="call not found")
    return lead.model_dump(mode="json")
