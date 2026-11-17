"""The only place that reads environment variables (.env at the repo root)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore",
                                      populate_by_name=True)

    # AWS
    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None
    s3_bucket: Optional[str] = None

    # Model provider (decision D18): "gemini" now; "bedrock" kept as the planned production path
    llm_provider: Literal["gemini", "bedrock"] = "gemini"
    embed_dimensions: int = 512
    llm_max_tokens: int = 1000
    llm_temperature: float = 0.0
    llm_requests_per_minute: float = 0          # client-side rate limit for chat calls; 0 = none

    # Gemini (Google AI Studio API key)
    gemini_api_key: Optional[str] = None
    gemini_llm_id: str = "gemini-3.5-flash-lite"
    gemini_embed_id: str = "gemini-embedding-001"
    gemini_thinking_budget: Optional[int] = None  # empty = model default; Gemini 3.x Flash-Lite thinks only if asked

    # Bedrock
    bedrock_llm_id: Optional[str] = None
    bedrock_embed_id: str = "amazon.titan-embed-text-v2:0"
    llm_extra_request_fields_json: Optional[str] = Field(default=None, alias="LLM_EXTRA_REQUEST_FIELDS")

    @property
    def llm_model_id(self) -> Optional[str]:
        return self.gemini_llm_id if self.llm_provider == "gemini" else self.bedrock_llm_id

    @property
    def embed_model_id(self) -> str:
        return self.gemini_embed_id if self.llm_provider == "gemini" else self.bedrock_embed_id

    # Token budget
    llm_token_budget_input: int = 1_500_000
    llm_token_budget_output: int = 300_000
    embed_token_budget: int = 400_000
    max_llm_calls_per_case: int = 6

    # Storage
    mongo_uri: str = "mongodb://localhost:27017/caselens"
    chroma_path: Path = Path("data/chroma")
    chroma_collection: str = "reg_docs"

    # API (the backend forwards decisions to its own mock case system route)
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"          # comma-separated

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
    max_upload_mb: int = 300           # M7 uploads (D17)

    # Investigation
    typology_top_k: int = 4
    prompt_version: str = "v1"
    random_seed: int = 42
    id_pattern: str = r"\b[0-9A-F]{8,12}\b"

    @field_validator("aws_profile", "s3_bucket", "bedrock_llm_id", "langsmith_api_key", "max_rows",
                     "llm_extra_request_fields_json", "aws_region", "gemini_api_key", "gemini_thinking_budget",
                     mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("llm_extra_request_fields_json", mode="after")
    @classmethod
    def _valid_json(cls, v):
        if v is not None and not isinstance(json.loads(v), dict):
            raise ValueError("LLM_EXTRA_REQUEST_FIELDS must be a JSON object")
        return v

    @property
    def llm_extra_request_fields(self) -> Optional[dict[str, Any]]:
        return json.loads(self.llm_extra_request_fields_json) if self.llm_extra_request_fields_json else None

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
