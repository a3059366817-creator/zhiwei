# 架构说明

## 1. 分层原则

| 层 | 目录 | 职责 | 不允许做的事 |
|---|---|---|---|
| 接入层 | `app/api/` `app/bot/` | 收 webhook、解析 Telegram 更新、发消息 | 不写 SQL、不直接调模型 SDK |
| 应用层 | `app/agent/` `app/conversation/` | 组装上下文、编排业务流程 | 不关心 Telegram 的字段 |
| 领域层 | `app/memory/` `app/people/` `app/profile/` | 记忆规则、人物关系、画像 | 不直接收发消息 |
| 能力层 | `app/llm/` | 模型适配器与路由 | 不写业务判断 |
| 基础设施 | `app/core/` `app/database/` | 配置、日志、连接、ORM 模型 | 不含业务规则 |

依赖方向单向向下：接入层可以调任何下层；能力层不知道接入层存在。

## 2. 一次消息的完整链路

```
1. Telegram → POST /webhook/telegram（带 X-Telegram-Bot-Api-Secret-Token）
2. app/api/webhook.py
   ├─ BOT_MODE 必须是 webhook，否则 404
   ├─ 必须配置 secret，否则 503
   ├─ secret 不匹配 → 403（不进任何处理逻辑）
   └─ 解析成 aiogram Update → dp.feed_update()
3. app/bot/middlewares.py
   ├─ AccessMiddleware：from_user.id 必须等于 TELEGRAM_USER_ID
   └─ DbSessionMiddleware：开一个 AsyncSession，异常回滚
4. app/bot/handlers/chat.py
   ├─ 若在「等待修改」状态 → 直接更新对应记录
   ├─ 取/建 user、取/建活跃 conversation
   ├─ 存用户消息
   ├─ assistant.reply() → 生成回复
   ├─ 存助手消息（带 model_name）
   ├─ 发送回复（超 4000 字自动分片）
   └─ asyncio.create_task(run_memory_flow(...))  ← 不阻塞回复
5. app/agent/assistant.py
   ├─ 取最近 16 条消息
   ├─ 用最后一条用户消息做 query，检索相关记忆
   ├─ 用 query 匹配人物档案（只注入被提到的人）
   └─ build_system_prompt() → llm.chat() → (文本, 模型名)
6. app/llm/router.py：按顺序尝试 provider，失败自动切下一个
7. app/memory/flow.py（后台）
   ├─ extractor：模型只输出 JSON 候选
   ├─ rules：Python 决定 自动存 / 要确认 / 丢弃
   ├─ AUTO_SAVE → 写 memories（情境类 14 天过期）
   └─ CONFIRM → 写 memory_candidates + 发确认卡片
8. 用户点「保存」→ callbacks.py → approve_candidate()
   └─ 写 memories；若是 relationship，同时写 people + relationships
```

## 3. 关键设计决策（都有原因）

### 3.1 模型只提议，不落库

`extractor.py` 拿到的只是字符串 JSON，交给 Pydantic 校验，再由 `rules.py` 决定去留。
模型永远无法直接写 `memories` / `people` / `relationships`。
原因：规格明确要求「模型不能绕过记忆审核」，且小模型会过度推断。

### 3.2 审核规则是纯函数

`app/memory/rules.py::review()` 不碰数据库、不碰网络，输入候选输出决策，
所以能被穷举测试（凭证丢弃 / 敏感确认 / 涉及他人强制确认 / 低风险自动存）。

### 3.3 记忆与消息分离

- `messages` 是「他说过什么」，永久保留。
- `memory_candidates` 是「AI 觉得值得记的」，待确认，可丢弃。
- `memories` 是「确认后的事实」，会被检索、会进画像。
三者混用会导致「AI 的猜测被当成事实」，这是规格里最强调的红线。

### 3.4 画像不单独存表

`/profile` 是 memories 按 category 分组的投影。
好处：改一条记忆，画像立即变化，不存在两份数据打架。
人物关系例外，因为它有独立结构（人 + 关系 + 来源），所以单独两张表。

### 3.5 上下文按需注入，不全量塞

- 记忆：关键词 + 重要度 + 时间衰减，取 top 6。
- 人物：只注入「当前这句话里出现的人」，用别名匹配（妈妈→妈、小林→林）。
- 历史：最近 16 条。
原因：控制成本、控制延迟，也避免把无关隐私送给模型。

### 3.6 优雅降级

`build_provider` 在配置不全时抛 `LLMError`，`LLMRouter` 初始化时捕获并跳过，
所以没填 `CLOUDFLARE_ACCOUNT_ID` 时服务照样启动，只是少一个 provider。

### 3.7 启动即迁移

`app/main.py` 的 lifespan 用 `asyncio.to_thread` 调 `alembic upgrade head`，
不用 `create_all`。这样本地/云端表结构始终由同一套迁移驱动。

## 4. 扩展点

| 想加什么 | 在哪加 | 需要改的地方 |
|---|---|---|
| 新模型提供方 | `app/llm/<name>.py` | 实现 `chat()` → `router.build_provider` 加分支 → `.env` 加配置 |
| 新 Telegram 命令 | `app/bot/handlers/commands.py` | 用 `@router.message(Command("x"))` 注册即可 |
| 新记忆类别 | `app/memory/schemas.py` | 加枚举 → `rules.py` 定风险等级 → `profile/service.py` 决定是否进画像 |
| 新 HTTP 接口 | `app/api/v1.py` | 记得加 `Depends(require_token)` |
| 新定时任务 | 目前没有（待办提醒在 Node 版） | 需要引入 APScheduler 或外部 cron |

## 5. 已知边界

- **单用户**：只服务配置里那一个 Telegram ID，没有多租户。
- **无流式回复**：Telegram 侧一次性发；模型侧 `stream: false`。
- **无向量检索**：记忆检索是关键词级，规模上千条后需要换 pgvector。
- **无待办/定时提醒**：规格 V1.0 未包含，由独立的 Node 版（`@ZhiWeiHomeBot`）承担。
- **编辑状态存内存**：`app/memory/pending.py` 用进程内字典，
  多实例部署时必须换成数据库；目前 Render 单实例，安全。
