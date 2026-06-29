#!/bin/bash
# 检查模型下载进度和 python 进程状态
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== /models 目录大小 ==="
docker exec "$CONTAINER" bash -c 'du -sh /models 2>/dev/null; ls -la /models/ 2>/dev/null | head -5'

echo ""
echo "=== huggingface cache 目录 ==="
docker exec "$CONTAINER" bash -c 'find /models -name "*.bin" -o -name "*.safetensors" 2>/dev/null | head -10; du -sh /models/hub 2>/dev/null'

echo ""
echo "=== python 进程 CPU/状态（从 /proc）==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in python*) echo "PID=$(basename $pid)"; cat $pid/stat 2>/dev/null | awk "{print \"  state=\"$3\" utime=\"$14\" stime=\"$15}"; cat $pid/status 2>/dev/null | grep -E "VmRSS|VmSize";; esac; done'

echo ""
echo "=== 当前时间 ==="
docker exec "$CONTAINER" date '+%Y-%m-%d %H:%M:%S'
