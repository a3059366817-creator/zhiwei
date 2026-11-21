# 数据库设计

生产：Neon PostgreSQL 18 · 本地：SQLite（`data/zhiwei.db`）
两者共用同一套 SQLAlchemy 模型与 Alembic 迁移，只靠 `DATABASE_URL` 切换。

## 1. 表结构

### users — 用户

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | UUID |
| telegram_id | **BIGINT** UNIQUE | Telegram 用户 ID（**必须 BIGINT**，见踩坑） |
| username | VARCHAR(64) | 可为空 |
| display_name | VARCHAR(64) | 可为空 |
| created_at / updated_at | TIMESTAMPTZ | 自动维护 |

### conversations — 会话

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| user_id | FK → users.id | 级联删除 |
| title | VARCHAR(200) | 目前不填 |
| status | VARCHAR(20) | `active` / `archived`（`/new` 时归档旧会话） |

### messages — 消息

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| conversation_id | FK → conversations.id | 级联删除 |
| role | VARCHAR(20) | `user` / `assistant` |
| content | TEXT | 原文 |
| model_name | VARCHAR(80) | 哪个模型生成的，便于排查 |
| created_at | TIMESTAMPTZ | 建索引，倒序取最近 N 条 |

### memories — 正式长期记忆

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| user_id | FK → users.id | |
| category | VARCHAR(30) | `profile` / `preference` / `experience` / `relationship` / `context` |
| content | TEXT | 一句完整的第三人称陈述 |
| importance | INTEGER | 1–5，检索加权用 |
| source_message_id | FK → messages.id | **来源可追溯**，消息删除后置 NULL |
| status | VARCHAR(20) | `active`（删除是真删，不用标记删除） |
| expires_at | TIMESTAMPTZ | 情境记忆 14 天过期，检索时过滤 |

### memory_candidates — 待确认候选

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| user_id | FK → users.id | |
| category / content | | 同 memories |
| reason | TEXT | 模型给的理由，或规则的判定理由 |
| source_message_id | FK → messages.id | |
| sensitivity_level | VARCHAR(20) | `normal` / `sensitive` |
| person_name / relation_type | VARCHAR(80/40) | **仅关系类候选**：确认后据此归档 people/relationships |
| status | VARCHAR(20) | `pending` / `approved` / `rejected` / `never_ask` |
| created_at / reviewed_at | TIMESTAMPTZ | |

### people — 人物档案

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| user_id | FK → users.id | |
| name | VARCHAR(80) | 用户怎么称呼（原词） |
| description | TEXT | 备注 |

### relationships — 人物关系

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| user_id / person_id | FK | person 删除时级联 |
| relation_type | VARCHAR(40) | 母亲 / 同事 / 大学室友… |
| description | TEXT | |
| source_message_id | FK → messages.id | **保留来源**，规格 3.2C 要求 |

### settings — 用户设置

| 列 | 类型 | 说明 |
|---|---|---|
| user_id | FK UNIQUE | |
| model_provider / model_name | VARCHAR | 预留（当前模型由环境变量决定） |
| memory_enabled | BOOLEAN | 总开关 |
| auto_save_enabled | BOOLEAN | `/memory off` 会把它设为 false |

## 2. 关系图

```
users 1 ── n conversations 1 ── n messages
  │                                  ▲
  ├── n memories.source_message_id ───┘
  ├── n memory_candidates.source_message_id ┘
  ├── n people 1 ── n relationships.source_message_id
  └── 1 settings
```

## 3. 迁移

```powershell
# 应用迁移（本地/云端都一样）
python -m alembic upgrade head

# 改完 models.py 后生成新迁移
python -m alembic revision --autogenerate -m "描述"
```

现有迁移：

| 版本 | 内容 |
|---|---|
| `276555ecb36f` | 初始 schema（8 张表） |
| `176813c6f087` | memory_candidates 增加 person_name / relation_type |
| `1cafcf7526e2` | users.telegram_id 从 INTEGER 改 BIGINT |

应用启动时会自动执行 `upgrade head`（`app/main.py` 的 lifespan，放在线程里跑）。

## 4. 三个必须知道的坑

### 4.1 telegram_id 必须是 BIGINT

Telegram ID 已超过 int32 上限（例如 `9035481188`）。
SQLite 不校验长度，所以本地一切正常；Postgres 会直接报
`value out of int32 range`。这是切库当天才炸出来的问题。

### 4.2 不要在 alembic.ini 里写中文

Alembic 用**系统 locale 编码**读 ini（中文 Windows 是 GBK），
写 UTF-8 中文会 `UnicodeDecodeError`。该文件必须保持纯 ASCII。

### 4.3 本地 SQLite 与云端 Postgres 的差异

| 行为 | SQLite | Postgres |
|---|---|---|
| 类型检查 | 宽松（INTEGER 能存大数） | 严格 |
| 时区 | 存的是 naive datetime | TIMESTAMPTZ，asyncpg 要求 aware |
| DDL | 非事务 | 事务 |

迁移脚本 `scripts/migrate_to_postgres.py` 已处理 naive → UTC 的转换，
并按外键顺序复制、保留原 id、可重复执行。

## 5. 备份与恢复（Neon）

- Neon 控制台有 **Point-in-time restore**（免费额度内可回滚）
- 手动导出：

```bash
pg_dump "postgresql://neondb_owner:...@ep-...neon.tech/neondb?sslmode=require" > backup.sql
```

- 本地回灌：

```bash
psql "$DATABASE_URL" < backup.sql
```

> 删除记忆是**真删除**（`DELETE FROM memories`），不是软删除；
> 误删只能靠 Neon 的 PITR 恢复，所以重要数据建议定期 `pg_dump`。
