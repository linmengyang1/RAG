#!/bin/bash
# 用 /proc 检查进程（容器无 ps 命令）
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== pip_install.log 修改时间 + 大小 ==="
docker exec "$CONTAINER" bash -c 'stat -c "size=%s modified=%y" /tmp/pip_install.log 2>/dev/null'

echo ""
echo "=== 容器内所有进程（用 /proc）==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do
  p=$(basename $pid)
  comm=$(cat $pid/comm 2>/dev/null)
  echo "  PID=$p comm=$comm"
done'

echo ""
echo "=== 当前时间 ==="
docker exec "$CONTAINER" date '+%Y-%m-%d %H:%M:%S'

echo ""
echo "=== 日志末尾 ==="
docker exec "$CONTAINER" tail -5 /tmp/pip_install.log 2>/dev/null
