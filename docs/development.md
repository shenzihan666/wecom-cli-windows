# 开发指南

## 环境要求

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ 与 pnpm
- 全局可用的 `wecom-cli`：`npm install -g @wecom/cli`
- 前端使用 [Vite+](https://viteplus.dev/guide/) 的 `vp` 命令
- 可选：`ffmpeg`、`ffprobe`，用于语音和视频转码

首次准备：

```bash
wecom-cli init
uv sync
pnpm install
cd frontend
vp install
cd ..
uv run pre-commit install --install-hooks
```

不要把 Bot Secret、访问令牌或本地凭据目录提交到仓库。

## 启动方式

### Electron 一体开发

从项目根目录启动后端、Vite 开发服务器和 Electron：

```bash
./dev.sh
```

关闭 Electron 窗口后，主进程会清理它启动的前后端子进程。

### 浏览器 + 前端热更新

分别启动后端和前端：

```bash
# 终端 1：项目根目录
uv run python backend/run.py

# 终端 2
cd frontend
pnpm dev
```

前端默认访问 `http://localhost:5173`，并将 `/api`、`/media`、`/ws` 代理到
`http://127.0.0.1:8765`。

### 后端直接提供构建后的 SPA

```bash
cd frontend
pnpm build
cd ..
uv run python backend/run.py
```

访问 `http://127.0.0.1:8765`；交互式 OpenAPI 位于
`http://127.0.0.1:8765/docs`。

## 代码地图

- 新增或修改 REST 接口：`backend/app/schemas/models.py` 与
  `backend/app/api/routes.py`。
- 新增业务流程或策略：`backend/app/services/`。
- 修改企微命令调用：`backend/app/core/wecom_api.py`、`backend/app/core/rpc.py`。
- 修改账号或 worker 生命周期：`backend/app/subprocess/` 与
  `backend/scripts/poll_worker.py`。
- 修改表结构或查询：`backend/app/db/`，通过 repository 暴露。
- 修改页面和交互：`frontend/src/pages/`、`frontend/src/components/`。
- 修改前端请求或共享类型：`frontend/src/api.ts`、`frontend/src/types.ts`。
- 修改桌面启动与打包：`electron/`、`electron-builder.yml`。

前端目录还有更具体的 `frontend/AGENTS.md`，处理前端文件时同时遵守其中的 Vite+
工具链约定。

## 工程约定

### 后端

- Python 目标版本为 3.11，Ruff 行宽为 100，启用 `E`、`F`、`I`、`UP`、`B` 规则。
- 路由只负责协议层；业务逻辑放在 `services/`，底层适配放在 `core/`。
- 所有账号级代码必须保留 `account_id` 和 `config_dir`，不能隐式退化为默认账号。
- 记住 API 主进程与 worker 是不同进程；内存锁不能解决跨进程一致性问题。
- SQLite 变更必须考虑 WAL 下的并发写入、账号隔离和旧数据库兼容。
- 上游消息 payload 按消息类型变化，边界处应防御缺失字段，不要假定固定形状。
- 捕获异常时保留可诊断日志；策略模块失败不应无故中断同步主流程。

### 前端与 Electron

- 使用 Vue 3 组合式 API、相对 API 路径和现有 Vue Router 结构。
- 前后端契约变化时，同步更新 Pydantic 模型、`frontend/src/types.ts` 和
  `docs/api.md`。
- Vite 配置从 `vite-plus` 导入，不要绕开仓库现有的 Vite+ 工具链。
- Electron 主进程负责子进程生命周期；新增启动路径时必须保留超时、健康检查和退出清理。
- 后端端口、Vite 代理和 Electron `BACKEND_PORT` 必须保持一致。

## 测试与验证

根据改动范围运行最小充分验证；跨层变更应运行相关层的全部检查。

```bash
# 后端全部测试
uv run pytest

# 全仓库 pre-commit：格式、lint、文件卫生和 secret 扫描
uv run pre-commit run --all-files

# 前端格式、lint、类型检查和测试
cd frontend
vp check
vp test
pnpm build

# Electron 类型检查（项目根目录）
cd ..
pnpm typecheck
```

修改以下行为时应补充回归测试：

- 消息合并、pending 回显或 `media_id` 轮换。
- 第一次同步基线与媒体自动拉黑。
- 自动回复候选选择、黑名单、cursor 去重或熔断。
- 多账号隔离、进程启停或 SQLite repository。
- API 请求/响应字段以及前端依赖这些字段的分支。

## 提交与文档

Git hooks 要求 Conventional Commits，例如 `feat: ...`、`fix: ...`、`docs: ...`。
不要跳过 hooks。代码改变架构、接口、配置、限制或排障方式时，在同一次变更中更新
`docs/`；若代码与文档冲突，以可执行代码和测试为准并修正文档。
