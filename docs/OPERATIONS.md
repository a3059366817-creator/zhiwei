# 运维手册

## 1. 线上拓扑

```
Telegram ──webhook──> Render (FastAPI + aiogram) ──> Neon PostgreSQL
                              │
                              └──> Cloudflare Workers AI (llama-3.3-70b)
```

| 组件 | 地址 / 标识 |
|---|---|
| 应用 | https://zhiwei-u0jc.onrender.com |
| 健康检查 | `/health` |
| Render 服务 ID | `srv-dc0leom7bikc73b5q2gg` |
| Render 区域/套餐 | singapore / free |
| Neon | PostgreSQL 18，`?ssl=require` |
| Telegram Bot | @zhiwei_muchuna_bot（webhook 模式） |
| 仓库 | github.com/a3059366817-creator/zhiwei（public） |

## 2. 日常操作

### 看健康

```powershell
curl https://zhiwei-u0jc.onrender.com/health
```

关键字段：`status: ok`、`database: true`、`config.database: postgres`、`config.bot_mode: webhook`。

### 手动触发部署

```powershell
$H = @{ Authorization = "Bearer <RENDER_KEY>"; "Content-Type" = "application/json" }
Invoke-RestMethod -Method Post `
  -Uri "https://api.render.com/v1/services/srv-dc0leom7bikc73b5q2gg/deploys" `
  -Headers $H -Body '{"clearCache":"clear"}'
```

### 改环境变量

用 Render 控制台 Environment 页，或 API：

```powershell
Invoke-RestMethod -Method Put `
  -Uri "https://api.render.com/v1/services/<SID>/env-vars/LLM_PROVIDER" `
  -Headers $H -Body '{"value":"deepseek"}'
```

改完需要重新部署才生效（`LLM_PROVIDER` 之类在启动时读取）。

### 看日志

```powershell
# 全部（含构建）
Invoke-RestMethod "https://api.render.com/v1/logs?ownerId=<OWNER>&resource=<SID>&limit=100" -Headers $H
```

或直接看 Render 控制台 → Logs（实时流）。

### 重设 webhook

```powershell
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" `
  -d "url=https://zhiwei-u0jc.onrender.com/webhook/telegram" `
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

> 密钥在 Render 环境变量里；改动后必须同步重设，否则所有更新会被 403。

## 3. 监控要点

| 指标 | 怎么查 | 异常表现 |
|---|---|---|
| 进程存活 | `/health` status | `degraded` = 数据库不通 |
| 数据库 | `/health` database | false → 检查 Neon 是否超额/暂停 |
| 模型 | 回复的 `model_name`（messages 表） | 一直是备用模型说明主模型在失败 |
| Telegram | `getWebhookInfo` 的 `last_error_message` | 403 = 密钥不匹配；409 = 还在用轮询 |
| 额度 | Cloudflare 控制台 Workers AI 用量 | 429 = 当天 neuron 用尽 |

`/health` 也返回 `stats.users` / `stats.memories`，可做简单趋势观察。

## 4. 故障排查表

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 发消息没反应，超过 1 分钟 | Render 休眠中（15 分钟无请求） | 再等 30–50 秒；或配 UptimeRobot 保活 |
| 发消息立刻报「脑子卡了一下」 | 模型超时/限流 | 看 Render 日志的 `LLMError`；临时把 `LLM_PROVIDER` 换 `deepseek` |
| `/health` 返回 `degraded` | Neon 不可达 / 超额 | Neon 控制台看项目状态；确认连接串未变 |
| webhook `last_error_message` 是 403 | secret 不匹配 | 重置 Render 的 `TELEGRAM_WEBHOOK_SECRET` → 重新 setWebhook |
| 出现两条回复 | 本地和云端同时在跑 | 停本地：`taskkill /PID <pid>`；webhook 与轮询互斥 |
| 构建失败 `No module named uvicorn` | 构建命令装错解释器 | 用 `uv pip install --python "$(which python)" --no-cache .` |
| 记忆没生成 | `memory_enabled` 被关，或模型抽取失败 | `/memory` 看；`/memory on` 恢复；查日志 `[memory]` |

## 5. 备份

Neon 免费版有 PITR（时间点恢复），但建议定期导出：

```bash
pg_dump "postgresql://neondb_owner:<pwd>@ep-...neon.tech/neondb?sslmode=require" > backup-$(date +%F).sql
```

恢复：

```bash
psql "$DATABASE_URL" < backup-2026-11-21.sql
```

数据量很小（当前 12 条消息 / 2 条记忆），导出是秒级的。

## 6. 成本与配额

| 资源 | 免费额度 | 注意 |
|---|---|---|
| Render Web Service | 750 小时/月，不休眠时间有限 | 15 分钟无流量会休眠 |
| Neon | 0.5 GB 存储 + 计算额度 | 闲置会自动挂起 |
| Cloudflare Workers AI | 每天 neuron 配额 | 超了 429，云端无备用模型会报错 |
| Telegram Bot API | 免费 | 有速率限制 |

纯日常使用（一天几十条消息）目前都在免费额度内。

## 7. 安全清单（上线后自查）

- [x] `.env` 未入库（`.gitignore` 已挡）
- [x] 仓库内无 token / 数据库密码 / 个人 ID
- [x] webhook 必须带 Secret，不配则 503
- [x] 非 `TELEGRAM_USER_ID` 的消息被中间件拦截
- [x] `/api/v1/*` 默认 401（未配 `ADMIN_API_TOKEN`）
- [x] 敏感记忆必须人工确认；凭证类直接丢弃
- [x] 删除记忆是物理删除
- [ ] 定期轮换 Render API Key / GitHub PAT / Bot Token（建议 3–6 个月）
- [ ] 生产环境把仓库改回私有（需给 Render 的 GitHub App 授权）

## 8. 升级依赖

```powershell
uv lock --upgrade-package fastapi
uv sync
pytest -q
# 通过后提交 uv.lock，Render 会自动重建
```

> ⚠️ 不要在云端直接在 shell 里升级，构建时以 `uv.lock` 为准。

## 9. 提醒保活（V1.1 关键）

Render 免费实例 15 分钟无请求休眠，**休眠时进程内调度器不跑**，
所以必须有一个外部 cron 每 5 分钟打 `POST /api/v1/internal/tick`。

### 方案 A：GitHub Actions（推荐，免费）

仓库里需要有 `.github/workflows/keepalive.yml`（内容见 `docs/keepalive.yml.example`），
它用 `secrets.TICK_TOKEN` 调接口。仓库 secret 已经配置好了（名为 `TICK_TOKEN`）。

> ⚠️ 推送 workflow 文件需要 PAT 带 `workflow` 权限；只有 `repo` 权限会被 GitHub 拒绝。
> 没有该权限时，可以在 GitHub 网页上手动新建这个文件（Add file → Create new file）。

### 方案 B：任何可发 HTTP 的定时器

```bash
curl -X POST https://zhiwei-u0jc.onrender.com/api/v1/internal/tick \
  -H "X-API-Token: $ADMIN_API_TOKEN"
```

UptimeRobot / cron-job.org / 自建 cron 都行，注意必须能发 POST 并带 header。

### 验证保活是否生效

```powershell
# 连续两次调用，间隔 > 15 分钟后再看 Render 日志：如果没有新的冷启动记录，说明没睡
curl -X POST https://zhiwei-u0jc.onrender.com/api/v1/internal/tick -H "X-API-Token: ..."
```

响应里的 `sent` 是本次推送的提醒条数。

### 提醒没发出的排查顺序

1. `/todo` 看这条还在不在、时间对不对（注意时区）；
2. 手动打一次 tick，看 `sent` 是否为 0；
3. `sent=0` 且确实到点了 → 检查 `remind_count` 是否已到 3、`last_remind_at` 是否在 20 分钟内；
4. `sent>0` 但没收到 → 查 Telegram 侧是否被屏蔽、bot 是否被 block。
