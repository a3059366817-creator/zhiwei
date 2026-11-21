# 知微 ZhiWei

> 见微知著，知你所想。

私人 Telegram AI 伙伴。朋友型人格 + 长期记忆（候选 → 确认 → 入库）+ 个人画像 + 人物关系。

本目录是**按《知微 V1.0 产品设计规格》实现的 Python 版本**，规格原文见
[`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)。

---

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 项目初始化、架构搭建、配置/日志/数据库/健康检查/Alembic | ✅ 已完成 |
| P1 | Telegram Bot（aiogram 3，收发消息、命令、访问控制、按钮） | ✅ 已完成 |
| P2 | 模型适配器（Ollama 本地 + Gemini + OpenRouter，主备自动切换） | ✅ 已完成 |
| P3 | 对话与历史管理（多轮上下文、新会话、历史查询） | ✅ 已完成 |
| P4 | 数据库（Neon Postgres + Alembic 迁移） | ✅ 已完成（Neon PostgreSQL 18） |
| P5 | 记忆提取、候选确认、检索 | ✅ 已完成 |
| P6 | 个人画像与人物关系 | ✅ 已完成 |
| P7 | Render 云端部署（电脑关机也能用） | 🟡 配置已备好，等账号 |
| P8 | 安全与验收 | ✅ 已完成（见 [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md)） |

---

## 快速开始（本地）

```powershell
cd D:\develop\AI好友\zhiwei

# 1. 建虚拟环境（用 Python 3.12，uv 已自带）
uv venv --python 3.12 .venv
uv sync

# 2. 配置
Copy-Item .env.example .env
#    编辑 .env：至少填 TELEGRAM_BOT_TOKEN 和 TELEGRAM_USER_ID

# 3. 建表（本地开发用迁移，比 create_all 更接近生产）
.\.venv\Scripts\alembic.exe upgrade head

# 4. 启动
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8420
```

打开 <http://127.0.0.1:8420/health> 应该看到：

```json
{ "status": "ok", "database": true, "config": { "database": "sqlite", ... } }
```

接口文档：<http://127.0.0.1:8420/docs>

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 目录结构

```
zhiwei/
├── app/
│   ├── main.py              FastAPI 入口 + lifespan
│   ├── core/
│   │   ├── config.py        配置（全部来自环境变量，绝不写死密钥）
│   │   └── logging.py       日志（带密钥脱敏兜底）
│   ├── database/
│   │   ├── connection.py    异步引擎 / 会话工厂 / 健康检查
│   │   └── models.py        8 张表（users conversations messages memories
│   │                        memory_candidates people relationships settings）
│   ├── api/routes.py        GET / 、GET /health
│   ├── bot/                 P1：aiogram 3（handlers / keyboards / middlewares）
│   ├── agent/               P3：人格提示词、上下文拼装
│   ├── llm/                 P2：base / gemini / openrouter / ollama / router
│   ├── conversation/        P3：会话服务与仓储
│   └── memory/              P5：extractor / reviewer / manager / retriever
├── migrations/              Alembic（初始迁移已生成并验证）
├── tests/
├── docs/PROJECT_SPEC.md     设计规格原文
├── Dockerfile
├── render.yaml              Render 部署配置
├── alembic.ini              注意：必须保持纯 ASCII
└── pyproject.toml
```

---

## 关键设计决定（与规格的差异，已确认）

1. **渐进式落地**：架构完全按规格分层，但本地先用 SQLite + Ollama，
   靠 `DATABASE_URL` / `LLM_PROVIDER` 一行切换，不重写代码。
2. **主键用 UUID 字符串**：SQLite 和 Postgres 通用，不依赖数据库自增特性。
3. **`create_all` 只用于测试**，真实建表走 Alembic 迁移（应用启动自动执行）。
4. **待办提醒不在 V1.0 范围**（规格未定义），仍由旧 Node 版提供。
5. **额外提供 DeepSeek 适配器**：国内可直连，作为 Gemini 之外的备选。

### 支持的模型

| `LLM_PROVIDER` | 需要 | 说明 |
|---|---|---|
| `ollama` | 本机 Ollama | 免费、离线，默认 |
| `gemini` | `GEMINI_API_KEY` | 规格指定主模型 |
| `openrouter` | `OPENROUTER_API_KEY` + model | 规格指定备用 |
| `deepseek` | `DEEPSEEK_API_KEY` | 国内直连，不需要代理 |

`LLM_FALLBACK_PROVIDER` 配一个不同的值，主模型失败会自动切过去。

### 只读 HTTP 接口

设了 `ADMIN_API_TOKEN` 后可用（请求头 `X-API-Token` 或 `Authorization: Bearer`）：

```
GET /api/v1/models          当前模型配置
GET /api/v1/memories?category=preference
GET /api/v1/profile
GET /api/v1/conversations
GET /api/v1/people
```

不设令牌时这些接口一律 401，保证默认不暴露任何个人数据。

---

## 部署到 Render + Neon（需要账号）

准备好这四样，就能上线：

| 需要什么 | 从哪拿 | 用途 |
|---|---|---|
| GitHub 仓库 | 新建仓库，把 `zhiwei/` 推上去 | Render 从仓库构建 |
| Neon 连接串 | neon.tech 建项目 → Connection string（选 **asyncpg**） | `DATABASE_URL` |
| Gemini API Key | aistudio.google.com → Get API key | 云端模型（Render 在海外，直连可用） |
| 新 Bot Token | @BotFather 再建一个 bot | 避免和旧 Node 版抢同一个 bot |

部署步骤：

1. 推到 GitHub。
2. Render → New → Blueprint，选中仓库（会自动读 `render.yaml`）。
3. 在 Render 后台填上面四个环境变量（`DATABASE_URL` / `TELEGRAM_BOT_TOKEN` /
   `TELEGRAM_USER_ID` / `GEMINI_API_KEY`）。
4. 部署完成后设置 webhook：

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://<你的应用>.onrender.com/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

> 免费实例会休眠（规格 9.3 已说明）：长时间无请求后首次响应会慢几十秒。
