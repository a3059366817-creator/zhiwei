# 接口与环境变量

## 1. HTTP 接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | 无 | 服务信息 |
| GET | `/health` | 无 | 健康检查（含脱敏配置快照与计数） |
| POST | `/webhook/telegram` | Telegram Secret | Telegram 更新入口 |
| GET | `/api/v1/models` | API Token | 当前模型配置 |
| GET | `/api/v1/memories?category=&limit=` | API Token | 记忆列表 |
| GET | `/api/v1/profile` | API Token | 画像（按类别分组） |
| GET | `/api/v1/conversations?limit=` | API Token | 会话列表 |
| GET | `/api/v1/people` | API Token | 人物档案 + 关系 |

### 鉴权

数据类接口用 `ADMIN_API_TOKEN`：

```bash
curl -H "X-API-Token: $ADMIN_API_TOKEN" https://zhiwei-u0jc.onrender.com/api/v1/memories
# 或
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" ...
```

- **没配置 `ADMIN_API_TOKEN` 时，所有 `/api/v1/*` 一律 401**（默认关闭，安全优先）
- 令牌比较用 `hmac.compare_digest`，防时序攻击

### `/health` 返回

```json
{
  "status": "ok",
  "database": true,
  "config": {
    "app_env": "production",
    "database": "postgres",
    "llm_provider": "cloudflare",
    "llm_fallback": null,
    "bot_mode": "webhook",
    "ai_name": "知微",
    "user_name": "木川",
    "telegram_configured": true,
    "owner_bound": true
  },
  "stats": { "users": 1, "memories": 2 }
}
```

只暴露计数，不暴露内容。

### Webhook 的三道闸

```python
if settings.bot_mode != "webhook": 404       # 轮询模式下不接 webhook
if not secret: 503                           # 没配密钥直接拒绝（防伪造）
if header != secret: 403                     # 密钥不匹配，不进处理流程
```

## 2. Telegram 命令

| 命令 | 作用 |
|---|---|
| `/start` | 初始化，显示菜单按钮 |
| `/help` | 帮助 |
| `/new`（别名 `/chat`） | 归档当前会话，开新的 |
| `/history` | 最近 10 条对话 |
| `/model` | 当前主用/备用模型 |
| `/id` | 你的 Telegram ID |
| `/memory` | 列出全部记忆 + 修改/删除按钮 |
| `/memory <category>` | 按类别筛选：`profile` / `preference` / `experience` / `relationship` / `context` |
| `/memory pending` | 只看待确认候选 |
| `/memory off` / `on` | 暂停 / 恢复自动记忆 |
| `/profile` | 个人画像 |
| `/people` | 人物档案 + 改称呼 / 改备注 / 改关系 / 删除 |
| `/settings` | 未实现（占位） |

### 回调查询

| callback_data | 作用 |
|---|---|
| `mem:save:<id>` | 确认候选 → 写 memories（关系类同时建 people） |
| `mem:edit:<id>` | 进入「等你发新内容」状态 |
| `mem:skip:<id>` | 拒绝，候选标记 rejected |
| `mem:never:<id>` | 以后不再问这条 |
| `mem:del:<id>` | 删除已入库记忆（真删） |
| `ppl:name:<id>` / `ppl:desc:<id>` / `ppl:rel:<id>` | 改称呼 / 备注 / 关系 |
| `ppl:del:<id>` | 删人物（连带关系） |
| `cmd:new` / `cmd:memory` / `cmd:history` / `cmd:model` | 菜单按钮 |

## 3. 环境变量完整清单

### 应用

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_ENV` | local | local / production |
| `LOG_LEVEL` | INFO | |
| `APP_HOST` / `APP_PORT` | 127.0.0.1 / 8420 | 本地开发用（Render 用 `$PORT`） |

### 数据库

| 变量 | 示例 |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?ssl=require` |
| | `sqlite+aiosqlite:///./data/zhiwei.db`（本地） |

> asyncpg 不认 `sslmode=`，要写 `?ssl=require`；`channel_binding` 参数也不支持。

### Telegram

| 变量 | 说明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather 给的 token |
| `TELEGRAM_USER_ID` | 只允许这个人用（**必填**，否则拒绝所有消息） |
| `TELEGRAM_PROXY` | 国内开发需要，如 `http://127.0.0.1:7897`；云端留空 |
| `TELEGRAM_WEBHOOK_SECRET` | webhook 校验密钥，留空则 webhook 模式直接 503 |
| `BOT_MODE` | `polling`（本地） / `webhook`（云端） |

### 模型

| 变量 | 说明 |
|---|---|
| `LLM_PROVIDER` | `ollama` / `cloudflare` / `deepseek` / `gemini` / `openrouter` |
| `LLM_FALLBACK_PROVIDER` | 主模型失败后切这个（云端没有 ollama，可留空） |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 本地模型 |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_MODEL` | Workers AI（account_id 必填） |
| `CLOUDFLARE_TIMEOUT` | 默认 30 秒，云端建议 45 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | |

### 人格与记忆

| 变量 | 默认 |
|---|---|
| `AI_NAME` | 知微 |
| `USER_NAME` | 木川 |
| `MEMORY_AUTO_SAVE` | true（低风险信息是否自动入库） |

### 接口

| 变量 | 说明 |
|---|---|
| `ADMIN_API_TOKEN` | 只读接口令牌；不设则全部 401 |
| `PYTHON_VERSION` | Render 构建用，当前 3.12.8 |

## 4. 本地调试技巧

```powershell
# 完整自检（服务是否起得来 + 数据库通不通）
curl http://127.0.0.1:8420/health

# 交互式文档（FastAPI 自动生成）
start http://127.0.0.1:8420/docs

# 强制走某个模型
$env:LLM_PROVIDER="ollama"; python -m uvicorn app.main:app --port 8420

# 只看记忆抽取质量（临时库，不污染真实数据）
python scripts/check_memory.py
python scripts/check_people.py
```
