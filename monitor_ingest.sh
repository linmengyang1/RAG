#!/bin/bash
# 监控 ingest 进度
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== ingest.log 信息 ==="
docker exec "$CONTAINER" bash -c 'stat -c "size=%s modified=%y" /tmp/ingest.log 2>/dev/null'

echo ""
echo "=== 日志末尾 15 行 ==="
docker exec "$CONTAINER" tail -15 /tmp/ingest.log 2>/dev/null

echo ""
echo "=== python 进程 ==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in python*) echo "PID=$(basename $pid) comm=$comm";; esac; done'

echo ""
echo "=== PG documents 状态统计 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;" 2>/dev/null

echo ""
echo "=== PG chunks 数量 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT COUNT(*) FROM chunks;" 2>/dev/null

echo ""
echo "=== Milvus chunks 数量 ==="
docker compose exec postgres bash -c 'echo skip' 2>/dev/null
