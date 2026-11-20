"""
WhatsApp delivery, behind a small Protocol so the rest of the system never
imports Meta's API directly. Two implementations:

  - MetaCloudAPIWhatsAppClient: the real thing (app/whatsapp/client.py).
    Requires WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, and a
    pre-approved message template (see README "WhatsApp Setup"). Not
    exercised against the live API from this environment -- no network
    path to graph.facebook.com from the build sandbox, and no token was
    available -- but written against Meta's current documented Cloud API
    request/response shape.

  - MockWhatsAppClient: records every call in memory instead of sending
    anything. This is what the test suite and scripts/simulate_call.py
    actually run against, so "the mid-call WhatsApp fires" is a claim we
    can back with a real, repeatable, passing test rather than an
    unverifiable assertion.

Which one gets wired up is decided in one place: app/config.py picks
MetaCloudAPIWhatsAppClient only if WHATSAPP_ACCESS_TOKEN is set, otherwise
MockWhatsAppClient -- so a missing credential degrades to "runs, logs
clearly, sends nothing" rather than a startup crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

logger = logging.getLogger("elevatebox.whatsapp")

GRAPH_API_VERSION = "v21.0"  # bump here if Meta advances the default version


@dataclass(frozen=True)
class WhatsAppSendResult:
    success: bool
    provider_message_id: str | None
    error: str | None = None


class WhatsAppClient(Protocol):
    async def send_template_message(
        self,
        *,
        to_phone_e164: str,
        template_name: str,
        language_code: str,
        body_params: list[str],
        header_document_url: str | None = None,
        header_document_filename: str | None = None,
        header_image_url: str | None = None,
    ) -> WhatsAppSendResult: ...

    async def send_text_message(self, *, to_phone_e164: str, text: str) -> WhatsAppSendResult: ...


class MetaCloudAPIWhatsAppClient:
    """
    Real implementation against Meta's WhatsApp Business Cloud API.

    Business-initiated messages (which this always is -- the evaluator
    calls US, they haven't messaged our WhatsApp number first) MUST use a
    pre-approved template outside the 24-hour customer-service window; a
    free-form `send_text_message` will be rejected by Meta with error code
    131047 in that case. `send_text_message` is kept here for completeness
    and for the (rare) case a prior inbound message opened a 24h window.
    """

    def __init__(self, access_token: str, phone_number_id: str, *, timeout_seconds: float = 10.0) -> None:
        self._token = access_token
        self._phone_number_id = phone_number_id
        self._base_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
        self._timeout = timeout_seconds

    async def send_template_message(
        self,
        *,
        to_phone_e164: str,
        template_name: str,
        language_code: str = "en",
        body_params: list[str],
        header_document_url: str | None = None,
        header_document_filename: str | None = None,
        header_image_url: str | None = None,
    ) -> WhatsAppSendResult:
        components = []
        if header_document_url:
            components.append({
                "type": "header",
                "parameters": [{
                    "type": "document",
                    "document": {"link": header_document_url, "filename": header_document_filename or "document.pdf"},
                }],
            })
        elif header_image_url:
            components.append({
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": header_image_url}}],
            })
        if body_params:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in body_params],
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        return await self._post(payload)

    async def send_text_message(self, *, to_phone_e164: str, text: str) -> WhatsAppSendResult:
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone_e164,
            "type": "text",
            "text": {"body": text},
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> WhatsAppSendResult:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._base_url, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and "messages" in data:
                return WhatsAppSendResult(success=True, provider_message_id=data["messages"][0].get("id"))
            error_msg = data.get("error", {}).get("message", f"HTTP {resp.status_code}")
            logger.error("WhatsApp send failed: %s", error_msg)  # never log headers/token
            return WhatsAppSendResult(success=False, provider_message_id=None, error=error_msg)
        except httpx.TimeoutException:
            logger.error("WhatsApp send timed out")
            return WhatsAppSendResult(success=False, provider_message_id=None, error="timeout")
        except httpx.HTTPError as exc:
            logger.error("WhatsApp send raised a transport error: %s", exc.__class__.__name__)
            return WhatsAppSendResult(success=False, provider_message_id=None, error=str(exc.__class__.__name__))


@dataclass
class MockWhatsAppClient:
    """Records every send in memory. Used by tests and the simulation
    script so the mid-call/follow-up WhatsApp behaviour is exercised for
    real, without needing a Meta account."""

    sent_messages: list[dict] = field(default_factory=list)
    fail_next: bool = False

    async def send_template_message(
        self,
        *,
        to_phone_e164: str,
        template_name: str,
        language_code: str = "en",
        body_params: list[str],
        header_document_url: str | None = None,
        header_document_filename: str | None = None,
        header_image_url: str | None = None,
    ) -> WhatsAppSendResult:
        if self.fail_next:
            self.fail_next = False
            return WhatsAppSendResult(success=False, provider_message_id=None, error="simulated failure")
        record = {
            "to": to_phone_e164,
            "type": "template",
            "template_name": template_name,
            "body_params": body_params,
            "header_document_url": header_document_url,
            "header_image_url": header_image_url,
        }
        self.sent_messages.append(record)
        return WhatsAppSendResult(success=True, provider_message_id=f"mock-{len(self.sent_messages)}")

    async def send_text_message(self, *, to_phone_e164: str, text: str) -> WhatsAppSendResult:
        if self.fail_next:
            self.fail_next = False
            return WhatsAppSendResult(success=False, provider_message_id=None, error="simulated failure")
        self.sent_messages.append({"to": to_phone_e164, "type": "text", "text": text})
        return WhatsAppSendResult(success=True, provider_message_id=f"mock-{len(self.sent_messages)}")
