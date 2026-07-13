"""Subprocess layer: per-account wecom-cli context management + process control.

Purpose
-------
This layer is the seam for multi-account support. wecom-cli keeps its
credentials in a config directory (``WECOM_CLI_CONFIG_DIR``); running several
accounts side by side means routing each RPC call to the right config
sandbox (``AccountManager``) and owning a long-lived poll-worker process per
account (``AccountProcessManager``, see ``process_manager.py``).
"""

from .account_manager import DEFAULT_ACCOUNT, Account, AccountManager, account_manager
from .process_manager import AccountProcessManager, account_process_manager

__all__ = [
    "Account",
    "AccountManager",
    "DEFAULT_ACCOUNT",
    "account_manager",
    "AccountProcessManager",
    "account_process_manager",
]
