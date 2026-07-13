"""Standalone polling subprocess for one account.

Spawned by ``AccountProcessManager`` (one process per account) instead of
running as an in-process thread. This gives us real OS-level process control:
``taskkill`` to stop, and Windows Job Objects to truly suspend/resume (see
``app.core.windows_job``) without losing in-memory state.

Usage (spawned by the parent, not meant to be run manually):
    uv run python backend/scripts/poll_worker.py \
        --account-id default --config-dir "" --self-userid "" --poll-sec 5.0
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

# backend/scripts/poll_worker.py -> parents[1] == backend/ (so `import app.*` works)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import database  # noqa: E402
from app.services.sync_service import SyncService  # noqa: E402
from app.subprocess import Account  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Per-account WeCom DM poll worker")
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--config-dir", default="")
    parser.add_argument("--self-userid", default="")
    parser.add_argument("--poll-sec", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account = Account(
        id=args.account_id,
        name=args.name or args.account_id,
        config_dir=args.config_dir or None,
        self_userid=args.self_userid or "",
    )

    database.connect()
    svc = SyncService(account)
    svc.load_state()

    print(
        f"[{account.id}] poll worker started (self={svc.self_userid or 'auto'}, "
        f"poll={args.poll_sec}s, pid={os.getpid()})",
        flush=True,
    )

    while True:
        try:
            svc.sync_once()
        except Exception:
            traceback.print_exc()
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
