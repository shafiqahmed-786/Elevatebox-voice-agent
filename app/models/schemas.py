"""
Structured state models for a single call.

These are the types the whole system is built around. Per the assignment's
own instruction ("do not make the LLM responsible for everything"), the LLM's
only job is to fill these fields in accurately from the conversation. Every
decision (classification, callback time, follow-up wording) is then made by
deterministic code operating on this structured state, not by asking the LLM
"what should happen next."
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Language(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"
    TELUGU = "te"
    HINGLISH = "hinglish"
    TENGLISH = "tenglish"  # Telugu <-> English code-switching
    UNKNOWN = "unknown"


class IntentClassification(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class ExtractedSignals(BaseModel):
    """
    Raw signals pulled from the transcript so far. This is the ONLY thing the
    conversation LLM is asked to produce during a call (via a tool call). It
    intentionally does not include a classification -- that is computed
    deterministically from these fields, see app/decision/classifier.py.
    """

    asked_price: bool = False
    asked_start_timeline: bool = False
    explicit_next_step_request: bool = False  # "send me details", "let's proceed"
    specific_feature_questions: list[str] = Field(default_factory=list)  # "Razorpay integration?"

    business_type: str | None = None
    sells_online_currently: bool | None = None  # None = not yet asked; True/False = an actual answer
    product_count: int | None = None
    decision_maker: str | None = None  # "self", or who else is involved

    concrete_budget_inr: int | None = None
    concrete_timeline: str | None = None  # e.g. "3 weeks", "by Diwali"

    budget_barrier: bool = False
    approval_barrier: str | None = None  # who: "brother", "partner", "wife", etc.
    timing_barrier: str | None = None  # e.g. "maybe next month"

    just_browsing: bool = False
    general_interest: bool = False
    has_business_context: bool = False

    model_config = ConfigDict(extra="ignore")


class IntentResult(BaseModel):
    classification: IntentClassification
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[str]
    hot_score: int = 0
    warm_score: int = 0
    cold_score: int = 0


class CallbackRequest(BaseModel):
    raw_phrase: str
    interpreted_datetime: datetime  # tz-aware, Asia/Kolkata
    interpretation_note: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: str = "scheduled"  # scheduled | fired | cancelled


class ConversationStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class ActionStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class LeadState(BaseModel):
    """
    The single structured object that represents everything known about a
    lead at a point in time. Written to Postgres as JSONB on the Lead row
    after every conversation turn (see app/models/db_models.py), and is the
    ONLY input the decision engine and message generators ever read from --
    nothing downstream ever re-reads the raw transcript.
    """

    call_id: str
    conversation_status: ConversationStatus = ConversationStatus.IN_PROGRESS
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Contact / business identity
    caller_phone: str | None = None
    contact_name: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    sells_online_currently: bool | None = None

    # Discovery
    language: Language = Language.UNKNOWN
    product_count: int | None = None
    budget_inr: int | None = None
    timeline: str | None = None
    features: list[str] = Field(default_factory=list)
    decision_maker: str | None = None  # "self" or e.g. "brother co-owns the shop"
    barriers: list[str] = Field(default_factory=list)

    # Qualification
    cumulative_signals: ExtractedSignals = Field(default_factory=ExtractedSignals)
    intent: IntentResult | None = None

    # Actions
    callback: CallbackRequest | None = None
    whatsapp_midcall_status: ActionStatus = ActionStatus.PENDING
    whatsapp_midcall_sent_at: datetime | None = None
    whatsapp_followup_status: ActionStatus = ActionStatus.PENDING
    whatsapp_followup_sent_at: datetime | None = None

    # Free-form
    key_quotes: list[str] = Field(default_factory=list)  # verbatim useful lines, for follow-up
    notes: str | None = None

    @property
    def whatsapp_midcall_sent(self) -> bool:
        return self.whatsapp_midcall_status in (ActionStatus.SENT, ActionStatus.COMPLETED)

    @property
    def whatsapp_followup_sent(self) -> bool:
        return self.whatsapp_followup_status in (ActionStatus.SENT, ActionStatus.COMPLETED)

    def as_example_dict(self) -> dict:
        """Compact dict in the exact shape shown in the assignment brief."""
        return {
            "language": self.language.value,
            "business_type": self.business_type,
            "product_count": self.product_count,
            "budget": self.budget_inr,
            "timeline": self.timeline,
            "features": self.features,
            "intent": {
                "classification": self.intent.classification.value if self.intent else None,
                "confidence": self.intent.confidence if self.intent else None,
                "signals": self.intent.signals if self.intent else [],
            },
            "barriers": self.barriers,
            "callback": self.callback.raw_phrase if self.callback else None,
            "whatsapp_sent": self.whatsapp_midcall_sent or self.whatsapp_followup_sent,
        }
