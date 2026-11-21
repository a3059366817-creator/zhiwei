# 文件地图

共 82 个受版本控制文件 / 约 5500 行。按目录分组，标注职责与关键符号。

```
zhiwei/  (项目根)
├── 应用代码 app/          约 2600 行
├── 迁移 migrations/       约 260 行
├── 测试 tests/            约 900 行
├── 脚本 scripts/          约 570 行
├── 文档 docs/             8 个 md
└── 部署/配置              6 个文件
```

---

## 根目录

| 文件 | 行 | 作用 | 改它要注意 |
|---|---|---|---|
| `pyproject.toml` | 44 | 依赖、pytest、ruff、hatchling 打包配置 | 改依赖后跑 `uv lock`；`[build-system]` 是 Render 构建成功的前提 |
| `uv.lock` | 大 | uv 锁定文件 | 自动生成，不要手改 |
| `.env.example` | 45 | 环境变量模板（不含真实值） | 新增配置项时同步这里 |
| `.gitignore` | 26 | 排除 `.env` / `data/` / `.venv/` / `dist/` | 新增敏感产物记得加 |
| `alembic.ini` | 34 | Alembic 配置 | **必须纯 ASCII**（中文会因 GBK 解码报错） |
| `Dockerfile` | 16 | 容器构建（备用部署方式） | Render 原生构建不用它 |
| `render.yaml` | 38 | Render Blueprint（声明式部署） | 实际服务由 API 创建，此文件是备用/参考 |
| `README.md` | 104 | 快速开始 + 路线图 | |
| `start.cmd` | 9 | Windows 本地启动（ASCII，避免 cmd 乱码） | |

---

## app/ — 应用代码

### app/main.py（94 行）

FastAPI 入口 + 生命周期。

- `create_app()`：注册路由（`api_router`、`v1_router`、`webhook_router`）
- `lifespan()`：初始化日志 → **在线程里跑 `alembic upgrade head`** → 构造 LLM 路由与 Assistant →
  `BOT_MODE=polling` 时启动 aiogram 长轮询任务 → 关闭时取消任务、关闭 bot session
- `_upgrade_schema()`：`asyncio.to_thread` 调 alembic（因为 `migrations/env.py` 内部用 `asyncio.run`）

### app/core/

| 文件 | 行 | 内容 |
|---|---|---|
| `config.py` | 78 | `Settings`（pydantic-settings）。所有密钥、模型、人格配置；`public_dict()` 输出脱敏快照；`telegram_user_id` 有空值→None 的校验器 |
| `logging.py` | 31 | `setup_logging()`；`_SecretFilter` 兜底抹掉日志里的 `AAH` / `sk-` / `Bearer` |

### app/database/

| 文件 | 行 | 内容 |
|---|---|---|
| `models.py` | 112 | 8 个 ORM 模型：`User` `Conversation` `Message` `Memory` `MemoryCandidate` `Person` `Relationship` `UserSettings`；`new_id()` 生成 UUID；`utcnow()` |
| `connection.py` | 75 | 异步引擎单例、`async_sessionmaker`、`get_session()` 依赖、`init_db()`（仅测试用）、`ping_db()`、`dispose_db()` |
| `repositories/` | - | 当前为空目录，业务查询直接写在各自 service 里（规模还小） |

### app/llm/ — 模型层

| 文件 | 行 | 内容 |
|---|---|---|
| `base.py` | 23 | `LLMProvider` Protocol（`name` + `async chat()`）、`LLMError` |
| `router.py` | 71 | `build_provider()` 按名字构造；`LLMRouter` 按主→备顺序尝试，全失败抛 `LLMError`；配置不全的 provider 启动时跳过 |
| `cloudflare.py` | 91 | Workers AI：`/accounts/{id}/ai/run/{model}`；`_extract_text()` 兼容 `result.response` 与 OpenAI `choices[]`；25/30 秒超时 |
| `ollama.py` | 51 | 本地 Ollama `/api/chat`；带 `repeat_penalty` 等抑制车轱辘话 |
| `deepseek.py` | 59 | OpenAI 兼容，国内直连 |
| `gemini.py` | 77 | REST `generateContent`，system 抽成 `systemInstruction` |
| `openrouter.py` | 54 | OpenAI 兼容 |

### app/agent/ — 对话编排

| 文件 | 行 | 内容 |
|---|---|---|
| `prompts.py` | 40 | `BASE_PROMPT`（核心身份 / 人格 / 风格 / 用户背景 / 记忆规则 / 隐私规则 / 行为规范 / **能力边界**）；`build_system_prompt()` 注入记忆与人物 |
| `assistant.py` | 51 | `Assistant.reply()`：取 16 条历史 → 检索记忆 → 匹配人物 → 拼 prompt → 调路由；`_memory_lines()` / `_people_lines()` 都做了异常兜底 |

### app/conversation/

| 文件 | 行 | 内容 |
|---|---|---|
| `service.py` | 88 | `get_active_conversation()` / `start_new_conversation()`（归档旧的）/ `add_message()` / `recent_messages()` / `list_conversations()` / `message_count()` |

### app/memory/ — 记忆系统（核心）

| 文件 | 行 | 内容 |
|---|---|---|
| `schemas.py` | 76 | Pydantic：`MemoryCategory` `Sensitivity` `ExtractedCandidate`（含 person_name/relation_type）、`ExtractionResult`（最多 5 条）、`Decision`、`ReviewResult`；带类别/sensitivity 的容错归一化 |
| `extractor.py` | 82 | `MemoryExtractor.extract()`：提示词 + JSON 解析（`_extract_json_object` 容忍 ```json 包裹）；解析失败返回空结果，绝不猜 |
| `rules.py` | 158 | `review(candidate, auto_save_enabled)`：凭证→DROP；敏感词→CONFIRM(sensitive)；经历/关系→CONFIRM；**涉及他人（45 个称谓词）→CONFIRM**；低风险→AUTO_SAVE |
| `manager.py` | 220 | 题库操作：`save_memory`（bigram 相似度去重）、`create_candidate`、`approve_candidate`（关系类同时建 people/relationships）、`reject/never_ask`、`list/get/update/delete_memory`、`apply_auto_save`（context 14 天过期） |
| `retriever.py` | 84 | 关键词（英文词 + 中文 bigram）→ 打分（重叠×2 + importance×0.3 + 时间衰减）→ top 6；过滤过期 |
| `flow.py` | 82 | `run_memory_flow()`：后台任务，抽取→审核→自动存/发确认卡片；只写候选，不越权 |
| `pending.py` | 23 | 进程内「等待用户输入」状态机：`candidate` / `memory` / `person_name` / `person_desc` / `relation` |

### app/people/

| 文件 | 行 | 内容 |
|---|---|---|
| `service.py` | 182 | `upsert_person`（同名合并）、`add_relationship`（同类型去重）、`update_person`（改名撞车自动合并）、`set_relation`、`delete_person`（连带关系）、`people_context`（**别名匹配**：妈妈→妈、小林→林、王老师→王） |

### app/profile/

| 文件 | 行 | 内容 |
|---|---|---|
| `service.py` | 53 | `build_profile()` 按 category 分组；`render_profile_text()` 渲染 `/profile`；`profile_summary_lines()` 给上下文用 |

### app/services/

| 文件 | 行 | 内容 |
|---|---|---|
| `user_service.py` | 62 | `get_or_create()`（按 telegram_id）、`get_settings_row()`、`update_settings()`（auto_save 开关等） |

### app/bot/ — Telegram 接入

| 文件 | 行 | 内容 |
|---|---|---|
| `dispatcher.py` | 34 | `create_bot()`（可选 `AiohttpSession(proxy=...)`）、`create_dispatcher()`（挂中间件、三个 router、注入 settings/assistant/llm） |
| `middlewares.py` | 51 | `AccessMiddleware`（只放行 `TELEGRAM_USER_ID`，陌生人只提示一次）、`DbSessionMiddleware`（每更新一个会话，异常回滚） |
| `keyboards.py` | 62 | `main_menu()`、`memory_candidate()`（保存/修改/暂不/永不再问）、`memory_list()`（✏️/🗑）、`people_list()`（改称呼/备注/关系/删） |
| `utils.py` | 22 | `split_text()` / `answer_long()`：Telegram 4000 字上限分片 |
| `handlers/chat.py` | 124 | 文本消息主流程：优先处理「等待修改」状态 → 建 user/conv → 存消息 → 生成回复 → 存回复 → 发送 → **后台触发记忆流水线** |
| `handlers/commands.py` | 190 | `/start` `/help` `/new` `/history` `/model` `/id` `/memory`（含 filters/off/on）`/profile` `/people` `/settings` |
| `handlers/callbacks.py` | 144 | 菜单按钮、记忆候选确认/编辑/删除、人物编辑/删除；同一 `mem:edit:<id>` 会自动判断是候选还是已入库记忆 |

### app/api/

| 文件 | 行 | 内容 |
|---|---|---|
| `routes.py` | 41 | `GET /`、`GET /health` |
| `webhook.py` | 35 | `POST /webhook/telegram`：模式/密钥/结构三重校验，然后 `dp.feed_update()` |
| `v1.py` | 111 | 只读接口 + `require_token` 依赖（`hmac.compare_digest`）；`_owner()` 取配置的主人 |

---

## migrations/

| 文件 | 行 | 说明 |
|---|---|---|
| `env.py` | 44 | 异步 Alembic 环境，URL 从 `Settings` 读，`target_metadata = Base.metadata` |
| `script.py.mako` | 18 | 迁移模板 |
| `versions/276555ecb36f_initial_schema.py` | 150 | 8 张表 + 索引 |
| `versions/176813c6f087_add_person_fields...py` | 23 | 候选表加 person_name / relation_type |
| `versions/1cafcf7526e2_telegram_id_to_bigint.py` | 27 | telegram_id 改 BIGINT |

---

## tests/（75 个用例）

| 文件 | 行 | 覆盖 |
|---|---|---|
| `conftest.py` | 11 | 把 `DATABASE_URL` 指到临时 SQLite，杜绝污染真实库 |
| `unit/test_health.py` | 43 | 启动、健康检查、不泄露密钥、脱敏 |
| `unit/test_prompt_access.py` | 52 | 提示词七段结构、禁止虚构人类经历、访问控制中间件 |
| `unit/test_llm_router.py` | 45 | 主备切换、全失败、未知 provider |
| `unit/test_conversation.py` | 46 | 消息顺序、新会话归档、历史条数限制、用户幂等 |
| `unit/test_memory.py` | 212 | 规则全分支、JSON 容错、去重、确认/拒绝、检索、删除、流水线端到端（含敏感不自动存、凭证丢弃） |
| `unit/test_people_profile.py` | 121 | 人物去重、关系去重、级联删除、别名匹配、画像分组、关系候选归档 |
| `unit/test_editing.py` | 92 | 记忆内容替换、改名合并、关系替换、待编辑状态机、删后不可编辑 |
| `unit/test_security.py` | 172 | 规格 10.4 隐私测试 6 条 + API 鉴权 + webhook 三道闸 |
| `unit/test_cloudflare.py` | 63 | MockTransport：URL/鉴权头正确、429/401/空响应、缺参数 |

---

## scripts/

| 文件 | 行 | 用途 |
|---|---|---|
| `deploy_render.py` | 277 | 一键部署：GitHub 建仓库 → push → Render 建服务 → 写环境变量 → 等 live → setWebhook；带重试与 dry-run |
| `migrate_to_postgres.py` | 81 | SQLite → Postgres 数据搬迁（按外键顺序、保留 id、幂等） |
| `check_memory.py` | 64 | 用真实模型跑记忆抽取，打印决策（临时库） |
| `check_people.py` | 61 | 人物关系候选 → 确认 → 归档 的端到端演练 |

---

## docs/

| 文件 | 说明 |
|---|---|
| `INDEX.md` | 文档导航 |
| `ARCHITECTURE.md` | 分层、数据流、设计决策、扩展点、边界 |
| `DATABASE.md` | 表结构、迁移、备份、三个坑 |
| `API.md` | 接口、命令、回调、环境变量清单 |
| `DEVELOPMENT.md` | 开发环境、测试、常见改造任务、规范 |
| `OPERATIONS.md` | 部署、日志、监控、排障、成本 |
| `FILE_MAP.md` | 本文件 |
| `CHANGELOG.md` | 版本与决策记录 |
| `ACCEPTANCE.md` | 规格 10.x 验收对照 |
| `DEPLOY.md` | Render 部署实录与四个坑 |
| `PROJECT_SPEC.md` | 产品规格原文（615 行） |
