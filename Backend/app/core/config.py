"""Runtime configuration, loaded from environment variables (prefix ``SAP_``) or ``.env``."""

from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SAP_", extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    app_name: str = "Secure Analytics Pro"

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    data_dir: Path = Path("./data")

    # 32-byte key-encryption key (base64). Wraps the per-dataset data keys.
    master_key: str | None = None
    # PEM-encoded Ed25519 private key used to sign access tokens.
    jwt_private_key: str | None = None
    jwt_issuer: str = "secure-analytics-pro"
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 14 * 24 * 3600

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    cookie_secure: bool = False

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

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


def _load_or_create(path: Path, factory) -> bytes:
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = factory()
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


class Keys:
    """Key material. In production keys must come from the environment; in dev they are
    generated once and persisted under ``data_dir/keys`` so restarts keep data readable."""

    def __init__(self, settings: Settings) -> None:
        key_dir = settings.data_dir / "keys"
        if settings.master_key:
            kek = base64.b64decode(settings.master_key)
        elif settings.is_prod:
            raise RuntimeError("SAP_MASTER_KEY is required in production")
        else:
            kek = base64.b64decode(
                _load_or_create(key_dir / "master.key", lambda: base64.b64encode(secrets.token_bytes(32)))
            )
        if len(kek) != 32:
            raise RuntimeError("SAP_MASTER_KEY must decode to exactly 32 bytes")
        self.kek = kek

        if settings.jwt_private_key:
            pem = settings.jwt_private_key.replace("\\n", "\n").encode()
        elif settings.is_prod:
            raise RuntimeError("SAP_JWT_PRIVATE_KEY is required in production")
        else:
            pem = _load_or_create(
                key_dir / "jwt_ed25519.pem",
                lambda: Ed25519PrivateKey.generate().private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ),
            )
        self.jwt_private = serialization.load_pem_private_key(pem, password=None)
        self.jwt_public = self.jwt_private.public_key()


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


@lru_cache
def get_keys() -> Keys:
    return Keys(get_settings())
