"""Cross-platform process pause/resume manager.

On **Windows** there is no ``SIGSTOP``/``SIGCONT``, so "pause" is implemented
via Job Objects: every process in the job is suspended with
``NtSuspendProcess`` / ``NtResumeProcess`` -- the process tree freezes in place
(no state lost) instead of being killed.

On **Unix** (macOS/Linux) the native ``SIGSTOP`` / ``SIGCONT`` signals give us
the same semantics with far less ceremony: we walk the process tree with
``psutil`` and send the signal to every descendant.

``get_job_manager()`` returns the right implementation for the current platform.
Both expose the same interface (``create_job`` / ``add_process`` /
``suspend_job`` / ``resume_job`` / ``terminate_job`` / ``is_suspended``).
"""

from __future__ import annotations

import logging
import signal
import sys

logger = logging.getLogger(__name__)


class _UnixJobManager:
    """Tracks one process tree per account id; suspends/resumes via SIGSTOP/SIGCONT."""

    def __init__(self) -> None:
        self._pids: dict[str, int] = {}
        self._suspended: dict[str, bool] = {}

    def create_job(self, account_id: str) -> None:
        # No persistent kernel object needed on Unix; just reset bookkeeping.
        self._suspended[account_id] = False
        return None

    def add_process(self, account_id: str, pid: int) -> bool:
        self._pids[account_id] = pid
        return True

    def _tree_pids(self, account_id: str) -> list[int]:
        import psutil

        pid = self._pids.get(account_id)
        if pid is None:
            return []
        pids = [pid]
        try:
            proc = psutil.Process(pid)
            pids.extend(child.pid for child in proc.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return pids

    def suspend_job(self, account_id: str) -> bool:
        if self._suspended.get(account_id):
            return True
        ok = True
        for pid in self._tree_pids(account_id):
            try:
                # SIGSTOP can't be caught/ignored, so the process halts immediately.
                import os

                os.kill(pid, signal.SIGSTOP)
            except ProcessLookupError:
                continue
            except Exception:
                logger.exception("Failed to SIGSTOP pid=%s", pid)
                ok = False
        if ok:
            self._suspended[account_id] = True
        return ok

    def resume_job(self, account_id: str) -> bool:
        if not self._suspended.get(account_id):
            return True
        ok = True
        for pid in self._tree_pids(account_id):
            try:
                import os

                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                continue
            except Exception:
                logger.exception("Failed to SIGCONT pid=%s", pid)
                ok = False
        if ok:
            self._suspended[account_id] = False
        return ok

    def terminate_job(self, account_id: str) -> bool:
        # Actual killing is handled by process_manager's _kill_tree (psutil).
        self._pids.pop(account_id, None)
        self._suspended.pop(account_id, None)
        return True

    def is_suspended(self, account_id: str) -> bool:
        return self._suspended.get(account_id, False)


class _WindowsJobManager:
    """Tracks one Job Object per account id; suspends/resumes its process tree.

    All Win32 ctypes imports are deferred to method bodies so this module can be
    imported on non-Windows platforms without raising ``OSError`` from
    ``ctypes.WinDLL``.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, int] = {}
        self._processes: dict[str, int] = {}
        self._suspended: dict[str, bool] = {}

    def _load(self):
        import ctypes

        PROCESS_ALL_ACCESS = 0x1F0FFF
        PROCESS_SUSPEND_RESUME = 0x0800
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        return ctypes, kernel32, ntdll, PROCESS_ALL_ACCESS, PROCESS_SUSPEND_RESUME

    def create_job(self, account_id: str) -> int | None:
        ctypes, kernel32, *_ = self._load()
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            logger.error("Failed to create job object: %s", ctypes.get_last_error())
            return None
        self._jobs[account_id] = job_handle
        self._suspended[account_id] = False
        return job_handle

    def add_process(self, account_id: str, pid: int) -> bool:
        ctypes, kernel32, _, PROCESS_ALL_ACCESS, _ = self._load()
        job_handle = self._jobs.get(account_id)
        if job_handle is None:
            logger.error("No job object for %s", account_id)
            return False

        process_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not process_handle:
            logger.error("Failed to open process %s: %s", pid, ctypes.get_last_error())
            return False

        if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
            logger.error("Failed to assign process to job: %s", ctypes.get_last_error())
            kernel32.CloseHandle(process_handle)
            return False

        self._processes[account_id] = process_handle
        return True

    def suspend_job(self, account_id: str) -> bool:
        if account_id not in self._jobs:
            logger.error("No job object for %s", account_id)
            return False
        if self._suspended.get(account_id):
            return True
        try:
            pids = self._get_job_processes(account_id)
            for pid in pids:
                self._suspend_process(pid)
            self._suspended[account_id] = True
            return True
        except Exception:
            logger.exception("Failed to suspend job for %s", account_id)
            return False

    def resume_job(self, account_id: str) -> bool:
        if account_id not in self._jobs:
            logger.error("No job object for %s", account_id)
            return False
        if not self._suspended.get(account_id):
            return True
        try:
            pids = self._get_job_processes(account_id)
            for pid in pids:
                self._resume_process(pid)
            self._suspended[account_id] = False
            return True
        except Exception:
            logger.exception("Failed to resume job for %s", account_id)
            return False

    def terminate_job(self, account_id: str) -> bool:
        ctypes, kernel32, *_ = self._load()
        job_handle = self._jobs.get(account_id)
        if job_handle is None:
            return True
        try:
            kernel32.TerminateJobObject(job_handle, 1)
            kernel32.CloseHandle(job_handle)
            process_handle = self._processes.pop(account_id, None)
            if process_handle:
                kernel32.CloseHandle(process_handle)
            del self._jobs[account_id]
            self._suspended.pop(account_id, None)
            return True
        except Exception:
            logger.exception("Failed to terminate job for %s", account_id)
            return False

    def is_suspended(self, account_id: str) -> bool:
        return self._suspended.get(account_id, False)

    def _get_job_processes(self, account_id: str) -> list[int]:
        import psutil

        ctypes, kernel32, *_ = self._load()
        process_handle = self._processes.get(account_id)
        if not process_handle:
            return []
        try:
            main_pid = kernel32.GetProcessId(process_handle)
            if not main_pid:
                return []
            proc = psutil.Process(main_pid)
            pids = [main_pid]
            pids.extend(child.pid for child in proc.children(recursive=True))
            return pids
        except Exception:
            return []

    def _suspend_process(self, pid: int) -> bool:
        ctypes, kernel32, ntdll, _, PROCESS_SUSPEND_RESUME = self._load()
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ntdll.NtSuspendProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)

    def _resume_process(self, pid: int) -> bool:
        ctypes, kernel32, ntdll, _, PROCESS_SUSPEND_RESUME = self._load()
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ntdll.NtResumeProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)


_job_manager: _UnixJobManager | _WindowsJobManager | None = None


def get_job_manager() -> _UnixJobManager | _WindowsJobManager:
    """Return the platform-appropriate job manager singleton."""
    global _job_manager
    if _job_manager is None:
        if sys.platform == "win32":
            _job_manager = _WindowsJobManager()
        else:
            _job_manager = _UnixJobManager()
    return _job_manager
