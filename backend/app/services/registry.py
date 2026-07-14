"""Maps an account id to its running :class:`SyncService` (one per account)."""

from __future__ import annotations

import threading

from ..subprocess import account_manager
from .media_blacklist_service import MediaBlacklistService
from .sync_service import SyncService


class ServiceRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, SyncService] = {}

    def get(self, account_id: str = "default") -> SyncService:
        with self._lock:
            svc = self._services.get(account_id)
            if svc is None:
                account = account_manager.get(account_id)
                media_blacklist = MediaBlacklistService(account.id)
                svc = SyncService(account, update_handlers=[media_blacklist.process])
                self._services[account_id] = svc
            return svc

    def all(self) -> list[SyncService]:
        with self._lock:
            return list(self._services.values())

    def remove(self, account_id: str) -> None:
        with self._lock:
            self._services.pop(account_id, None)


service_registry = ServiceRegistry()
