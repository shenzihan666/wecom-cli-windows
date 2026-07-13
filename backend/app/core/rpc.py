"""Thin wecom-cli JSON-RPC transport. No AI, no business logic.

Every call optionally accepts ``config_dir`` so an upstream account manager can
route a request to a specific wecom-cli credential sandbox (multi-account).
When ``config_dir`` is ``None`` the ambient environment / default config is used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def wecom_cli() -> str:
    """Resolve wecom-cli for subprocess (Windows needs .cmd via shutil.which)."""
    cmd = shutil.which("wecom-cli")
    if not cmd:
        raise FileNotFoundError("wecom-cli not found in PATH")
    return cmd


def _rpc_env(config_dir: str | Path | None) -> dict[str, str] | None:
    if not config_dir:
        return None
    env = os.environ.copy()
    env["WECOM_CLI_CONFIG_DIR"] = str(config_dir)
    return env


# A single wecom-cli call should return well within this. Without a timeout a
# hung/weird wecom-cli process freezes the entire account worker forever (the
# surrounding try/except only catches exceptions, not indefinite hangs).
_DEFAULT_RPC_TIMEOUT = 30.0


def rpc(
    args: list[str],
    config_dir: str | Path | None = None,
    *,
    timeout: float = _DEFAULT_RPC_TIMEOUT,
) -> dict:
    """Run a wecom-cli MCP command and return the parsed inner JSON payload."""
    # encoding=utf-8: Windows default locale (cp936) corrupts CLI JSON with CJK names
    try:
        out = subprocess.check_output(
            [wecom_cli(), *args],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
            env=_rpc_env(config_dir),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        cmd_summary = " ".join(args[:2])
        raise RuntimeError(f"wecom-cli timed out after {timeout}s ({cmd_summary})") from e
    outer = json.loads(out)
    if outer.get("result", {}).get("isError"):
        raise RuntimeError(out)
    return json.loads(outer["result"]["content"][0]["text"])


def time_window(days: float = 6.0) -> tuple[str, str]:
    end = datetime.now()
    begin = end - timedelta(days=days)
    fmt = "%Y-%m-%d %H:%M:%S"
    return begin.strftime(fmt), end.strftime(fmt)
