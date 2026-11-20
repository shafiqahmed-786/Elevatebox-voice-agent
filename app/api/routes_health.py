from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.config import startup_credential_report

router = APIRouter(tags=["health"])


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=307)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "credentials": startup_credential_report()}
