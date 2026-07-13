# wecom_CLI_TEST

Local **WeCom DM sync** web UI on top of [`wecom-cli`](https://github.com/WecomTeam/wecom-cli). Left: private-chat list. Right: thread + text send. Background poll keeps cache close to live (not true push).

## Requirements

- Python 3.11+ managed by [`uv`](https://docs.astral.sh/uv/)
- `wecom-cli` on `PATH` (`npm install -g @wecom/cli`), already `wecom-cli init`
- Optional: `ffmpeg` / `ffprobe` for voice (AMR→MP3) and video (HEVC→H.264)

## Quick start

```bash
wecom-cli init                      # once; Bot ID/Secret or QR
uv sync                             # create .venv + install deps
uv run python backend/run.py        # http://127.0.0.1:8765
# or with autoreload:
uv run uvicorn app.main:app --app-dir backend --reload --port 8765
```

Interactive API docs: `http://127.0.0.1:8765/docs`

Self-check (no network):

```bash
uv run python backend/tests/test_merge.py
```

## Git hooks

This repo uses the [pre-commit](https://pre-commit.com/) framework (config in
`.pre-commit-config.yaml`). One-time setup for new contributors:

```bash
uv sync                                   # installs pre-commit (dev dep)
uv run pre-commit install --install-hooks # wires up all three hook stages
```

What runs, and when:

| Stage | Hooks | Scope |
|-------|-------|-------|
| **pre-commit** | ruff (lint `--fix` + format), whitespace/EOF/large-file/merge-conflict hygiene, `detect-secrets`, `detect-private-key` | staged files only (fast, < ~10s) |
| **commit-msg** | Conventional Commits (`feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`, `revert`) — merge / `revert:` / `fixup!` messages are allowed | the commit message |
| **pre-push** | `uv run pytest` (full suite; it's small) | whole repo |

Useful commands:

```bash
uv run pre-commit run --all-files   # run every hook against the whole repo
uv run pre-commit autoupdate        # bump pinned hook versions
```

**Escape hatch** (use sparingly): `git commit --no-verify` / `git push --no-verify`
skip the hooks. In CI the hooks do not auto-run on git operations; run the same
checks explicitly with `uv run pre-commit run --all-files` and `uv run pytest`.

## Architecture

FastAPI backend, layered top → bottom:

```
api        -> HTTP presentation (FastAPI routers, pydantic schemas)
subprocess -> per-account wecom-cli context (multi-account seam; single default account today)
services   -> business logic (sync loop, disk cache, conversation state, send)
core       -> thin wecom-cli JSON-RPC + media download/convert
```

Each core call accepts an optional `config_dir`, so the `subprocess` layer can
later route requests to per-account wecom-cli credential sandboxes.

## Layout

```
.
├── pyproject.toml              # uv project + deps
├── backend/
│   ├── run.py                  # dev entrypoint (uvicorn)
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan (poller), static UI
│   │   ├── config.py           # env-based settings
│   │   ├── api/                # routers + deps (HTTP layer)
│   │   ├── schemas/            # pydantic models
│   │   ├── services/           # sync engine + per-account registry
│   │   ├── subprocess/         # account manager (multi-account foundation)
│   │   └── core/               # wecom-cli RPC + media helpers
│   └── tests/test_merge.py     # assert-based merge self-check
├── static/index.html           # single-page chat UI
├── data/cache.json             # runtime cache (gitignored)
├── media/                      # downloaded/converted media (gitignored)
└── server.py, wecom_rpc.py …   # legacy experimental scripts (superseded)
```

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `SELF_USERID` | *(auto)* | Your WeCom userid (outbound bubbles). Auto-detected from DM senders if unset. |
| `WECOM_POLL_SEC` | `5` | Backend poll interval (seconds) |
| `WECOM_WEB_HOST` | `127.0.0.1` | Bind host |
| `WECOM_WEB_PORT` | `8765` | Bind port |
| `WECOM_CLI_CONFIG_DIR` | `~/.config/wecom` | Isolate multi-sandbox credentials |

Example: `WECOM_POLL_SEC=10 SELF_USERID=YourId python3 server.py`

## API (local)

- `GET /api/conversations` — DM list (+ empty contacts)
- `GET /api/messages?userid=` — thread from cache
- `POST /api/send` — `{ "userid", "content" }` text only
- `GET /api/status` — sync health
- `GET /media/<file>` — media (supports `Range`)

## Limits (WeCom / wecom-cli)

- History ~**7 days**; DMs only in this app (no groups in UI)
- Send **text only** (no image/file/sticker send)
- Custom stickers arrive as `[自定义表情]` — no media
- Reading here does **not** clear client unread badges
- Message MCP auth in admin may **expire** (days–weeks); re-authorize / `wecom-cli init` with same Bot ID+Secret — not necessarily a new bot
- `media_id` can rotate between polls; cache falls back by send time
- Rate limit e.g. `850005` if polled too hard

## Multi-sandbox

Point each environment at its own config dir:

```bash
export WECOM_CLI_CONFIG_DIR=/path/sandbox-a/wecom-config
wecom-cli init && python3 server.py
```
