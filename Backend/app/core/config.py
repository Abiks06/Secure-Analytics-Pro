"""Runtime configuration, loaded from environment variables (prefix ``SAP_``) or ``.env``."""

from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SAP_", extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    app_name: str = "Secure Analytics Pro"

    # Supabase Postgres via the session pooler, as the least-privilege `sap_engine` role.
    # SQLite is supported for offline tests only.
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    data_dir: Path = Path("./data")

    # Supabase project. Auth tokens are verified against its public JWKS; encrypted datasets
    # are stored in its private `datasets` bucket using the caller's own access token.
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    # Test-only: a JWKS document to trust instead of fetching it from Supabase.
    supabase_jwks_json: str | None = None
    storage_backend: Literal["supabase", "local"] | None = None

    # 32-byte key-encryption key (base64). Wraps the per-dataset data keys.
    master_key: str | None = None

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    max_upload_mb: int = 200
    max_decompressed_mb: int = 1024
    worker_concurrency: int = 2
    frame_cache_mb: int = 512

    query_timeout_s: float = 10.0
    query_row_limit: int = 5_000

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-opus-5-5"

    static_dir: Path | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("supabase_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def blob_backend(self) -> str:
        return self.storage_backend or ("supabase" if self.supabase_url else "local")

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"


class Keys:
    """Key material. In production the KEK must come from the environment; in dev it is
    generated once and persisted under ``data_dir/keys`` so restarts keep data readable."""

    def __init__(self, settings: Settings) -> None:
        if settings.master_key:
            kek = base64.b64decode(settings.master_key)
        elif settings.is_prod:
            raise RuntimeError("SAP_MASTER_KEY is required in production")
        else:
            path = settings.data_dir / "keys" / "master.key"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64encode(secrets.token_bytes(32)))
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            kek = base64.b64decode(path.read_bytes())
        if len(kek) != 32:
            raise RuntimeError("SAP_MASTER_KEY must decode to exactly 32 bytes")
        self.kek = kek


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    if not s.supabase_url:
        raise RuntimeError("SAP_SUPABASE_URL is required: authentication is provided by Supabase Auth")
    return s


@lru_cache
def get_keys() -> Keys:
    return Keys(get_settings())
