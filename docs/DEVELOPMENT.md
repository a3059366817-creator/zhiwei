# 开发指南

## 1. 环境准备

```powershell
cd D:\develop\AI好友\zhiwei

uv venv --python 3.12 .venv     # uv 内置 CPython 3.12
uv sync                          # 安装运行时 + 开发依赖
Copy-Item .env.example .env      # 然后按需填值
```

本地最小可跑配置（不需要任何云服务）：

```env
DATABASE_URL=sqlite+aiosqlite:///./data/zhiwei.db
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
TELEGRAM_BOT_TOKEN=<你的 bot token>
TELEGRAM_USER_ID=<你的 telegram id>
TELEGRAM_PROXY=http://127.0.0.1:7897   # 国内访问 Telegram 必需
BOT_MODE=polling
```

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8420
```

## 2. 日常命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 全部测试（75）
.\.venv\Scripts\ruff.exe check .                 # 代码规范
.\.venv\Scripts\ruff.exe check . --fix           # 自动修复
.\.venv\Scripts\alembic.exe upgrade head         # 应用迁移
.\.venv\Scripts\alembic.exe revision --autogenerate -m "msg"   # 生成迁移
```

> 测试用 `conftest.py` 把 `DATABASE_URL` 指到临时 SQLite，**不会碰真实数据**。

## 3. 调试技巧

| 场景 | 做法 |
|---|---|
| 想看不经过 Telegram 的对话 | `python scripts/check_memory.py` / `check_people.py`（临时库 + 真实模型） |
| 想确认记忆判定 | 直接调 `app.memory.rules.review()`，纯函数无副作用 |
| 想看当前模型链 | `python -c "from app.llm.router import LLMRouter; from app.core.config import get_settings; print(LLMRouter(get_settings()).provider_names)"` |
| 服务起不来 | 先 `curl /health`；再查日志里的 alembic 段 |
| Telegram 收不到 | 确认 `BOT_MODE`：polling 与 webhook 互斥 |

## 4. 常见改造任务

### 4.1 加一个模型提供方

```python
# app/llm/myvendor.py
class MyVendorProvider:
    name = "myvendor"
    async def chat(self, messages, *, temperature=0.8, max_tokens=None) -> str:
        ...  # 失败必须抛 LLMError
```

```python
# app/llm/router.py
if key == "myvendor":
    return MyVendorProvider(settings.myvendor_key, settings.myvendor_model)
```

```python
# app/core/config.py  → 加字段
myvendor_key: str = ""
myvendor_model: str = "default"
```

然后 `.env` 里 `LLM_PROVIDER=myvendor`。**不需要改任何业务代码**——这就是模型层抽象的意义。

### 4.2 加一条 Telegram 命令

```python
# app/bot/handlers/commands.py
@router.message(Command("todos"))
async def on_todos(message: Message, session: AsyncSession) -> None:
    await message.answer("还没做这个功能")
```

处理器能拿到的依赖（由 `dispatcher.py` 注入）：
`settings` / `assistant` / `llm` / `session`（DbSessionMiddleware 提供）。

### 4.3 加记忆类别

1. `app/memory/schemas.py::MemoryCategory` 加枚举值
2. `app/memory/rules.py` 决定它的风险等级（放 `LOW_RISK_CATEGORIES` 还是 `CONFIRM_CATEGORIES`）
3. `app/profile/service.py::SECTIONS` 决定它是否进画像
4. `app/memory/manager.py::DEFAULT_IMPORTANCE` 给个默认重要度

### 4.4 改审核规则

只改 `app/memory/rules.py`，它是纯函数。
新增关键词就加到 `FORBIDDEN_KEYWORDS` / `SENSITIVE_KEYWORDS` / `RELATIONSHIP_HINTS`，
然后**必须补测试**（`tests/unit/test_memory.py`）。

### 4.5 加 HTTP 接口

```python
# app/api/v1.py
@router.get("/todos", dependencies=[Depends(require_token)])
async def list_todos(session: AsyncSession = Depends(get_session)) -> dict:
    ...
```

别忘了 `require_token`，否则等于把私人数据暴露到公网。

### 4.6 加定时任务

当前没有调度器。两种做法：
- 进程内：引入 `apscheduler`，在 lifespan 里启动；
- 外部：用 cron/Cloudflare Cron 打一个受保护的 HTTP 接口。

## 5. 代码规范

- 全部 `from __future__ import annotations`，类型注解写全
- 中文注释解释「为什么」，不复述「做了什么」
- 业务逻辑不写在 handler 里；handler 只做：取数据 → 调 service → 回消息
- 所有 IO 失败都要转成有意义的异常（`LLMError` 等），不要裸抛 httpx 的异常
- 新功能必须有测试；隐私相关改动必须有「反例测试」（例如：敏感信息不能被自动保存）
- 提交前 `ruff check .` 和 `pytest -q` 必须全绿

## 6. 提交与部署

```powershell
git add -A
git commit -m "feat: 描述"
git push   # Render 会自动部署（autoDeploy=yes）
```

部署后验证：

```powershell
curl https://zhiwei-u0jc.onrender.com/health
```

> 提交前确认 `.env` 没被加进来（`.gitignore` 已挡，但别用 `git add -f`）。

## 7. 一个必须记住的约束

**单用户**。所有数据都通过 `TELEGRAM_USER_ID` 归属到同一个人，
`AccessMiddleware` 会拦掉其他 Telegram 账号。
如果要变多用户，需要：
1. `users` 已经按 telegram_id 唯一，天然支持；
2. 但 `app/memory/pending.py` 的进程内状态要换成数据库；
3. `app/api/v1.py::_owner()` 要改成按 token 映射用户；
4. 记忆检索、人物、画像的查询本来就带 `user_id`，不用改。
