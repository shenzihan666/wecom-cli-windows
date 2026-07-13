"""Subprocess layer: per-account wecom-cli context management.

Purpose
-------
This layer is the seam for **multi-account** support. wecom-cli keeps its
credentials in a config directory (``WECOM_CLI_CONFIG_DIR``); running several
accounts side by side just means routing each RPC call to the right config
sandbox (and, later, owning a long-lived wecom-cli process per account).

Right now it exposes a single ``DEFAULT_ACCOUNT`` so the services layer can be
written account-aware without the full multi-account machinery being built yet.
"""

from .account_manager import DEFAULT_ACCOUNT, Account, AccountManager, account_manager

__all__ = ["Account", "AccountManager", "DEFAULT_ACCOUNT", "account_manager"]
