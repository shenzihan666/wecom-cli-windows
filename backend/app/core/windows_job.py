"""Windows Job Objects: real process pause/resume.

Ported from the wecom-cua-windows reference project's device manager (which
uses this to pause/resume Android automation subprocesses). Windows has no
SIGSTOP/SIGCONT, so "pause" is implemented by walking every process in a Job
Object and calling ``NtSuspendProcess``/``NtResumeProcess`` on each -- the
process tree freezes in place (no state lost) instead of being killed.
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_SUSPEND_RESUME = 0x0800

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)


class WindowsJobManager:
    """Tracks one Job Object per account id; suspends/resumes its process tree."""

    def __init__(self) -> None:
        self._jobs: dict[str, int] = {}
        self._processes: dict[str, int] = {}
        self._suspended: dict[str, bool] = {}

    def create_job(self, account_id: str) -> int | None:
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            logger.error("Failed to create job object: %s", ctypes.get_last_error())
            return None
        self._jobs[account_id] = job_handle
        self._suspended[account_id] = False
        return job_handle

    def add_process(self, account_id: str, pid: int) -> bool:
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
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ntdll.NtSuspendProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)

    def _resume_process(self, pid: int) -> bool:
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return ntdll.NtResumeProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)


_job_manager: WindowsJobManager | None = None


def get_job_manager() -> WindowsJobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = WindowsJobManager()
    return _job_manager
