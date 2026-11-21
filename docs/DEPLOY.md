# 部署到 Render（详细步骤）

代码已经准备好：`Dockerfile`、`render.yaml`、Alembic 迁移、健康检查 `/health` 都在。
数据库已经跑在 Neon 上（PostgreSQL 18）。

---

## 一、推代码到 GitHub

项目已经初始化好 git 仓库并提交过一次。你只需要建远程仓库并推：

```powershell
cd D:\develop\AI好友\zhiwei

# 1. 在 GitHub 上新建一个空仓库（不要勾选 README/.gitignore）
# 2. 关联并推送（把 URL 换成你自己的）
git remote add origin https://github.com/<你的用户名>/zhiwei.git
git branch -M main
git push -u origin main
```

> 如果提示要登录：用 GitHub 的 Personal Access Token 当密码（Settings → Developer settings → Tokens）。

## 二、Render 创建服务

1. 打开 <https://dashboard.render.com> → **New** → **Blueprint**
2. 选择刚推上去的仓库（Render 会自动读取 `render.yaml`）
3. 它会创建 Web Service `zhiwei`，区域 `singapore`，健康检查 `/health`
4. 在 **Environment** 里填这几个变量（`render.yaml` 里标了 `sync: false` 的都必须手填）：

| 变量 | 值 |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://neondb_owner:...@ep-...neon.tech/neondb?ssl=require` |
| `TELEGRAM_BOT_TOKEN` | 你的 bot token（从 `.env` 里复制） |
| `TELEGRAM_USER_ID` | 你的 Telegram 用户 ID（给 bot 发 `/id` 可得） |
| `GEMINI_API_KEY` | 你的 Gemini key（不填也行，见下） |

5. 点 **Deploy**，等构建完成（首次约 3-5 分钟）

## 三、设置 Telegram Webhook

部署完成后，Render 会给你一个 `https://zhiwei-xxxx.onrender.com` 域名：

```powershell
# 先把 BOT_MODE 改成 webhook（render.yaml 里已设为 webhook）
# 生成一个随机 secret 填进 Render 的 TELEGRAM_WEBHOOK_SECRET，然后：
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" `
  -d "url=https://<你的应用>.onrender.com/webhook/telegram" `
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

验证：

```powershell
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

> 注意：**webhook 和本地长轮询不能同时用**。云端跑起来后，把本地这个进程停掉，
> 否则两边抢同一个 bot（Telegram 会报 409）。

## 四、模型选择

| 场景 | 建议 |
|---|---|
| 云端（Render，海外） | `LLM_PROVIDER=gemini`，直连 Google 无需代理 |
| 本地（国内） | `LLM_PROVIDER=ollama` 或 `deepseek` |

云端没有本地 Ollama，所以 Render 上必须用 `gemini` / `openrouter` / `deepseek` 之一。
如果暂时没有 Gemini key，可以先用 `deepseek`（国内可直连，但 Render 在海外也访问得到）。

## 五、免费实例注意事项（规格 9.3 已说明）

- Render 免费实例 **15 分钟无请求会休眠**，下次消息要等 30-50 秒冷启动；
- Neon 免费额度有计算时间限制；
- 两者都可能被服务商调整。

如果嫌冷启动慢，可以：

- 用 UptimeRobot 之类的服务每 10 分钟 ping 一次 `/health`；
- 或者升级 Render 付费实例（$7/月，不休眠）。

## 六、部署后自检

```powershell
curl https://<你的应用>.onrender.com/health
```

应返回：

```json
{"status":"ok","database":true,"config":{"database":"postgres", ...}}
```

然后在 Telegram 里给 @zhiwei_muchuna_bot 发消息，看是否正常回复、记忆是否写入 Neon。
