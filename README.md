# wecom_CLI_TEST

Local **WeCom DM sync** web UI on top of [`wecom-cli`](https://github.com/WecomTeam/wecom-cli). Left: private-chat list. Right: thread + text send. Background poll keeps cache close to live (not true push).

## Requirements

- Python 3.9+ (stdlib only; no pip deps)
- `wecom-cli` on `PATH` (`npm install -g @wecom/cli`), already `wecom-cli init`
- Optional: `ffmpeg` / `ffprobe` for voice (AMR→MP3) and video (HEVC→H.264)

## Quick start

```bash
wecom-cli init          # once; Bot ID/Secret or QR
python3 server.py       # http://127.0.0.1:8765
# optional CLI dump:
python3 fetch_latest_msgs.py
```

Self-check (no network):

```bash
python3 check_self.py
```

## Layout

```
.
├── server.py              # HTTP UI + 5s DM poller + disk cache
├── wecom_rpc.py           # wecom-cli JSON helpers + media download/convert
├── fetch_latest_msgs.py   # one-shot CLI message dump
├── check_self.py          # assert-based merge self-check
├── static/index.html      # single-page chat UI
├── data/cache.json        # runtime cache (gitignored)
└── media/                 # downloaded/converted media (gitignored)
```

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `SELF_USERID` | `WangGuoZheng` | Your WeCom userid (outbound bubbles) |
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
