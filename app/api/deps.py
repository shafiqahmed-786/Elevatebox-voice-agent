"""
FastAPI dependencies. This is the ONE place that decides real-vs-mock for
each external provider, based purely on whether credentials are configured
-- so the same route code runs identically whether it's wired to the real
Meta/OmniDimension APIs or to the in-memory mocks used by tests and the
simulator. A deployment with real credentials gets real behaviour with no
code change; one without them still runs, end to end, against mocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.services.idempotency import IdempotencyGuard
from app.telephony.voice_provider_client import MockVoiceProviderClient, OmniDimensionClient, VoiceProviderClient
from app.whatsapp.client import MetaCloudAPIWhatsAppClient, MockWhatsAppClient, WhatsAppClient

# Single process-wide idempotency guard and mock stores, so state (and
# recorded mock sends) survives across requests within one running process
# -- this is what makes the mocks usable for a real demo session, not just
# single-call unit tests.
_guard = IdempotencyGuard()
_mock_whatsapp = MockWhatsAppClient()
_mock_voice = MockVoiceProviderClient()


def get_idempotency_guard() -> IdempotencyGuard:
    return _guard


def get_whatsapp_client(settings: Settings = Depends(get_settings)) -> WhatsAppClient:
    if settings.has_live_whatsapp:
        return MetaCloudAPIWhatsAppClient(settings.whatsapp_access_token, settings.whatsapp_phone_number_id)
    return _mock_whatsapp


def get_voice_client(settings: Settings = Depends(get_settings)) -> VoiceProviderClient:
    if settings.has_live_omnidimension:
        return OmniDimensionClient(
            settings.omnidimension_api_key, settings.omnidimension_agent_id, settings.omnidimension_from_number_id
        )
    return _mock_voice


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session
