# 一键恢复 Milvus + PostgreSQL 数据（从 backup.ps1 生成的备份目录）
# 用法: .\restore.ps1 backups\20260826_214456
# 警告: 会清空当前 minio_data / etcd_data / postgres 数据，不可逆！
#
# 恢复流程:
#   1. 停服（保证数据一致性）
#   2. minio_data: 清空 + tar 解包
#   3. etcd_data:   清空 + etcdctl snapshot restore（--force-new-cluster 单机恢复）
#   4. postgres:    启动 + DROP/CREATE DATABASE + psql 导入 SQL
#   5. 启所有服务
#
# 注意:
#   - etcd snapshot restore 要求 data-dir 为空，所以先清空 etcd_data volume
#   - PG 用 psql -f 导入（避免 PowerShell 重定向的 UTF-16 编码问题）
#   - 恢复后 milvus 会自动加载 collection（lifespan 里 _ensure_milvus_collections 会调 load）
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$BackupDir
)

$ErrorActionPreference = "Stop"

# 解析备份目录（支持相对/绝对路径）
if (-not (Test-Path $BackupDir -PathType Container)) {
    Write-Error "备份目录不存在: $BackupDir"
    exit 1
}
$abs = (Resolve-Path $BackupDir).Path

# 校验三个文件齐全
foreach ($f in @("postgres.sql", "etcd.snap", "minio_data.tar.gz")) {
    if (-not (Test-Path "$abs\$f")) {
        Write-Error "备份文件缺失: $abs\$f"
        exit 1
    }
}

Write-Host ">>> 将从备份恢复: $abs" -ForegroundColor Cyan
Write-Host ">>> 警告: 此操作会清空当前 minio/etcd/postgres 数据，不可逆!" -ForegroundColor Red
$confirm = Read-Host "确认恢复? 输入 yes 继续"
if ($confirm -ne "yes") {
    Write-Host "已取消"
    exit 0
}

$envFile = if (Test-Path .env) { ".env" } else { ".env.example" }
$pgImg = "postgres:16-alpine"            # 本地已有，含 tar/sh/rm
$etcdImg = "quay.io/coreos/etcd:v3.5.5" # 和 docker-compose 一致

Write-Host ">>> 停止所有服务 ..." -ForegroundColor Yellow
docker compose --env-file $envFile stop

Write-Host ">>> [1/4] 恢复 minio_data（清空 + tar 解包）..." -ForegroundColor Yellow
docker run --rm -v graduate-rag_minio_data:/d -v "${abs}:/bak" $pgImg `
    sh -c "rm -rf /d/* /d/.[!.]* 2>/dev/null; tar xzf /bak/minio_data.tar.gz -C /d"

Write-Host ">>> [2/4] 恢复 etcd_data（清空 + snapshot restore）..." -ForegroundColor Yellow
# 先清空（etcd snapshot restore 要求 data-dir 为空）
docker run --rm -v graduate-rag_etcd_data:/d $pgImg `
    sh -c "rm -rf /d/* /d/.[!.]* 2>/dev/null"
# snapshot restore（--force-new-cluster: 单机恢复，避免旧集群成员冲突）
docker run --rm --entrypoint sh -v graduate-rag_etcd_data:/d -v "${abs}:/bak" $etcdImg `
    -c "etcdctl snapshot restore /bak/etcd.snap --data-dir /d --force-new-cluster"

Write-Host ">>> [3/4] 启动 PostgreSQL + 恢复 SQL ..." -ForegroundColor Yellow
docker compose --env-file $envFile up -d postgres
Start-Sleep 6  # 等 PG ready
# 先 DROP/CREATE，避免和现有表冲突（pg_dump 是纯 SQL，不含 DROP）
docker exec grad-rag-postgres psql -U grad -d postgres -c "DROP DATABASE IF EXISTS grad_rag;"
docker exec grad-rag-postgres psql -U grad -d postgres -c "CREATE DATABASE grad_rag OWNER grad;"
# 用 docker cp + psql -f 导入（避免 PowerShell 重定向编码问题）
docker cp "$abs\postgres.sql" grad-rag-postgres:/tmp/pg_dump.sql
docker exec grad-rag-postgres psql -U grad -d grad_rag -f /tmp/pg_dump.sql
docker exec grad-rag-postgres rm -f /tmp/pg_dump.sql

Write-Host ">>> [4/4] 启动所有服务 ..." -ForegroundColor Yellow
docker compose --env-file $envFile up -d

Write-Host ">>> 恢复完成。等待 backend 启动后可用（约 30-60 秒）。" -ForegroundColor Green
Write-Host ">>> 验证（等 30 秒后执行）:" -ForegroundColor Cyan
Write-Host "    docker exec -w /app/backend grad-rag-backend python -c `"from pymilvus import MilvusClient; from app.core.config import settings; print(MilvusClient(uri=settings.milvus_uri).get_collection_stats(settings.milvus_collection_chunks))`"" -ForegroundColor Cyan
