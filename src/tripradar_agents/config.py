from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRIPRADAR_AGENT_", env_file=ROOT / ".env", extra="ignore", populate_by_name=True
    )
    mode: Literal["live", "fixture"] = "live"
    database: Path = ROOT / "data/runtime/tripradar.sqlite3"
    provider: Literal["openai"] = Field(
        default="openai", validation_alias=AliasChoices("TRIPRADAR_AGENT_PROVIDER", "LLM_PROVIDER")
    )
    model: str = Field(
        default="", validation_alias=AliasChoices("TRIPRADAR_AGENT_MODEL", "LLM_MODEL")
    )
    shared_model: str = Field(default="", validation_alias="LLM_MODEL", exclude=True)
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("TRIPRADAR_AGENT_BASE_URL", "LLM_BASE_URL"),
    )
    specialist_model: str = ""
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TRIPRADAR_AGENT_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    chroma_backend: Literal["cloud", "local"] = "cloud"
    chroma_collection: str = "cloud_tripradar_destinations_6d212e1068573a49"
    deadline_seconds: float = 120
    max_model_calls: int = 12
    max_reads: int = 20
    # Explicitly set rates from your account's rate card before live execution.
    input_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    request_cost_cap: float = 2
    amadeus_environment: Literal["test", "production"] = "test"
    amadeus_client_id: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TRIPRADAR_AGENT_AMADEUS_CLIENT_ID", "AMADEUS_CLIENT_ID"),
    )
    amadeus_client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "TRIPRADAR_AGENT_AMADEUS_CLIENT_SECRET", "AMADEUS_CLIENT_SECRET"
        ),
    )
    startup_model_probes: bool = False
    judge_tracking: bool = False
    judge_acceptance_path: Path = ROOT / "data/evals/judge-acceptance.json"
    api_url: str = "http://127.0.0.1:8000"

    langsmith_tracing: bool = False
    langsmith_project: str = "tripradar-agents"
    langsmith_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TRIPRADAR_AGENT_LANGSMITH_API_KEY", "LANGSMITH_API_KEY"),
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("TRIPRADAR_AGENT_LANGSMITH_ENDPOINT", "LANGSMITH_ENDPOINT"),
    )
    langsmith_workspace_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "TRIPRADAR_AGENT_LANGSMITH_WORKSPACE_ID", "LANGSMITH_WORKSPACE_ID"
        ),
    )

    @model_validator(mode="after")
    def provider_defaults(self):
        if not self.model:
            self.model = "gpt-4.1"
        if not self.specialist_model:
            self.specialist_model = self.shared_model or "gpt-4.1-mini"
        # Standard text rates verified from official model pages; explicit values override.
        # Unknown/custom models require explicit rates rather than guessed costs.
        rates = {
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4o-mini-2024-07-18": (0.15, 0.60),
            "gpt-4.1": (2.0, 8.0),
            "gpt-4.1-mini": (0.4, 1.6),
            "gpt-4.1-2025-04-14": (2.0, 8.0),
            "gpt-4.1-mini-2025-04-14": (0.4, 1.6),
        }
        known = (
            self.provider == "openai"
            and self.base_url.rstrip("/") == "https://api.openai.com/v1"
            and all(m in rates for m in (self.model, self.specialist_model))
        )
        if self.input_usd_per_million is None:
            self.input_usd_per_million = (
                max(rates[m][0] for m in (self.model, self.specialist_model)) if known else 0
            )
        if self.output_usd_per_million is None:
            self.output_usd_per_million = (
                max(rates[m][1] for m in (self.model, self.specialist_model)) if known else 0
            )
        return self

    def readiness(self) -> list[str]:
        if self.mode == "fixture":
            return []
        missing = []
        if not self.openai_api_key.get_secret_value():
            missing.append("OPENAI_API_KEY")
        if self.input_usd_per_million <= 0:
            missing.append("TRIPRADAR_AGENT_INPUT_USD_PER_MILLION")
        if self.output_usd_per_million <= 0:
            missing.append("TRIPRADAR_AGENT_OUTPUT_USD_PER_MILLION")
        return missing
