"""WeCom DM sync backend (FastAPI).

Layering (top -> bottom):
    api        -> HTTP presentation (FastAPI routers)
    subprocess -> per-account wecom-cli process/context management (multi-account)
    services   -> business logic (sync loop, cache, conversation state)
    core       -> thin wecom-cli JSON-RPC + media helpers
"""

__version__ = "0.1.0"
