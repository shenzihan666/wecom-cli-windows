"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import HTTPException, Query

from ..services import SyncService, service_registry


def get_service(
    account: str = Query("default", description="Account id (multi-account)"),
) -> SyncService:
    try:
        return service_registry.get(account)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account}") from None
