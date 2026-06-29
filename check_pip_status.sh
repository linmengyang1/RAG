#!/bin/bash
# 检查容器内 pip install 进度
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag

echo "=== pip_install.log 末尾 ==="
docker compose exec backend tail -10 /tmp/pip_install.log 2>/dev/null || echo "(无法读取日志)"

echo ""
echo "=== pip 进程 ==="
docker compose exec backend bash -c 'ps aux | grep -E "pip|python" | grep -v grep' 2>/dev/null || echo "(无 pip 进程)"

echo ""
echo "=== torch 是否已装 ==="
docker compose exec backend python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" 2>&1 || echo "(torch 不可用)"
