"""
Outbound call dispatch, behind a Protocol, same pattern as the WhatsApp
client. `OmniDimensionClient.dispatch_call` is written against OmniDimension's
documented dispatch endpoint (confirmed via their API reference: POST
https://backend.omnidim.io/api/v1/calls/dispatch, bearer auth, JSON body
with agent_id/to_number/from_number_id/call_context) -- not exercised
against the live API here, since api.omnidim.io is outside this sandbox's
network allowlist and no API key was available anyway.

`MockVoiceProviderClient` is what scripts/simulate_call.py actually calls,
so "dispatch a call" is a code path that really runs, just against a stub
instead of the real telephony network.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

import httpx

logger = logging.getLogger("elevatebox.telephony")

OMNIDIMENSION_DISPATCH_URL = "https://backend.omnidim.io/api/v1/calls/dispatch"


@dataclass(frozen=True)
class DispatchResult:
    success: bool
    provider_call_id: str | None
    error: str | None = None


class VoiceProviderClient(Protocol):
    async def dispatch_call(
        self, *, to_phone_e164: str, call_context: dict
    ) -> DispatchResult: ...


class OmniDimensionClient:
    def __init__(self, api_key: str, agent_id: str, from_number_id: str | None, *, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._from_number_id = from_number_id
        self._timeout = timeout_seconds

    async def dispatch_call(self, *, to_phone_e164: str, call_context: dict) -> DispatchResult:
        payload: dict = {
            "agent_id": self._agent_id,
            "to_number": to_phone_e164,
            "call_context": call_context,
        }
        if self._from_number_id:
            payload["from_number_id"] = self._from_number_id

        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(OMNIDIMENSION_DISPATCH_URL, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code in (200, 201) and data.get("id"):
                return DispatchResult(success=True, provider_call_id=str(data["id"]))
            error_msg = data.get("message") or data.get("error") or f"HTTP {resp.status_code}"
            logger.error("OmniDimension dispatch failed: %s", error_msg)
            return DispatchResult(success=False, provider_call_id=None, error=str(error_msg))
        except httpx.TimeoutException:
            logger.error("OmniDimension dispatch timed out")
            return DispatchResult(success=False, provider_call_id=None, error="timeout")
        except httpx.HTTPError as exc:
            logger.error("OmniDimension dispatch raised a transport error: %s", exc.__class__.__name__)
            return DispatchResult(success=False, provider_call_id=None, error=str(exc.__class__.__name__))


@dataclass
class MockVoiceProviderClient:
    dispatched_calls: list[dict] = field(default_factory=list)

    async def dispatch_call(self, *, to_phone_e164: str, call_context: dict) -> DispatchResult:
        provider_call_id = f"mock-call-{uuid.uuid4().hex[:8]}"
        self.dispatched_calls.append({
            "to": to_phone_e164,
            "provider_call_id": provider_call_id,
            "call_context": call_context,
        })
        return DispatchResult(success=True, provider_call_id=provider_call_id)
