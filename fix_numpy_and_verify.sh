#!/bin/bash
# 降级 numpy 到 <2.0（torch 2.2.2 兼容性），然后完整验证 GPU 依赖
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 1. 降级 numpy（torch 2.2.2 需要 numpy<2.0）==="
docker exec "$CONTAINER" pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "numpy<2.0" 2>&1 | tail -5

echo ""
echo "=== 2. 完整 GPU 验证 ==="
docker exec "$CONTAINER" python check_gpu.py 2>&1
