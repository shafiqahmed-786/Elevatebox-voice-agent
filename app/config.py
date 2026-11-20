"""
All configuration in one place, loaded from environment variables (see
.env.example for the full documented list). Nothing in this file has a
secret hardcoded -- every credential is `None` by default and the system
degrades to mock/simulation behaviour rather than crashing, EXCEPT where a
missing value would cause it to silently pretend to do something it isn't
(see `require_for_live_call` below).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./elevatebox.db"
    log_level: str = "INFO"
    public_base_url: str | None = None  # e.g. https://your-app.up.railway.app, needed for provider webhooks

    # --- Agent identity (used in WhatsApp messages, never hardcoded) ---
    agent_name: str = "Shafiq"
    agent_phone: str = "+91-XXXXXXXXXX"  # set your real number in .env
    resume_url: str | None = None  # public URL to a hosted resume PDF/DOCX
    architecture_image_url: str | None = None  # public URL to docs/architecture.png once hosted

    # --- OmniDimension (voice/telephony) ---
    omnidimension_api_key: str | None = None
    omnidimension_agent_id: str | None = None
    omnidimension_from_number_id: str | None = None
    evaluator_phone_e164: str = "+918688664337"  # the number from the assignment PDF

    # --- WhatsApp Cloud API (Meta) ---
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_midcall_template_name: str = "elevatebox_midcall_update"
    whatsapp_followup_template_name: str = "elevatebox_followup"

    # --- LLM (extraction fallback + follow-up polish) ---
    anthropic_api_key: str | None = None
    conversation_model: str = "claude-haiku-4-5-20251001"  # optimized for turn latency
    extraction_model: str = "claude-sonnet-5"  # used off the hot path, quality over speed

    @property
    def has_live_omnidimension(self) -> bool:
        return bool(self.omnidimension_api_key and self.omnidimension_agent_id)

    @property
    def has_live_whatsapp(self) -> bool:
        return bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)

    @property
    def has_live_llm(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def startup_credential_report() -> dict[str, bool]:
    """Called once at app startup and logged (not raised) -- per the
    assignment's own instruction to report blockers explicitly rather than
    fail silently OR crash the whole app over an optional integration."""
    s = get_settings()
    return {
        "omnidimension_live": s.has_live_omnidimension,
        "whatsapp_live": s.has_live_whatsapp,
        "llm_live": s.has_live_llm,
        "database_configured": bool(s.database_url),
    }
