"""
SQLAlchemy 2.0 models. Deliberately small: the assignment's own guidance is
"do not over-engineer" and "the exact schema is up to you" -- this covers
exactly what gets read or written somewhere else in the codebase, nothing
speculative.

LeadState (app/models/schemas.py) is the working representation used by
all business logic; `Lead.state_json` is where it's persisted, as JSONB on
Postgres / JSON text on SQLite. Storing it as one structured blob rather
than exploding every field into its own column is a deliberate choice: the
shape of LeadState is expected to keep evolving during development, and a
single JSON column means schema changes don't require a migration for
every new field discovered while building the conversation flow. The
handful of columns duplicated onto `Lead` itself (phone, classification,
whatsapp/callback flags) are exactly the ones something needs to filter or
index on.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # our call_id, == provider's session id where possible
    provider: Mapped[str] = mapped_column(String, default="omnidimension")
    provider_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    to_phone: Mapped[str] = mapped_column(String)
    from_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger_reason: Mapped[str] = mapped_column(String, default="manual")  # manual | callback
    status: Mapped[str] = mapped_column(String, default="dispatched")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="call", uselist=False)
    turns: Mapped[list["ConversationTurn"]] = relationship(back_populates="call")
    actions: Mapped[list["OutboundAction"]] = relationship(back_populates="call")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), unique=True)
    phone: Mapped[str] = mapped_column(String)
    classification: Mapped[str | None] = mapped_column(String, nullable=True)  # HOT | WARM | COLD
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    whatsapp_midcall_status: Mapped[str] = mapped_column(String, default="pending")
    whatsapp_followup_status: Mapped[str] = mapped_column(String, default="pending")
    state_json: Mapped[dict] = mapped_column(JSON)  # full LeadState.model_dump(mode="json")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    call: Mapped["Call"] = relationship(back_populates="lead")


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"))
    turn_index: Mapped[int] = mapped_column()
    speaker: Mapped[str] = mapped_column(String)  # "caller" | "agent"
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_signals_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    call: Mapped["Call"] = relationship(back_populates="turns")


class ScheduledCallback(Base):
    __tablename__ = "scheduled_callbacks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"))
    raw_phrase: Mapped[str] = mapped_column(String)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # IST, tz-aware
    interpretation_note: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String, default="scheduled")  # scheduled | fired | cancelled | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OutboundAction(Base):
    """Every WhatsApp send attempt (mid-call or follow-up), one row per
    attempt -- this is the audit trail idempotency checks against and what
    "debuggable from a single call ID" (per the assignment's observability
    section) actually means in practice."""

    __tablename__ = "outbound_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"))
    action_type: Mapped[str] = mapped_column(String)  # whatsapp_midcall | whatsapp_followup
    status: Mapped[str] = mapped_column(String)  # sent | failed
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_preview: Mapped[str | None] = mapped_column(Text, nullable=True)  # first N chars, for debugging
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    call: Mapped["Call"] = relationship(back_populates="actions")
