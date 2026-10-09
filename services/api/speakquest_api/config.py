"""Runtime configuration from environment variables (validated at cold start).

Only non-secret configuration lives here — bucket and table names, ARNs,
limits. Lambda gets these from Terraform; the local server from
``.env.local`` / the shell. AWS credentials are never read from here.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    env: str = Field(default="dev", pattern=r"^[a-z0-9-]{2,16}$")
    backend: Literal["aws", "local"] = "aws"
    region: str = "us-east-1"
    bucket: str = ""
    table: str = ""
    state_machine_arn: str = ""
    allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_duration_s: int = Field(default=180, gt=0)
    upload_url_ttl_s: int = Field(default=300, ge=60, le=3600)
    result_url_ttl_s: int = Field(default=600, ge=60, le=3600)
    analysis_ttl_days: int = Field(default=14, ge=1)
    max_active_analyses: int = Field(default=3, ge=1)
    transcribe_language: str = "en-US"
    # Local backend only.
    local_dir: str = ".local"
    local_base_url: str = "http://localhost:8787"
    local_aligner: str = "vosk"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split(cls, v: object) -> object:
        if isinstance(v, str):
            return tuple(o.strip().rstrip("/") for o in v.split(",") if o.strip())
        return v

    def require_aws(self) -> None:
        missing = [n for n in ("bucket", "table") if not getattr(self, n)]
        if missing:
            raise RuntimeError(f"missing configuration: {', '.join(missing)}")


_ENV_MAP = {
    "env": "SPEAKQUEST_ENV",
    "backend": "SPEAKQUEST_BACKEND",
    "region": "AWS_REGION",
    "bucket": "SPEAKQUEST_BUCKET",
    "table": "SPEAKQUEST_TABLE",
    "state_machine_arn": "SPEAKQUEST_STATE_MACHINE_ARN",
    "allowed_origins": "SPEAKQUEST_ALLOWED_ORIGINS",
    "max_upload_bytes": "SPEAKQUEST_MAX_UPLOAD_BYTES",
    "max_duration_s": "SPEAKQUEST_MAX_DURATION_S",
    "upload_url_ttl_s": "SPEAKQUEST_UPLOAD_URL_TTL_S",
    "result_url_ttl_s": "SPEAKQUEST_RESULT_URL_TTL_S",
    "analysis_ttl_days": "SPEAKQUEST_ANALYSIS_TTL_DAYS",
    "max_active_analyses": "SPEAKQUEST_MAX_ACTIVE_ANALYSES",
    "transcribe_language": "SPEAKQUEST_LANGUAGE",
    "local_dir": "SPEAKQUEST_LOCAL_DIR",
    "local_base_url": "SPEAKQUEST_LOCAL_BASE_URL",
    "local_aligner": "SPEAKQUEST_LOCAL_ALIGNER",
}


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    values = {field: env[var] for field, var in _ENV_MAP.items() if env.get(var)}
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise RuntimeError(f"invalid SpeakQuest configuration: {exc}") from exc


@lru_cache(maxsize=1)
def settings() -> Settings:
    return load_settings()
