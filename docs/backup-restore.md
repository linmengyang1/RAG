# Milvus + PostgreSQL 备份与恢复

## 概述

本项目数据分布在三个关键 Docker volume，丢了任何一项都要付出昂贵代价：

| Volume | 容器内挂载点 | 内容 | 丢了的影响 |
|--------|------------|------|-----------|
| `graduate-rag_minio_data` | `/minio_data` | Milvus 的 chunk 向量正文 | **重新 ingest 约 78 分钟**（BGE-M3 推理 3271 个 chunk） |
| `graduate-rag_etcd_data` | `/etcd` | Milvus 元数据（collection schema / segment 元信息） | collection 不存在，检索全部失败 |
| `graduate-rag_postgres_data` | `/var/lib/postgresql/data` | PG 全部数据（documents/chunks/mentors/wiki/conversations/messages/users） | 用户、聊天历史、导师映射全丢 |

> 注：`milvus_data` / `huggingface_cache` / `mineru_cache` 不需要备份，前者是运行时状态可从 etcd+minio 重建，后两者是缓存可重新下载/生成。

---

## 备份

### 一键备份（推荐）

```powershell
cd c:\Users\lmy\Desktop\test\graduate-rag
.\backup.ps1
```

每次执行生成一个带时间戳的目录：`backups\<yyyyMMdd_HHmmss>\`，不覆盖旧备份。

### 备份产物

| 文件 | 备份方式 | 说明 |
|------|---------|------|
| `postgres.sql` | `pg_dump`（逻辑备份） | 跨 PG 版本可恢复，纯 SQL 文本 |
| `etcd.snap` | `etcdctl snapshot save` | etcd 官方在线一致性快照 |
| `minio_data.tar.gz` | `tar` 文件级打包 | 当前无 ingest 时 milvus 不写 minio，tar 安全 |

**特点**：在线备份，不停服，约 4 秒完成，总大小约 33 MB。

---

## 恢复

### 一键恢复（推荐）

```powershell
cd c:\Users\lmy\Desktop\test\graduate-rag
.\restore.ps1 backups\20260826_214456
```

脚本会要求输入 `yes` 确认（破坏性操作，会清空当前数据）。恢复流程：
1. 停服 `docker compose stop`
2. minio_data：清空 + tar 解包
3. etcd_data：清空 + `etcdctl snapshot restore --force-new-cluster`
4. postgres：启动 + `DROP/CREATE DATABASE` + `psql -f` 导入 SQL
5. 启所有服务 `docker compose up -d`

恢复后约 30-60 秒 backend 完成 lifespan 初始化（会自动 `load_collection`），即可正常检索。

### 手动恢复步骤（脚本不可用时）

如果 `restore.ps1` 无法执行，按以下步骤手动恢复。假设备份目录为 `backups\20260826_214456`。

#### 0. 停服

```powershell
cd c:\Users\lmy\Desktop\test\graduate-rag
docker compose --env-file .env stop
```

#### 1. 恢复 minio_data

```powershell
# 清空 minio_data volume + tar 解包（用本地已有的 postgres:16-alpine 替代 alpine）
docker run --rm -v graduate-rag_minio_data:/d -v "${PWD}:/bak" postgres:16-alpine sh -c "rm -rf /d/* /d/.[!.]* 2>/dev/null; tar xzf /bak/backups/20260826_214456/minio_data.tar.gz -C /d"
```

#### 2. 恢复 etcd_data

```powershell
# 先清空（etcd snapshot restore 要求 data-dir 为空）
docker run --rm -v graduate-rag_etcd_data:/d postgres:16-alpine sh -c "rm -rf /d/* /d/.[!.]* 2>/dev/null"
# snapshot restore（--force-new-cluster: 单机恢复，避免旧集群成员冲突）
docker run --rm --entrypoint sh -v graduate-rag_etcd_data:/d -v "${PWD}:/bak" quay.io/coreos/etcd:v3.5.5 -c "etcdctl snapshot restore /bak/backups/20260826_214456/etcd.snap --data-dir /d --force-new-cluster"
```

#### 3. 恢复 PostgreSQL

```powershell
# 启动 postgres
docker compose --env-file .env up -d postgres
Start-Sleep 6  # 等 ready
# 先 DROP/CREATE，避免和现有表冲突
docker exec grad-rag-postgres psql -U grad -d postgres -c "DROP DATABASE IF EXISTS grad_rag;"
docker exec grad-rag-postgres psql -U grad -d postgres -c "CREATE DATABASE grad_rag OWNER grad;"
# 用 docker cp + psql -f 导入（避免 PowerShell 重定向的 UTF-16 编码问题）
docker cp "backups\20260826_214456\postgres.sql" grad-rag-postgres:/tmp/pg_dump.sql
docker exec grad-rag-postgres psql -U grad -d grad_rag -f /tmp/pg_dump.sql
docker exec grad-rag-postgres rm -f /tmp/pg_dump.sql
```

#### 4. 启所有服务 + 验证

```powershell
docker compose --env-file .env up -d
# 等 30 秒后验证
docker exec -w /app/backend grad-rag-backend python -c "from pymilvus import MilvusClient; from app.core.config import settings; print(MilvusClient(uri=settings.milvus_uri).get_collection_stats(settings.milvus_collection_chunks))"
# 应输出 row_count > 0
```

---

## 备份策略

### 何时备份

- **重要操作前必做**：`init_milvus.py --force`、清数据、升级镜像、改 docker-compose
- **每周一次定期**：数据小（33 MB），成本极低
- **大改 ingest 后**：调整 chunker / embedding 模型 / schema 后

### 保留策略

- 保留最近 3 份备份即可（旧的可以删）
- 关键备份（如发版前）建议复制一份到其他磁盘，防止 WSL2 虚拟磁盘整体损坏

### 清理旧备份

```powershell
# 删除某个旧备份目录
Remove-Item -Recurse -Force backups\20260826_214456
```

---

## 故障案例：Milvus 数据丢失（2026-08-26）

### 现象

无论问什么都返回"未检索到相关资料，无法回答"。日志显示 `向量检索 0.3s / 关键词检索 0.0s / LLM 生成 0.0s`，但出现 `MilvusException (code=106, collection on recovering)`。

### 根因

- **PostgreSQL 完好**：732 documents / 3271 chunks，全部 `status=embedded`，全部有 `milvus_id`
- **Milvus chunks collection 完空**：`num_entities=0`，但 `load_state=Loaded`
- **判断**：etcd 元数据还在（collection 存在，collection_id 没变），但 minio 对象存储数据丢了。典型的"etcd 元数据还在 / minio 数据丢失"故障，通常由 WSL2 强制关闭或 docker volume 被清理导致

### 修复（已执行）

1. 只 drop + recreate `chunks` collection（不用 `init_milvus.py --force`，那会误删 wiki）
2. 清 PG 的 `documents` / `chunks` 表（保留 wiki_entries / wiki_links / mentors / conversations / messages / users）
3. 重跑 `python -m app.cli.ingest`：732 文档全部成功，3271 chunks，耗时 78 分钟
4. 验证：`hybrid_search("王法胜是谁")` 命中 score=0.976，`hybrid_search("郑蕊蕊")` 命中 score=0.989

### 教训

- **没有备份 → 重新 ingest 78 分钟**。本案例之后才建立 `backup.ps1` / `restore.ps1`
- `init_milvus.py --force` 会同时 drop chunks 和 wiki 两个 collection，重建时要注意
- hybrid_search 的 dense/sparse 检索没有异常处理，Milvus 报 106 会直接抛出（未来可加 try/except + load 状态自愈）

### 已知遗留

- Milvus 的 `wiki` collection 向量也丢了（`num_entities=0`），但 PG 的 `wiki_entries` 还在，wiki 界面不受影响。chat 默认 `enable_wiki=False`，不影响问答。如需启用 wiki 第三路检索，需单独重建 wiki 向量。

---

## 注意事项

1. **WSL2 关闭方式**：用 `wsl --shutdown` 优雅关闭，不要直接关窗口或强制关机，避免 etcd WAL / minio 数据损坏（docker-compose.yml 里 etcd 已设 `stop_grace_period: 60s` 缓解）
2. **alpine 镜像拉不下来**：本项目用 USTC 镜像源不可用，`backup.ps1` / `restore.ps1` 改用本地已有的 `postgres:16-alpine`（基于 alpine，含 tar/sh/rm）替代
3. **恢复后等 30-60 秒**：backend 启动时 lifespan 会重新调 `_ensure_milvus_collections` → `load_collection`，加载完才能检索
4. **不要备份 milvus_data**：它是运行时状态（rocksdb/日志），从 etcd+minio 可重建，备份它没意义且可能不一致
5. **恢复脚本未实跑测试**：`restore.ps1` 逻辑参照 docker-compose.yml 配置编写，当前数据完好未实际执行过。首次使用建议在测试环境验证
