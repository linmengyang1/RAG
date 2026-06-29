#!/bin/bash
# 1. docker commit 保存当前容器（含 torch/FlagEmbedding 等）
# 2. force-recreate 应用 GPU 配置
# 3. 验证 CUDA
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 1. docker commit 保存当前容器状态 ==="
docker commit "$CONTAINER" graduate-rag-backend:latest 2>&1 | tail -3
docker images graduate-rag-backend --format '{{.Repository}}:{{.Tag}} {{.Size}} {{.CreatedSince}}'

echo ""
echo "=== 2. force-recreate backend（应用 GPU 配置）==="
docker compose up -d --force-recreate backend 2>&1 | tail -5

echo ""
echo "=== 3. 等待 healthy ==="
for i in $(seq 1 30); do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)
  echo "  尝试 $i: $status"
  if [ "$status" = "healthy" ]; then
    break
  fi
  sleep 2
done

echo ""
echo "=== 4. 验证 GPU + 所有依赖 ==="
docker exec "$CONTAINER" python check_gpu.py 2>&1
