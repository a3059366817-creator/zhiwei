# 部署到 Render（已完成）

**线上地址：<https://zhiwei-u0jc.onrender.com>**
Telegram：`@zhiwei_muchuna_bot`（webhook 模式）· 数据库：Neon · 模型：Cloudflare Workers AI

一键部署脚本：`scripts/deploy_render.py`（GitHub + Render API 全自动，幂等）

```powershell
python scripts/deploy_render.py --github-token <PAT> --render-key <KEY>
```

---

## 部署时踩到的 4 个坑（都已修正）

### 1. 私有仓库 Render 拉不到

Render 需要 GitHub App 授权才能读私有仓库，否则报
`repository URL is invalid or unfetchable`。
**解决**：仓库设为 public（代码不含密钥），或在 Render 里给 GitHub App 授权该仓库。

### 2. `uv pip install .` 构建失败

`pyproject.toml` 没声明 `[build-system]`，pip 退回 setuptools 旧式布局探测，
在扁平目录（app/ migrations/ tests/）下必然失败。
**解决**：改用 hatchling 并声明 `packages = ["app"]`。

### 3. 依赖装完，运行时 `No module named uvicorn`

Render 的运行时是 `/opt/render/project/src/.venv`；
`--system` 装到了系统 Python，不带 `--system` 又装到别处。
**解决**：构建命令显式指定解释器
`uv pip install --python "$(which python)" --no-cache .`，
启动用 `python -m uvicorn ...`（`uvicorn` 这个 bin 不在 PATH 上）。

### 4. 构建期跑 alembic 找不到模块

**解决**：构建期不迁移。应用启动时本来就会执行 `alembic upgrade head`
（`app/main.py` lifespan 里用线程跑，避免 asyncio 嵌套冲突）。

---

## Render 上的配置（已生效）

| 变量 | 值 |
|---|---|
| `APP_ENV` | production |
| `BOT_MODE` | webhook |
| `LLM_PROVIDER` | cloudflare |
| `LLM_FALLBACK_PROVIDER` | （空，云端没有本地 Ollama） |
| `CLOUDFLARE_MODEL` | @cf/meta/llama-3.3-70b-instruct-fp8-fast |
| `CLOUDFLARE_TIMEOUT` | 45 |
| `DATABASE_URL` | Neon（asyncpg + `ssl=require`） |
| `TELEGRAM_WEBHOOK_SECRET` | 部署脚本自动生成 |

构建命令：`uv pip install --python "$(which python)" --no-cache .`
启动命令：`python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## 免费实例注意

- **15 分钟无请求会休眠**，下一条消息要等 30-50 秒冷启动；
- 想避免：用 UptimeRobot 每 10 分钟 ping `/health`，或升级付费实例；
- Cloudflare 免费额度用尽会返回 429，云端没有备用模型，会直接报错
  （建议后续接一个 DeepSeek 当备用）。

## 手工部署（不用脚本时）

1. GitHub 建仓库并推代码
2. Render → New → Web Service → 选仓库
3. Build：`uv pip install --python "$(which python)" --no-cache .`
4. Start：`python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. 填环境变量（见上表）
6. 设 webhook：

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://<你的应用>.onrender.com/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

> webhook 与本地长轮询互斥：云端上线后必须停掉本地进程，否则 Telegram 会报 409。

## 回滚 / 重新部署

```powershell
# 触发一次新部署（用最新提交）
$H = @{ Authorization = "Bearer <RENDER_KEY>"; "Content-Type" = "application/json" }
Invoke-RestMethod -Method Post -Uri "https://api.render.com/v1/services/<SERVICE_ID>/deploys" `
  -Headers $H -Body '{"clearCache":"clear"}'
```

当前 service id：`srv-dc0leom7bikc73b5q2gg`
