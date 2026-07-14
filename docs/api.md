# API 参考

## 约定

- 默认地址：`http://127.0.0.1:8765`
- 交互式 OpenAPI：`GET /docs`
- 内容类型：JSON；媒体下载和 WebSocket 除外
- 私聊、消息、发送和状态接口通过 `?account=<account_id>` 选择账号，省略时使用
  `default`
- 未知账号返回 `404`

当前 API 没有身份认证，设计目标是仅在本机回环地址使用。不要直接将端口暴露到局域网
或公网；如需远程访问，应先增加认证、授权、来源限制和 TLS。

## 会话与消息

### `GET /api/conversations`

查询账号的会话摘要。

查询参数：

- `account`：可选，默认 `default`。

响应包含 `self_userid`、`last_sync`、`error` 和 `conversations`。每个会话包含
`userid`、`name`、`last_time`、`last_preview`、`has_messages`、`msg_count`。

### `GET /api/messages`

查询单个联系人的缓存消息。

查询参数：

- `account`：可选，默认 `default`。
- `userid`：必填；为空时返回 `400`。

响应包含联系人信息、宽松类型的原始消息列表、用户名称映射和同步元数据。消息 payload
由 `wecom-cli` 决定，不同 `msgtype` 的字段不同。

### `GET /api/status`

查询账号同步状态。响应包含 `account_id`、`self_userid`、`last_sync`、`syncing`、
`error` 和 `poll_sec`。

### `POST /api/send`

发送文本消息。

```json
{
  "userid": "customer_userid",
  "content": "消息内容"
}
```

查询参数 `account` 可选。成功响应中 `ok=true`，并返回本地 pending 消息；发送失败返回
HTTP `400`，同时提供 `error` 和可选的上游 `raw`。

## 账号管理

### `GET /api/accounts`

返回全部账号及其 worker 状态。状态值为 `running`、`paused` 或 `stopped`。

### `POST /api/accounts`

创建一个默认未启用的账号。

```json
{
  "name": "客服名称",
  "config_dir": "/path/to/wecom-config",
  "self_userid": "optional-userid"
}
```

`name` 为空时使用占位名；首次同步可能根据联系人信息更新展示名。每个非空
`config_dir` 必须唯一，重复时返回 `400`。

### `DELETE /api/accounts/{account_id}`

停止 worker 并删除账号。至少保留一个账号，删除最后一个账号返回 `400`；未知账号返回
`404`。

### `POST /api/accounts/{account_id}/start`

启动或恢复账号 worker，并将账号标记为启用。启动失败返回 `500`。

### `POST /api/accounts/{account_id}/pause`

暂停账号 worker，并将账号标记为未启用。未知账号返回 `404`。

## 全局设置

### `GET /api/settings`

读取持久化的全局轮询与 AI 设置：

- `poll_sec`
- `ai_enabled`
- `ai_server_url`
- `ai_timeout_sec`
- `ai_system_prompt`
- `ai_reply_max_length`

### `PUT /api/settings`

请求体必须包含与读取响应相同的完整字段。`poll_sec`、`ai_timeout_sec` 和
`ai_reply_max_length` 必须大于 0。修改 `poll_sec` 会重启所有正在运行的 worker。

这些值存入 SQLite `app_settings`；环境变量只提供未持久化时的默认值。

## 黑名单

黑名单按账号隔离，所有接口接受可选的 `?account=`。

### `GET /api/blacklist`

返回 `items`，每项包含 `account_id`、`userid`、`name`、`reason`、`created_at`。

### `POST /api/blacklist`

```json
{
  "userid": "customer_userid",
  "name": "客户名称",
  "reason": "原因"
}
```

`userid` 必填。重复添加由 repository 按 `(account_id, userid)` 主键处理。

### `DELETE /api/blacklist/{userid}`

移除账号内的黑名单记录；记录不存在时返回 `404`。

## 媒体

### `GET /media/{filename}`

读取 `media/` 中已下载或转码的文件，支持 HTTP Range。路径会经过解码、规范化和目录
边界检查；非法路径返回 `400`，文件不存在返回 `404`。

## WebSocket 日志

### `WS /ws/logs/{account_id}`

连接后先回放该账号 worker 日志的最近约 200 行，再推送新增日志。JSON 消息格式：

```json
{
  "timestamp": "2026-07-14 10:30:00,123",
  "level": "INFO",
  "message": "日志内容"
}
```

应用层心跳协议：

- 客户端约每 25 秒发送文本 `ping`。
- 服务端回复文本 `pong`。
- 服务端在长时间未收到数据时会发送一次 `ping` 探测。
- 客户端应在断线后退避重连。

## 修改接口时

1. 更新 `backend/app/schemas/models.py`。
2. 更新 `backend/app/api/routes.py` 或 `backend/app/api/logs.py`。
3. 更新 `frontend/src/types.ts` 与 `frontend/src/api.ts`。
4. 检查 Vite 的 `/api`、`/media`、`/ws` 代理是否仍匹配。
5. 补充后端和前端相关测试，并更新本文档。
