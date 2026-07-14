# Repository Agent Guide

This file applies to the whole repository. `frontend/AGENTS.md` adds frontend-specific Vite+
instructions and takes precedence for files in that subtree.

## Project background

WeCom DM Sync is a local WeCom private-chat management app built on `wecom-cli`. A FastAPI API
and per-account polling workers cache recent DMs in SQLite; a Vue 3 SPA provides account, chat,
blacklist, settings, and log pages; Electron optionally owns the local backend and frontend
processes. The system polls rather than receiving true push events.

## Documentation-first workflow

1. Start with [`docs/README.md`](docs/README.md) and open the linked topic document.
2. Before guessing project behavior, search docs: `rg -n "<keyword>" docs`.
3. Verify important claims against implementation, configuration, and tests.
4. If docs and code disagree, treat executable code/config/tests as authoritative and update docs
   in the same change.
5. Keep docs focused on current behavior; label future designs explicitly as plans.

Topic index: architecture and invariants in `docs/architecture.md`, setup and validation in
`docs/development.md`, contracts in `docs/api.md`, and configuration/troubleshooting in
`docs/operations.md`.

## Repository boundaries

- `backend/app/api` and `schemas`: transport and API contracts.
- `backend/app/services`: business workflows and policies.
- `backend/app/core`: thin WeCom/media/platform adapters; do not put business policy here.
- `backend/app/db`: schema and repositories; keep SQL out of routes and services.
- `backend/app/subprocess` plus `backend/scripts`: per-account worker lifecycle.
- `frontend/src`: Vue application; `electron`: desktop process orchestration.

Preserve `account_id` isolation and pass each account's `config_dir` through every `wecom-cli`
call. Remember the API and workers are separate processes sharing SQLite. Preserve first-sync
media-blacklist baselining and auto-reply cursor semantics unless the requested behavior changes.

## Change and verification rules

- Make the smallest coherent change; add regression coverage for changed behavior.
- API changes must update Pydantic schemas, frontend types/client code, and `docs/api.md`.
- Never commit `.env`, credentials, `data/`, `media/`, logs, node_modules, or generated builds.
- Do not initialize credentials, delete local data, or expose the unauthenticated API without an
  explicit request.
- Backend checks: `uv run pytest` and `uv run pre-commit run --all-files`.
- Frontend checks: from `frontend/`, run `vp check`, `vp test`, and `pnpm build`.
- Electron changes: run root `pnpm typecheck`.
