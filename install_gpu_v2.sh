#!/bin/bash
# 在容器内用 setsid 彻底后台安装 GPU 依赖
# 用 torch==2.2.2（自带 CUDA runtime 的单 wheel），避免 2.12 的 nvidia-* 拆分包
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag

CONTAINER=grad-rag-backend

# 清理旧日志
docker exec "$CONTAINER" rm -f /tmp/pip_install.log

# setsid 让 pip 脱离 docker exec 会话，彻底独立运行
docker exec -d "$CONTAINER" bash -c '
setsid bash -c "
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    torch==2.2.2 \
    FlagEmbedding>=1.2.10 \
    sentence-transformers>=3.0.0 \
    > /tmp/pip_install.log 2>&1
" < /dev/null > /dev/null 2>&1
'

echo "pip 已用 setsid 后台启动（torch==2.2.2 单 wheel）"
sleep 5
echo ""
echo "=== 5s 后日志 ==="
docker exec "$CONTAINER" tail -5 /tmp/pip_install.log 2>/dev/null || echo "(日志还未生成)"
echo ""
echo "=== setsid pip 进程 ==="
docker exec "$CONTAINER" bash -c "ps aux | grep -E 'pip|setsid' | grep -v grep" 2>/dev/null || echo "(无进程)"
