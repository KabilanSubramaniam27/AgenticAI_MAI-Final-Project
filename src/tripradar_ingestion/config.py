from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


def project_root() -> Path:
    if value := os.environ.get("TRIPRADAR_ROOT"):
        return Path(value).expanduser().resolve()
    for path in (Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]):
        if (path / "config/destinations.yaml").is_file():
            return path
    raise ValueError("Set TRIPRADAR_ROOT to the project containing config/destinations.yaml")


class Settings(BaseModel):
    root: Path
    data_directory: str = "data"
    chroma_persist_directory: str = "data/chroma_db"
    chroma_collection: str = "tripradar_destinations"
    embedding_function: Literal["chroma_default"] = "chroma_default"
    embedding_model: Literal["all-MiniLM-L6-v2"] = "all-MiniLM-L6-v2"
    embedding_dimension: Literal[384] = 384
    embedding_space_version: str = "chroma-minilm-v1"
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    chunk_target_tokens: int = Field(default=180, ge=16)
    chunk_overlap_tokens: int = Field(default=24, ge=0)
    chunk_max_input_tokens: int = Field(default=256, ge=32, le=256)
    http_timeout_seconds: float = Field(default=30, gt=0)
    http_max_retries: int = Field(default=4, ge=0, le=8)
    http_interval_seconds: float = Field(default=1, ge=0)
    scraper_user_agent: str = "TripRadarIngestion/0.1 (local research; contact not configured)"
    max_district_depth: int = Field(default=2, ge=0, le=3)
    max_district_pages: int = Field(default=40, ge=0, le=100)
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "tripradar-ingestion"
    langsmith_workspace_id: str = ""

    @field_validator("embedding_dimension", mode="before")
    @classmethod
    def dimension_from_env(cls, value):
        return int(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def budgets(self) -> Settings:
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("Overlap must be smaller than the chunk target")
        if self.chunk_target_tokens >= self.chunk_max_input_tokens:
            raise ValueError("Chunk target must reserve room for context and special tokens")
        return self

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def data(self) -> Path:
        return self.resolve(self.data_directory)

    @classmethod
    def load(cls, root: Path | None = None) -> Settings:
        root = (root or project_root()).resolve()
        config_file = root / "config/settings.yaml"
        values = yaml.safe_load(config_file.read_text()) or {} if config_file.exists() else {}
        # Prefix isolates ingestion from old agent/provider configuration in an existing .env.
        env = {**dotenv_values(root / ".env"), **os.environ}
        for field in cls.model_fields:
            if field == "root":
                continue
            key = field.upper() if field.startswith("langsmith_") else "TRIPRADAR_" + field.upper()
            if key in env and env[key] not in (None, ""):
                values[field] = env[key]
            scoped_key = "TRIPRADAR_" + field.upper()
            if scoped_key in env and env[scoped_key] not in (None, ""):
                values[field] = env[scoped_key]
        return cls(root=root, **values)
