from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app.api.deps import get_voice_client
from app.api.routes_calls import router as calls_router
from app.api.routes_health import router as health_router
from app.api.routes_webhooks import router as webhooks_router
from app.config import get_settings, startup_credential_report
from app.db import async_session_maker, init_db
from app.logging_config import configure_logging
from app.scheduler.callback_service import fire_due_callbacks
from app.services.lead_repository import list_leads_with_due_callbacks, save_lead_state

logger = logging.getLogger("elevatebox.main")

_CALLBACK_POLL_INTERVAL_SECONDS = 60


async def _due_callback_poller() -> None:
    """Lightweight polling loop instead of Redis/Celery -- per the
    assignment's own "Redis/background jobs only if genuinely useful"
    guidance, a take-home's callback volume doesn't need a job queue."""
    settings = get_settings()
    voice_client = get_voice_client(settings)
    while True:
        try:
            async with async_session_maker() as session:
                now_iso = datetime.now(timezone.utc).isoformat()
                due = await list_leads_with_due_callbacks(session, now_iso)
                if due:
                    fired = await fire_due_callbacks(
                        [(lead, lead.callback) for lead in due if lead.callback], voice_client
                    )
                    for lead in due:
                        await save_lead_state(session, lead)
                    if fired:
                        logger.info("fired %d due callback(s): %s", len(fired), fired)
        except Exception:  # noqa: BLE001 -- a poller crash must not take the whole app down
            logger.exception("due-callback poll iteration failed")
        await asyncio.sleep(_CALLBACK_POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("starting up; credential status: %s", startup_credential_report())
    await init_db()
    poller_task = asyncio.create_task(_due_callback_poller())
    yield
    poller_task.cancel()


app = FastAPI(title="ElevateBox Voice AI Agent", lifespan=lifespan)
app.include_router(health_router)
app.include_router(calls_router)
app.include_router(webhooks_router)
