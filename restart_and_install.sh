#!/bin/bash
# 重启 backend 容器，清理所有 pip 进程，然后启动一个干净的 pip install
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 1. 重启 backend 容器（清理所有 pip 进程）==="
docker compose restart backend
echo "等待 healthy..."
for i in $(seq 1 30); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)
  if [ "$status" = "healthy" ]; then
    echo "  backend healthy (尝试 $i)"
    break
  fi
  sleep 2
done

echo ""
echo "=== 2. 确认无残留 pip 进程 ==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in pip|pip3) echo "残留: PID=$(basename $pid) comm=$comm";; esac; done; echo "检查完毕"'

echo ""
echo "=== 3. 清理旧日志 ==="
docker exec "$CONTAINER" rm -f /tmp/pip_install.log

echo ""
echo "=== 4. 启动 pip install（torch==2.2.2，setsid 后台）==="
docker exec -d "$CONTAINER" bash -c '
setsid bash -c "
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONUNBUFFERED=1
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    torch==2.2.2 \
    FlagEmbedding>=1.2.10 \
    sentence-transformers>=3.0.0 \
    > /tmp/pip_install.log 2>&1
" < /dev/null > /dev/null 2>&1
'
echo "pip 已启动"

sleep 5
echo ""
echo "=== 5. 5s 后状态 ==="
docker exec "$CONTAINER" bash -c 'stat -c "log size=%s modified=%y" /tmp/pip_install.log 2>/dev/null; for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in pip|pip3) echo "pip PID=$(basename $pid)";; esac; done'
