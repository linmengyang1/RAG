#!/bin/bash
# 在 backend 容器内后台安装 GPU 依赖（torch/FlagEmbedding/sentence-transformers）
# 用法：在 WSL 内执行 bash install_gpu_deps.sh

set -e
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag

# 启动后台 pip install（容器内）
docker compose exec -d backend bash -c '
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "torch>=2.2.0" \
    "FlagEmbedding>=1.2.10" \
    "sentence-transformers>=3.0.0" \
    > /tmp/pip_install.log 2>&1
'

echo "pip 已在容器内后台启动"
sleep 3
echo "--- 当前日志 ---"
docker compose exec backend tail -5 /tmp/pip_install.log 2>/dev/null || echo "(日志还未生成)"
echo "--- pip 进程 ---"
docker compose exec backend bash -c 'ps aux | grep "pip install" | grep -v grep | head -3' 2>/dev/null || echo "(无进程)"
