# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database / broker
    DATABASE_URL: str = "postgresql+psycopg2://glassquote:glassquote@db:5432/glassquote"
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"

    # IMAP (single shared inbox all field workers send photos to)
    IMAP_HOST: str = "imap.example.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = "quotes@company.com"
    IMAP_PASSWORD: str = "changeme"
    IMAP_MAILBOX: str = "INBOX"
    IMAP_USE_SSL: bool = True
    # Only poll unseen mail whose subject contains this text (empty = no filter, poll all unseen).
    IMAP_SUBJECT_FILTER: str = ""

    # SMTP (owner approval email only — no customer email in this PoC)
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "quotes@company.com"
    SMTP_PASSWORD: str = "changeme"
    SMTP_USE_TLS: bool = True
    SMTP_FROM: str = "quotes@company.com"

    OWNER_EMAIL: str = "owner@company.com"

    # LLM (OpenAI-compatible endpoint — OpenAI, NVIDIA NIM, DeepSeek, Ollama /v1, etc.)
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = "changeme"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_VISION_MODEL: str = "gpt-4o-mini"
    LLM_MAX_RETRIES: int = 2
    LLM_TIMEOUT_SECONDS: int = 60

    # Optional separate endpoint for vision calls (falls back to LLM_BASE_URL/LLM_API_KEY if unset)
    LLM_VISION_BASE_URL: str = ""
    LLM_VISION_API_KEY: str = ""

    # Approval links
    APPROVAL_SECRET_KEY: str = "changeme-signing-key"
    APPROVAL_TOKEN_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 7
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Worker app auth (JWT bearer tokens — no self-registration, accounts
    # created by the owner via scripts/create_worker.py)
    JWT_SECRET_KEY: str = "changeme-jwt-signing-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_MINUTES: int = 60 * 24 * 14  # 14 days — field workers, not web sessions

    # Pricing rules / tier-3 enrichment defaults file locations
    RULES_PATH: str = "app/engine/rules.yaml"
    DEFAULTS_PATH: str = "app/engine/defaults.yaml"

    # Geocoding for Anthony's job map (maps branch). Nominatim (OpenStreetMap)
    # is free and needs no API key, but requires a descriptive User-Agent and
    # is rate-limited to 1 request/second — see app/geocode.py. Set
    # GEOCODE_ENABLED=false to skip live lookups and return only cached
    # coordinates (the map still loads, just with no fresh pins until a
    # later pass fills the cache).
    GEOCODE_USER_AGENT: str = "glassquote-nsw-jobmap/1.0"
    GEOCODE_ENABLED: bool = True
    # Hard cap on how many uncached addresses one map request will geocode
    # live — keeps Nominatim's 1 req/s policy satisfied and bounds latency.
    GEOCODE_MAX_LOOKUPS_PER_REQUEST: int = 8


settings = Settings()
