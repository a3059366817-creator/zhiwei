# 知微 V1.0 验收对照表

对照规格「第四部分：V1.0 最终交付清单」与「第十部分：测试与验收标准」逐条核对。

运行全部测试：

```powershell
cd D:\develop\AI好友\zhiwei
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 一、最终交付清单

| # | 交付项 | 状态 | 位置 / 说明 |
|---|---|---|---|
| 1 | 可运行的 Python 项目 | ✅ | `app/`，Python 3.12 + FastAPI |
| 2 | Telegram Bot | ✅ | `app/bot/`（aiogram 3，长轮询 + webhook 两模式） |
| 3 | 知微人格提示词 | ✅ | `app/agent/prompts.py`（规格要求的 7 段结构） |
| 4 | Gemini 模型适配器 | ✅ 代码就绪 | `app/llm/gemini.py`；需 `GEMINI_API_KEY` 才能实际上线 |
| 5 | OpenRouter 备用模型适配器 | ✅ 代码就绪 | `app/llm/openrouter.py`；需 key |
| 6 | 多轮对话管理 | ✅ | `app/conversation/service.py`（最近 16 条上下文） |
| 7 | PostgreSQL 数据库 | ✅ 已接入 Neon | 生产库为 Neon Postgres 18，`ssl=require` |
| 8 | 数据库迁移 | ✅ | `migrations/`，应用启动自动 `upgrade head`，当前版本 `1cafcf7526e2` |
| 9 | 聊天记录管理 | ✅ | `messages` / `conversations` 表 + `/history`、`/new` |
| 10 | 混合长期记忆系统 | ✅ | `app/memory/`（extractor / rules / manager / retriever） |
| 11 | 记忆候选确认机制 | ✅ | Telegram 卡片：保存 / 修改 / 暂不保存 / 以后别问 |
| 12 | 个人画像管理 | ✅ | `/profile`、`app/profile/service.py` |
| 13 | 人物档案管理 | ✅ | `/people`、`app/people/service.py` |
| 14 | 记忆检索 | ✅ | `app/memory/retriever.py`（关键词 + 重要度 + 时间衰减） |
| 15 | 记忆修改与删除 | ✅ | `/memory` 的 ✏️ / 🗑，人物可改称呼/备注/关系 |
| 16 | Telegram 用户访问控制 | ✅ | `app/bot/middlewares.py::AccessMiddleware` |
| 17 | 基础测试 | ✅ | 66 个用例 |
| 18 | Render 部署配置 | ✅ 已上线 | https://zhiwei-u0jc.onrender.com （free，singapore） |
| 19 | Neon 数据库配置 | ✅ 已完成 | Neon PostgreSQL 18，`ssl=require`，迁移到 `1cafcf7526e2` |
| 20 | README 使用文档 | ✅ | `README.md` |
| 21 | `.env.example` | ✅ | 含全部环境变量与注释 |

**结论：V1.0 交付清单全部完成，服务已运行在云端（电脑关机也能用）。**

线上地址：<https://zhiwei-u0jc.onrender.com> · 健康检查 `/health`
Telegram：`@zhiwei_muchuna_bot`（webhook 模式）

---

## 二、隐私与安全测试（规格 10.4）

| 要求 | 验证 | 用例 |
|---|---|---|
| 用户拒绝保存后，候选不得进入正式记忆 | ✅ | `test_security.py::test_rejected_candidate_never_enters_memory` |
| 用户删除后，记忆不能再次被检索 | ✅ | `test_security.py::test_deleted_memory_not_retrievable` |
| 未授权用户无法访问数据 | ✅ | `test_security.py::test_unauthorized_user_blocked` |
| 敏感信息不会被自动写入长期记忆 | ✅ | `test_security.py::test_sensitive_info_never_auto_saved` |
| 记忆候选不能绕过确认机制 | ✅ | `test_security.py::test_candidate_cannot_bypass_confirmation` |
| Webhook 无效请求不能进入消息处理流程 | ✅ | `test_security.py::test_webhook_rejects_wrong_secret` |
| 数据接口必须鉴权 | ✅ | `test_security.py::test_api_requires_token` |

## 三、记忆测试（规格 10.3）

规格给的 8 步场景，对应验证：

| 步骤 | 验证 |
|---|---|
| 1. 用户介绍长期兴趣 | ✅ `test_memory.py::test_flow_auto_saves_low_risk_and_notifies` |
| 2. AI 生成记忆候选 | ✅ `test_memory.py::test_extractor_parses_valid_json` |
| 3. 用户确认保存 | ✅ `test_memory.py::test_approve_candidate_creates_memory` |
| 4. 开启新会话 | ✅ `test_conversation.py::test_new_conversation_archives_old` |
| 5. 询问之前介绍的兴趣 | ✅ `test_memory.py::test_retrieve_picks_relevant_memory` |
| 6. AI 准确检索 | ✅ 同上 |
| 7. 用户修改记忆 | ✅ `test_editing.py::test_update_memory_replaces_content` |
| 8. 再次检索返回更新后内容 | ✅ 同上（检索命中新内容） |

## 四、模型测试（规格 10.2）

| 要求 | 验证 |
|---|---|
| Gemini / OpenRouter 可调用 | 🟡 代码就绪，需 key 实测 |
| 主模型失败切换备用 | ✅ `test_llm_router.py::test_fallback_when_primary_fails` |
| 限流正确处理 | ✅ 适配器对 429 抛 `LLMError`，路由切下一个 |
| 模型异常不致 Bot 崩溃 | ✅ `test_llm_router.py::test_all_providers_fail_raises` + chat handler 捕获 |
| 回复过长自动分段 | ✅ `app/bot/utils.py::split_text`（4000 字符切分） |

## 五、访问控制（规格 8.1）

| 要求 | 验证 |
|---|---|
| 只允许指定 Telegram 用户 | ✅ 中间件拦截，非主人只提示一次 |
| 未配置主人时拒绝所有消息 | ✅ `test_prompt_access.py::test_access_middleware_blocks_when_owner_unset` |
| Webhook Secret 校验 | ✅ 403 |
| 不在公开接口暴露记忆 | ✅ `/health` 只返回计数；数据接口需 token |

---

## 六、无法在本机完成的三项（需你提供）

| 项 | 为什么需要你 | 拿到后我做什么 |
|---|---|---|
| Render 部署 | 需要 GitHub + Render 账号授权 | 推仓库、跑 Blueprint、验证 HTTPS 域名与 webhook |
| Neon 数据库 | 需要注册并建项目拿连接串 | 填 `DATABASE_URL`，跑 `alembic upgrade head`，验证数据落库 |
| Gemini Key | 需要 Google 账号 | 配 key，实测主备切换与限流 |

**在此之前，本地已经可以完整使用**：SQLite + Ollama + Telegram 全链路已验证。
