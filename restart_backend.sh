#!/bin/bash
# 重启 backend 并等待 healthy
set -u
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag

echo "=== 重启 backend ==="
docker compose restart backend 2>&1 | tail -3

echo
echo "=== 等待 healthy ==="
for i in $(seq 1 8); do
    sleep 5
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' grad-rag-backend 2>/dev/null)
    echo "  [$i] health=$STATUS"
    [ "$STATUS" = "healthy" ] && break
done

echo
echo "=== 验证 transformers 版本 ==="
docker exec grad-rag-backend python -c "import transformers; print(f'transformers: {transformers.__version__}')" 2>&1

echo
echo "=== health 端点 ==="
curl -sS http://localhost:18000/health 2>&1
