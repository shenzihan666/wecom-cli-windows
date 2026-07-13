"""One OS subprocess per account, running the poll loop.

Ported (trimmed down) from the wecom-cua-windows reference project's
``DeviceManager``: instead of an in-process background thread per account, we
spawn ``backend/scripts/poll_worker.py`` as its own process. This gives us:

- real crash isolation (one account's worker dying doesn't touch the API
  process or other accounts),
- real pause/resume via Windows Job Objects (``NtSuspendProcess`` /
  ``NtResumeProcess``) instead of an in-memory flag,
- a hard ``taskkill /T`` to fully stop an account.

Not ported from the reference project: DroidRun port allocation and
WebSocket live log streaming (not applicable here). Worker output is
redirected to a per-account log file instead.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

import psutil

from ..config import settings
from ..core.windows_job import get_job_manager
from .account_manager import Account

logger = logging.getLogger(__name__)

_WORKER_SCRIPT = "poll_worker.py"


class AccountProcessManager:
    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen] = {}
        self._logfiles: dict[str, object] = {}
        self._job_manager = get_job_manager()

    # ---- lifecycle ---------------------------------------------------------- #
    def start(self, account: Account, poll_sec: float) -> bool:
        existing = self._processes.get(account.id)
        if existing is not None and existing.poll() is None:
            if self._job_manager.is_suspended(account.id):
                return self.resume(account.id)
            return True  # already running

        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = settings.logs_dir / f"{account.id}.log"
        logfile = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - kept open for process lifetime

        script_path = settings.project_root / "backend" / "scripts" / _WORKER_SCRIPT
        uv_path = shutil.which("uv") or "uv"
        args = [
            uv_path,
            "run",
            "python",
            str(script_path),
            "--account-id",
            account.id,
            "--name",
            account.name,
            "--config-dir",
            account.config_dir or "",
            "--self-userid",
            account.self_userid or "",
            "--poll-sec",
            str(poll_sec),
        ]

        try:
            # Plain arg list (no shell): avoids cmd.exe re-quoting the script
            # path/args, and uv resolves to a real .exe so no shim is needed.
            process = subprocess.Popen(  # noqa: S603
                args,
                cwd=str(settings.project_root),
                stdout=logfile,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception:
            logger.exception("Failed to start poll worker for %s", account.id)
            logfile.close()
            return False

        self._processes[account.id] = process
        self._logfiles[account.id] = logfile

        self._job_manager.create_job(account.id)
        self._job_manager.add_process(account.id, process.pid)
        return True

    def pause(self, account_id: str) -> bool:
        if not self._is_alive(account_id):
            return False
        return self._job_manager.suspend_job(account_id)

    def resume(self, account_id: str) -> bool:
        if not self._is_alive(account_id):
            return False
        return self._job_manager.resume_job(account_id)

    def stop(self, account_id: str) -> bool:
        process = self._processes.pop(account_id, None)
        self._job_manager.terminate_job(account_id)
        logfile = self._logfiles.pop(account_id, None)
        if logfile is not None:
            try:
                logfile.close()
            except Exception:
                pass

        if process is None:
            return True
        if process.poll() is not None:
            return True  # already exited

        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=5.0,
            )
        except Exception:
            logger.exception("taskkill failed for account %s (pid=%s)", account_id, process.pid)
            try:
                process.terminate()
            except Exception:
                pass
        return True

    def stop_all(self) -> None:
        for account_id in list(self._processes.keys()):
            self.stop(account_id)

    # ---- status -------------------------------------------------------------- #
    def status(self, account_id: str) -> dict:
        process = self._processes.get(account_id)
        if process is None or process.poll() is not None:
            return {"state": "stopped", "pid": None}
        if self._job_manager.is_suspended(account_id):
            return {"state": "paused", "pid": process.pid}
        return {"state": "running", "pid": process.pid}

    def _is_alive(self, account_id: str) -> bool:
        process = self._processes.get(account_id)
        return process is not None and process.poll() is None

    # ---- orphan cleanup -------------------------------------------------------- #
    def cleanup_orphans(self) -> int:
        """Kill leftover poll_worker.py process trees from a previous run/crash.

        Best-effort: failures are logged, never raised.
        """
        try:
            matches = self._iter_matching_processes()
        except Exception:
            logger.exception("Orphan scan failed")
            return 0

        roots = self._select_tree_roots(matches)
        killed = 0
        for root in roots:
            try:
                killed += self._kill_tree(root)
            except Exception:
                logger.exception("Failed to kill orphan poll worker pid=%s", root.pid)
        return killed

    @staticmethod
    def _iter_matching_processes() -> list[psutil.Process]:
        matches: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if _WORKER_SCRIPT in cmdline and "--account-id" in cmdline:
                matches.append(proc)
        return matches

    @staticmethod
    def _select_tree_roots(procs: list[psutil.Process]) -> list[psutil.Process]:
        if not procs:
            return []
        pid_set = {p.pid for p in procs}
        roots: list[psutil.Process] = []
        for proc in procs:
            try:
                ancestors = proc.parents()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if any(a.pid in pid_set for a in ancestors):
                continue
            roots.append(proc)
        return roots

    @staticmethod
    def _kill_tree(proc: psutil.Process, timeout: float = 5.0) -> int:
        try:
            descendants = proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            descendants = []
        targets = [*descendants, proc]
        for t in targets:
            try:
                t.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(targets, timeout=timeout)
        for t in alive:
            try:
                t.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return len(targets)


account_process_manager = AccountProcessManager()
