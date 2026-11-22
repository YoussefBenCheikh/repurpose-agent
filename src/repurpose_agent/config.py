from functools import lru_cache
from pathlib import Path
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

    # Persistence: set to a Postgres URL to keep runs across restarts.
    # Unset = in-memory (runs are lost when the process exits).
    database_url: str | None = None

    # Brand voice (RAG over past posts)
    embeddings: Literal["fastembed", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    voice_examples: int = 3  # past posts retrieved per platform
    brand_file: Path | None = Path("brand/posts.json")  # seeded into the store at startup

    # Demo mode: scripted LLM, no API key needed (see demo.py)
    demo: bool = False

    # API
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
