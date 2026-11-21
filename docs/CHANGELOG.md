# 变更与决策记录

## V1.0（2026-11-21）

从零搭建到云端上线，一天内完成 P0–P8。

### 阶段交付

| 阶段 | 内容 | 结果 |
|---|---|---|
| P0 | 项目骨架、配置、日志、数据库、Alembic、健康检查 | ✅ |
| P1 | aiogram 3 Bot、命令、按钮、访问控制 | ✅ |
| P2 | 模型适配器（Ollama / Gemini / OpenRouter / DeepSeek / Cloudflare）+ 主备路由 | ✅ |
| P3 | 多轮对话、会话管理、历史查询 | ✅ |
| P4 | Neon PostgreSQL + 迁移 | ✅ |
| P5 | 记忆提取 → 审核 → 确认 → 入库 → 检索 | ✅ |
| P6 | 个人画像 + 人物档案与关系 | ✅ |
| P7 | Render 云端部署（webhook） | ✅ |
| P8 | 安全加固 + 验收测试 | ✅ |

### 关键决策

1. **渐进式落库**：规格要求 Postgres + Gemini，但本地先跑 SQLite + Ollama，
   靠 `DATABASE_URL` / `LLM_PROVIDER` 切换，不重写代码。事后证明这是对的——
   本地一天内验证完所有业务逻辑，切云只花了配置时间。

2. **模型只提议**：`extractor` 输出 JSON，Pydantic 校验，`rules.py` 定去留。
   模型没有任何写库路径。

3. **审核规则用纯函数**：好测试、好改、可穷举。

4. **画像不建表**：由 memories 投影，避免双份数据。

5. **上下文按需注入**：记忆 top6 + 只注入被提到的人。

6. **额外加了 DeepSeek 适配器**：规格只写了 Gemini/OpenRouter，但国内开发者
   需要能直连的备选；多一个 provider 不影响架构。

### 踩过的坑（按发现顺序）

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | PowerShell 改写 `.env` 导致中文变乱码 | PS 5.1 按 GBK 读 UTF-8 再写回 | 改用直接复制，不做文本改写 |
| 2 | `alembic.ini` 报 UnicodeDecodeError | Alembic 用系统 locale 读 ini | 文件保持纯 ASCII |
| 3 | `TELEGRAM_USER_ID=` 留空导致启动崩溃 | 空串不能转 int | 加 `field_validator` 转 None |
| 4 | Cloudflare 返回 `sensitivity:"high"` 整批候选被丢 | Pydantic 枚举校验太严 | 加 `_coerce_sensitivity` / `_coerce_category` |
| 5 | 「我妈生日」被自动存成偏好 | 模型把关系信息判成 preference | 加 `RELATIONSHIP_HINTS`（45 个称谓），涉及他人强制确认 |
| 6 | 「我室友叫小林，在做后端」人丢了 | 模型拆成 profile | 提示词加硬规则：介绍人物必须用 relationship 并填 person_name |
| 7 | 切 Neon 时报 `value out of int32 range` | `telegram_id` 用了 INTEGER | 改 BIGINT + 迁移 `1cafcf7526e2` |
| 8 | Render 拉不到私有仓库 | 缺 GitHub App 授权 | 仓库转 public |
| 9 | Render 构建失败（setuptools 旧布局） | 缺 `[build-system]` | 加 hatchling + `packages=["app"]` |
| 10 | 运行时 `No module named uvicorn` | 装到了系统 Python，运行时用 `.venv` | `uv pip install --python "$(which python)"` + `python -m uvicorn` |
| 11 | 构建期 alembic 找不到模块 | 构建环境路径不同 | 改为应用启动时自动迁移 |
| 12 | webhook 密钥被误提交到公开仓库 | 调试脚本写了临时文件 | 轮换密钥 + 清理 + `.gitignore` |

### 已知未做

- 待办 / 定时提醒（规格 V1.0 未包含，由独立 Node 版承担）
- 向量检索（记忆量上来后需要 pgvector）
- 流式回复
- 多用户
- 云端备用模型（Cloudflare 额度用尽时会报错）

## 待办（后续可做）

- [ ] 把 Node 版的待办提醒并入云端（电脑关机也能提醒）
- [ ] 云端加 DeepSeek 作为 Cloudflare 的兜底
- [ ] 记忆检索升级到 pgvector
- [ ] 人物关系支持「共同经历」字段
- [ ] `/settings` 命令（模型切换、静音时段）
- [ ] UptimeRobot 保活，消除 30–50 秒冷启动
