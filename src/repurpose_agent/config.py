from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from env vars prefixed with REPURPOSE_ (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="REPURPOSE_", env_file=".env", extra="ignore")

    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16_000

    # Critic loop
    pass_score: int = 8  # drafts scoring >= this (1-10) are accepted
    max_revisions: int = 2  # max automatic rewrites per platform

    # Ingest
    max_source_chars: int = 60_000
    http_timeout: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
