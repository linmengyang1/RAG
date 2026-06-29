#!/bin/bash
# 监控 ingest 进度（v2：用 docker exec，不依赖 docker compose 上下文）
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend
PG=grad-rag-postgres

echo "========== 1. ingest.log 信息 =========="
docker exec "$CONTAINER" bash -c 'stat -c "size=%s bytes  modified=%y" /tmp/ingest.log 2>/dev/null || echo "(日志不存在)"'

echo ""
echo "========== 2. 日志末尾 25 行 =========="
docker exec "$CONTAINER" tail -25 /tmp/ingest.log 2>/dev/null

echo ""
echo "========== 3. python 进程 =========="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in python*|pip*) echo "PID=$(basename $pid) comm=$comm";; esac; done'

echo ""
echo "========== 4. PG documents 状态分布 =========="
docker exec "$PG" psql -U grad -d grad_rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;"

echo ""
echo "========== 5. chunks 统计 =========="
docker exec "$PG" psql -U grad -d grad_rag -c "SELECT COUNT(*) AS total, COUNT(milvus_id) AS with_milvus FROM chunks;"

echo ""
echo "========== 6. Milvus chunks 行数 =========="
docker exec "$CONTAINER" python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://grad-rag-milvus:19530')
print('chunks row_count:', c.get_collection_stats('chunks'))
" 2>&1
