#!/bin/bash
# 诊断 ingest 卡住原因
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== GPU 状态（宿主机 nvidia-smi）==="
nvidia-smi 2>&1 | head -15

echo ""
echo "=== python 进程 CPU（读两次看变化）==="
docker exec "$CONTAINER" bash -c 'cat /proc/398/stat 2>/dev/null | awk "{print \"utime=\"\$14\" stime=\"\$15}"; sleep 3; cat /proc/398/stat 2>/dev/null | awk "{print \"3s后 utime=\"\$14\" stime=\"\$15}"'

echo ""
echo "=== /models/hub 文件详情 ==="
docker exec "$CONTAINER" bash -c 'find /models/hub -type f 2>/dev/null | wc -l; echo "---"; find /models/hub -type f -size +100M 2>/dev/null | head -5; echo "---"; du -sh /models/hub/* 2>/dev/null'

echo ""
echo "=== python 进程打开的网络连接 ==="
docker exec "$CONTAINER" bash -c 'cat /proc/398/net/tcp 2>/dev/null | head -10 || echo "(无法读取)"'

echo ""
echo "=== ingest.log 完整末尾（含 stderr）==="
docker exec "$CONTAINER" bash -c 'tail -30 /tmp/ingest.log 2>/dev/null'
