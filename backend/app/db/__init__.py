"""Persistence layer: SQLite storage for per-account sync state."""

from .database import Database, database
from .repository import AccountRepository

__all__ = ["Database", "database", "AccountRepository"]
