# 运行与排障

## 配置来源

### 环境变量

后端从项目根目录的 `.env` 和进程环境读取：

- `HOST`：监听地址，默认 `127.0.0.1`。
- `PORT`：监听端口，默认 `8765`。
- `POLL_SEC`：SQLite 尚未保存轮询设置时的默认秒数，默认 `5`。
- `SELF_USERID`：默认账号的己方企微 user ID；为空时尝试从私聊消息推断。

为兼容旧版本，也接受 `WECOM_WEB_HOST`、`WECOM_WEB_PORT` 和 `WECOM_POLL_SEC`。
`WECOM_CLI_CONFIG_DIR` 由 `wecom-cli` 使用；未给账号指定 `config_dir` 时，worker 继承
环境中的该值。

### UI 持久化设置

设置页将以下全局值写入 SQLite `app_settings`：

- 轮询间隔 `poll_sec`
- AI 开关 `ai_enabled`
- AI 服务地址 `ai_server_url`
- AI 超时 `ai_timeout_sec`
- AI 系统提示词 `ai_system_prompt`
- AI 回复最大长度 `ai_reply_max_length`

SQLite 中已有的 `poll_sec` 优先于环境默认值。修改轮询间隔会重启所有正在运行的
worker。

### 每账号配置

每个账号可设置独立 `config_dir` 和 `self_userid`。多账号部署应先为每个凭据沙箱完成
`wecom-cli init`，再在账号页填入对应目录。不要让多个账号复用同一个非空
`config_dir`。

## 本地数据

- `data/wecom.db`：账号、设置、同步快照、黑名单和回复 cursor。
- `data/logs/{account_id}.log`：账号 worker 日志。
- `data/logs/{account_id}.log.1`：最近一次轮转备份。
- `data/cache.json`：旧版缓存；首次运行可迁移到 SQLite。
- `media/`：已下载及转码的消息媒体。
- `frontend/dist/`：前端构建产物。

`data/`、`media/` 和构建产物均被 Git 忽略。备份数据库前应停止应用，至少同时保留
`wecom.db`、`wecom.db-wal` 和 `wecom.db-shm`，或使用 SQLite 在线备份方式；不要在
worker 写入期间只复制主数据库文件。

## 启动检查

```bash
# 后端健康与默认账号同步状态
curl -sS "http://127.0.0.1:8765/api/status"

# 全部账号及 worker 状态
curl -sS "http://127.0.0.1:8765/api/accounts"
```

后端启动时会创建运行目录、检查 `ffmpeg`/`ffprobe`、打开数据库、清理遗留 worker，
并启动所有已启用账号。媒体工具缺失只会发出警告，不会阻止应用启动。

## 账号运维

- `running`：worker 正在按轮询间隔同步。
- `paused`：进程仍存在但被操作系统挂起。
- `stopped`：当前主进程没有存活的 worker。

通过账号页启动或暂停账号。创建的新账号默认不启动；应用重启后只恢复标记为启用的
账号。删除账号会先停止 worker；系统禁止删除最后一个账号。

日志页通过 `/ws/logs/{account_id}` 展示每账号日志。排查同步或自动回复问题时，先查看
对应 worker 日志，再检查 `/api/status?account=<id>` 中的 `error` 与 `last_sync`。

## 常见故障

### 后端无法启动

1. 确认 Python 3.11+、`uv` 可用并已执行 `uv sync`。
2. 确认 8765 端口没有被其他程序占用。
3. 直接运行 `uv run python backend/run.py` 获取完整错误。
4. 若 API 正常但浏览器首页失败，执行 `cd frontend && pnpm build` 生成
   `frontend/dist/index.html`。

### worker 启动后没有同步

1. 在账号页确认状态为 `running`。
2. 检查 `data/logs/{account_id}.log`。
3. 运行 `wecom-cli` 相关命令或重新执行 `wecom-cli init`，确认凭据未过期。
4. 多账号时确认 `config_dir` 指向该账号实际初始化过的目录。
5. 检查 `/api/status?account=<id>` 的错误和最近同步时间。

### 出现 `wecom-cli not found` 或 RPC 超时

- 确认 `wecom-cli` 位于启动应用进程的 `PATH` 中。
- RPC 单次调用默认 30 秒超时；检查网络、企微授权和上游 CLI 是否卡住。
- Electron 从图形环境启动时可能继承不同的 `PATH`，可先从终端运行 `./dev.sh` 验证。

### 授权过期或没有消息

企微消息 MCP 授权可能在数天到数周后过期。使用原 Bot ID/Secret 或扫码重新执行
`wecom-cli init`，通常无需新建 Bot。当前只请求私聊，且上游可用历史通常约 7 天。

### 限流错误

错误码如 `850005` 通常表示轮询过频。提高设置页的 `poll_sec`，减少同时运行的账号，
并等待上游限流窗口恢复。不要通过并发重试放大请求量。

### 自动回复不工作

依次确认：

1. 设置页已开启 AI，服务地址可访问且实现 `POST /chat`。
2. 账号有明确或可推断的 `self_userid`；未知时 worker 会记录
   `auto-reply inactive`。
3. 客户不在该账号黑名单中，最新消息是客户发来的非空文本。
4. 日志中没有 `circuit open`；连续失败会熔断 120 秒。
5. 同一条入站消息的 cursor 是否已推进。为防重复发送，发送失败的回复也不会自动重试。

### 客户被自动加入黑名单

首次同步完成后，客户新发送图片或视频会触发自动拉黑。这是当前业务策略，不是同步
错误。可在黑名单页手动移除；若要改变策略，应修改
`MediaBlacklistService` 并补充基线与增量场景测试。

### 媒体无法播放

- 确认 `ffmpeg` 和 `ffprobe` 位于 `./ffmpeg`、`./bin` 或 `PATH`。
- 检查 worker 日志中的下载、AMR→MP3 或 HEVC→H.264 转码错误。
- `media_id` 可能在轮询之间变化；系统会按发送者、发送时间和消息类型尝试复用缓存。

### SQLite `database is locked`

SQLite 已启用 WAL 和 5 秒 `busy_timeout`。持续锁冲突通常意味着异常遗留进程或高频
并发写入：

1. 正常退出并重启应用，让启动清理逻辑处理遗留 worker。
2. 检查是否同时启动了多个后端实例。
3. 保留数据库备份后再做进一步诊断；不要直接删除 `wecom.db`。

### Electron 白屏或启动超时

- 开发模式检查 `[vite]` 与 `[backend]` 日志。
- 确认 `localhost:5173` 和 `127.0.0.1:8765` 可用。
- 生产模式确认 `frontend/dist/index.html` 存在。
- 当前安装包不包含 Python 后端、`uv`、`wecom-cli` 或 ffmpeg，目标机器必须自行安装。

## 安全与限制

- 服务没有认证，默认只应绑定 `127.0.0.1`。
- 不要提交 `.env`、`data/`、`media/`、凭据沙箱或日志。
- 日志和数据库可能包含客户 ID、姓名与消息内容，按敏感业务数据保护。
- 当前只支持私聊和文本发送；不支持清除企微客户端未读状态。
- 自定义贴纸可能只显示为文本占位，媒体历史受上游窗口限制。
