#!/bin/bash
# 只启动 pip install（不重启容器，容器已 healthy）
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

# 清理旧日志
docker exec "$CONTAINER" rm -f /tmp/pip_install.log

# setsid 后台启动 pip（用 PYTHONUNBUFFERED 让日志实时输出）
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
echo "pip 已启动（torch==2.2.2，PYTHONUNBUFFERED=1）"

sleep 8
echo ""
echo "=== 8s 后状态 ==="
docker exec "$CONTAINER" bash -c 'stat -c "log size=%s modified=%y" /tmp/pip_install.log 2>/dev/null'
docker exec "$CONTAINER" tail -5 /tmp/pip_install.log 2>/dev/null
echo ""
echo "=== pip 进程 ==="
docker exec "$CONTAINER" bash -c 'for pid in /proc/[0-9]*; do comm=$(cat $pid/comm 2>/dev/null); case "$comm" in pip|pip3) echo "pip PID=$(basename $pid)";; esac; done'
