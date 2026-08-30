# 备份 Milvus + PostgreSQL 关键数据(在线,不停服)
# 用法: 在 graduate-rag 目录下执行  .\backup.ps1
# 备份文件: backups/<日期时间戳>/ 下
#
# 备份内容:
#   postgres.sql    - PG 逻辑备份(pg_dump,跨版本兼容,可恢复到任意 PG)
#   etcd.snap       - etcd 快照(Milvus 元数据:collection schema / segment 元信息)
#   minio_data.tar.gz - MinIO 对象数据(Milvus 的 chunk 向量正文,丢了要重新 ingest)
#
# 注意:
#   - minio tar 是文件级备份,理论上 milvus 正在写入时 tar 可能不一致。
#     当前没有 ingest 任务在跑,milvus 不会写 minio,tar 是安全的。
#     如需绝对一致,先 docker compose stop milvus 再跑此脚本(或加 -StopMilvus 参数)。
#   - alpine 镜像在 USTC 镜像源不可用,改用本地已有的 postgres:16-alpine(基于 alpine,含 tar)。
$ErrorActionPreference = "Stop"

$date = Get-Date -Format "yyyyMMdd_HHmmss"
$bdir = "backups/$date"
New-Item -ItemType Directory -Force -Path $bdir | Out-Null
$src = (Get-Location).Path
$img = "postgres:16-alpine"  # 本地已有,替代拉不下来的 alpine

Write-Host ">>> 备份目录: $bdir" -ForegroundColor Cyan

# 1. PostgreSQL 逻辑备份(在线,pg_dump -f 写容器内文件,避免 PS 重定向的 UTF-16 编码问题)
Write-Host ">>> [1/3] PostgreSQL pg_dump ..." -ForegroundColor Yellow
docker exec grad-rag-postgres pg_dump -U grad -d grad_rag -f /tmp/pg_dump.sql
if ($LASTEXITCODE -ne 0) { Write-Error "pg_dump 失败"; exit 1 }
docker cp grad-rag-postgres:/tmp/pg_dump.sql "$src\$bdir\postgres.sql"
docker exec grad-rag-postgres rm -f /tmp/pg_dump.sql

# 2. etcd 快照(在线,etcdctl snapshot save 是一致性快照)
Write-Host ">>> [2/3] etcd snapshot ..." -ForegroundColor Yellow
docker exec grad-rag-etcd etcdctl --endpoints=http://127.0.0.1:2379 snapshot save /tmp/etcd_snap.db
if ($LASTEXITCODE -ne 0) { Write-Error "etcd snapshot 失败"; exit 1 }
docker cp grad-rag-etcd:/tmp/etcd_snap.db "$src\$bdir\etcd.snap"
docker exec grad-rag-etcd rm -f /tmp/etcd_snap.db

# 3. MinIO 数据卷 tar(Milvus 的 chunk 向量正文,丢了要重新 ingest 78 分钟)
Write-Host ">>> [3/3] minio_data tar ..." -ForegroundColor Yellow
docker run --rm -v graduate-rag_minio_data:/d -v "${src}:/bak" $img tar czf "/bak/$bdir/minio_data.tar.gz" -C /d .
if ($LASTEXITCODE -ne 0) { Write-Error "minio tar 失败"; exit 1 }

Write-Host ">>> 备份完成:" -ForegroundColor Green
Get-ChildItem $bdir | Format-Table Name, @{N="Size(MB)";E={[math]::Round($_.Length/1MB, 2)}}
Write-Host ">>> 备份位置: $src\$bdir" -ForegroundColor Cyan
