"""Runtime configuration, sourced from environment variables.

Keeps the same env var names as the original experimental server so existing
deployments and the ``data/`` + ``media/`` folders keep working unchanged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] == project root (d:\wecom_CLI_TEST)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # HTTP server
    host: str = "127.0.0.1"
    port: int = 8765

    # Sync poller
    poll_sec: float = 5.0

    # Your WeCom userid (outbound bubbles). Empty => auto-detect from DM senders.
    self_userid: str = ""

    # Paths (kept relative to project root for backwards compatibility)
    project_root: Path = PROJECT_ROOT

    @property
    def media_dir(self) -> Path:
        return self.project_root / "media"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def static_dir(self) -> Path:
        return self.project_root / "static"

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache.json"


def _build_settings() -> Settings:
    import os

    # Backwards-compatible env aliases from the original server.py
    aliases = {
        "WECOM_WEB_HOST": "HOST",
        "WECOM_WEB_PORT": "PORT",
        "WECOM_POLL_SEC": "POLL_SEC",
        "SELF_USERID": "SELF_USERID",
    }
    for legacy, canonical in aliases.items():
        val = os.environ.get(legacy)
        if val is not None and os.environ.get(canonical) is None:
            os.environ[canonical] = val
    return Settings()


settings = _build_settings()
