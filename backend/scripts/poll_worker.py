"""Standalone polling subprocess for one account.

Spawned by ``AccountProcessManager`` (one process per account) instead of
running as an in-process thread. This gives us real OS-level process control
to stop and suspend/resume (see ``app.core.job_manager``) without losing
in-memory state. stdout/stderr are redirected by the parent to a per-account
log file under ``data/logs/{account_id}.log``.

Usage (spawned by the parent, not meant to be run manually):
    uv run python backend/scripts/poll_worker.py \
        --account-id default --config-dir "" --self-userid "" --poll-sec 5.0
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# backend/scripts/poll_worker.py -> parents[1] == backend/ (so `import app.*` works)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.runtime_settings import get_ai_settings  # noqa: E402
from app.db import database  # noqa: E402
from app.services.auto_reply_service import AutoReplyService  # noqa: E402
from app.services.media_blacklist_service import MediaBlacklistService  # noqa: E402
from app.services.sync_service import SyncService  # noqa: E402
from app.subprocess import Account  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("poll_worker")

# Log rotation is handled by the parent process (AccountProcessManager) right
# before (re)opening the log file and spawning this worker. The parent owns the
# file descriptor, so only it can rotate safely — renaming the inherited fd in
# the child would silently keep writing into the renamed backup.


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
    media_blacklist = MediaBlacklistService(account.id)
    svc = SyncService(account, update_handlers=[media_blacklist.process])
    svc.load_state()

    logger.info(
        "[%s] poll worker started (self=%s, poll=%ss, pid=%s)",
        account.id,
        svc.self_userid or "auto",
        args.poll_sec,
        os.getpid(),
    )

    while True:
        try:
            svc.sync_once()
        except Exception:
            logger.exception("[%s] sync_once failed", account.id)

        try:
            ai_settings = get_ai_settings()
            if ai_settings.enabled:
                AutoReplyService(svc, ai_settings).process_once()
        except Exception:
            logger.exception("[%s] auto-reply cycle failed", account.id)

        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
