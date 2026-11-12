"""The only place that reads environment variables (.env at the repo root)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # AWS
    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None
    s3_bucket: Optional[str] = None

    # Bedrock
    bedrock_llm_id: Optional[str] = None
    bedrock_embed_id: str = "amazon.titan-embed-text-v2:0"
    embed_dimensions: int = 512
    llm_max_tokens: int = 1000
    llm_temperature: float = 0.0
    llm_extra_request_fields: Optional[dict[str, Any]] = None

    # Token budget
    llm_token_budget_input: int = 1_500_000
    llm_token_budget_output: int = 300_000
    embed_token_budget: int = 400_000
    max_llm_calls_per_case: int = 6

    # Storage
    mongo_uri: str = "mongodb://localhost:27017/caselens"
    chroma_path: Path = Path("data/chroma")
    chroma_collection: str = "reg_docs"

    # LangSmith
    langsmith_tracing: bool = True
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "caselens"

    # Data slice and guards
    slice_hours: int = 24
    max_rows: Optional[int] = None
    keep_local_raw: bool = False
    mongo_max_gb: float = 1.0
    disk_budget_gb: float = 10.0
    max_alerts: int = 5000

    # Investigation
    typology_top_k: int = 4
    prompt_version: str = "v1"
    random_seed: int = 42
    id_pattern: str = r"\b[0-9A-F]{8,12}\b"

    @field_validator("aws_profile", "s3_bucket", "bedrock_llm_id", "langsmith_api_key", "max_rows",
                     "llm_extra_request_fields", "aws_region", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("llm_extra_request_fields", mode="before")
    @classmethod
    def _parse_json(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    @field_validator("chroma_path", mode="after")
    @classmethod
    def _abs_path(cls, v: Path) -> Path:
        return v if v.is_absolute() else REPO_ROOT / v

    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / "data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
