"""Environment-based configuration. Every secret comes from the environment (or a .env file)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Investors whose participation counts as a verified strength. Shown in the methodology
# section of every report. Matching is case-insensitive and exact.
DEFAULT_ESTABLISHED_INVESTORS = (
    "Accel",
    "Antler",
    "Bessemer Venture Partners",
    "Better Capital",
    "Blume Ventures",
    "Chiratae Ventures",
    "Elevation Capital",
    "Endiya Partners",
    "Fireside Ventures",
    "General Catalyst",
    "India Quotient",
    "Info Edge Ventures",
    "Kalaari Capital",
    "Lightspeed",
    "Lightspeed India",
    "Matrix Partners India",
    "Z47",
    "Nexus Venture Partners",
    "Omidyar Network India",
    "Peak XV Partners",
    "Sequoia Capital India",
    "Prime Venture Partners",
    "Saama Capital",
    "SoftBank Vision Fund",
    "Speciale Invest",
    "Stellaris Venture Partners",
    "3one4 Capital",
    "Tiger Global",
    "Titan Capital",
    "WaterBridge Ventures",
    "Y Combinator",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRUECAP_", env_file=".env", extra="ignore")

    app_name: str = "TrueCap"
    environment: str = "development"
    database_url: str = "sqlite:///./truecap.db"

    anthropic_api_key: str | None = None
    data_gov_in_api_key: str | None = None
    extraction_model: str = "claude-haiku-5-5"
    writing_model: str = "claude-sonnet-5-5"

    admin_email: str | None = None
    jwt_secret: str = "change-me-in-production"
    google_client_id: str | None = None

    daily_reports_per_user: int = 5
    monthly_llm_budget_inr: float = 800.0
    usd_to_inr: float = 88.0
    cache_ttl_days: int = 14

    established_investors: tuple[str, ...] = DEFAULT_ESTABLISHED_INVESTORS

    # data.gov.in "Company Master Data" resource ids (one per Registrar of Companies).
    # Copy them from each dataset's API tab on data.gov.in, comma-separated.
    data_gov_in_resource_ids: str = ""

    # Research limits per report (cost control).
    max_web_searches: int = 8
    max_website_pages: int = 4
    narrative_enabled: bool = True
    http_timeout_seconds: float = 15.0
    user_agent: str = "TrueCapBot/0.1 (+https://truecap.example/bot; public-data diligence)"


# USD per million tokens (input, output), and per web search. Update if pricing changes.
MODEL_PRICES_USD: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}
WEB_SEARCH_USD = 10.00 / 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
