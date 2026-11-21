# 文档索引

> 知微 ZhiWei V1.0 — 私人 Telegram AI 伙伴
> 线上地址：<https://zhiwei-u0jc.onrender.com>

## 按目的找文档

| 我想… | 看这个 |
|---|---|
| 先跑起来 | [README](../README.md) → [DEVELOPMENT](DEVELOPMENT.md) |
| 理解代码怎么分层、数据怎么流动 | [ARCHITECTURE](ARCHITECTURE.md) |
| 改表结构 / 加字段 | [DATABASE](DATABASE.md) |
| 加接口 / 查命令 / 看环境变量 | [API](API.md) |
| 加一个模型 / 加一条命令 / 加记忆类别 | [DEVELOPMENT](DEVELOPMENT.md#常见改造任务) |
| 部署、看日志、备份、排障 | [OPERATIONS](OPERATIONS.md) · [DEPLOY](DEPLOY.md) |
| 找某个文件是干嘛的 | [FILE_MAP](FILE_MAP.md) |
| 知道这版为什么这么做 | [CHANGELOG](CHANGELOG.md) |
| 对照产品规格验收 | [ACCEPTANCE](ACCEPTANCE.md) · [PROJECT_SPEC](PROJECT_SPEC.md) |

## 三分钟速览

```
Telegram 消息（webhook）
   ↓  app/api/webhook.py
app/bot/          aiogram 3：中间件（鉴权 + 每更新一个 DB 会话）→ handlers
   ↓
app/agent/        拼「人格提示词 + 历史 + 相关记忆 + 人物档案」→ 调模型
   ↓
app/llm/router.py 主模型（Cloudflare Workers AI）→ 失败切备用
   ↓
app/conversation/ 落库（conversations / messages）
   ↓
app/memory/       后台任务：提取候选 → Python 规则审核 → 自动存 / 等确认
   ↓
app/people/ · app/profile/   确认后归档人物关系；画像由记忆聚合而来
   ↓
Neon PostgreSQL（生产） / SQLite（本地）
```

## 关键事实

- 语言：Python 3.12.14（uv 管理）
- 框架：FastAPI + aiogram 3 + SQLAlchemy 2(async) + Alembic
- 线上：Render（free，singapore）+ Neon PostgreSQL 18 + Cloudflare Workers AI
- 测试：75 个用例，`pytest -q`
- 规范：Ruff（E/F/I/UP/B），`ruff check .`
- 单用户：只服务 `TELEGRAM_USER_ID` 指定的那一个人
