#!/bin/bash
# 后台启动 ingest 管线（setsid 独立运行）
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

# 清理旧日志
docker exec "$CONTAINER" rm -f /tmp/ingest.log

# 清理上次失败的 documents（级联删除 chunks，因为 ON DELETE CASCADE）
echo "=== 清理上次失败的 documents ==="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "DELETE FROM documents WHERE status='failed' RETURNING id;" | tail -5
echo "--- 清理后状态 ---"
docker exec grad-rag-postgres psql -U grad -d grad_rag -t -c "SELECT 'documents='||COUNT(*) FROM documents;"
docker exec grad-rag-postgres psql -U grad -d grad_rag -t -c "SELECT 'chunks='||COUNT(*) FROM chunks;"

# setsid 后台启动 ingest
# 关键：HF_HUB_OFFLINE=1 + TRANSFORMERS_OFFLINE=1 避免联网检查 .DS_Store（hf-mirror 会 403）
docker exec -d "$CONTAINER" bash -c '
setsid bash -c "
export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
cd /app/backend
python -m app.cli.ingest --limit-md 24 --limit-pdf 5 > /tmp/ingest.log 2>&1
" < /dev/null > /dev/null 2>&1
'
echo "ingest 已后台启动（md 24 + pdf 5，离线模式）"

sleep 8
echo ""
echo "=== 8s 后状态 ==="
docker exec "$CONTAINER" bash -c 'stat -c "log size=%s modified=%y" /tmp/ingest.log 2>/dev/null'
echo "--- 日志末尾 ---"
docker exec "$CONTAINER" tail -8 /tmp/ingest.log 2>/dev/null || echo "(日志还未生成)"
echo ""
echo "=== python 进程 ==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in python*|pip*) echo "PID=$(basename $pid) comm=$comm";; esac; done'
