#!/bin/bash
# 检查模型缓存结构 + 补全 .DS_Store 文件
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 模型缓存目录结构 ==="
docker exec "$CONTAINER" bash -c 'ls -la /models/hub/models--BAAI--bge-m3/snapshots/ 2>/dev/null'

echo ""
echo "=== snapshot 内容 ==="
docker exec "$CONTAINER" bash -c 'SNAP=$(ls -d /models/hub/models--BAAI--bge-m3/snapshots/*/ 2>/dev/null | head -1); echo "snapshot: $SNAP"; ls -la "$SNAP" 2>/dev/null; echo "---imgs---"; ls -la "$SNAP/imgs/" 2>/dev/null || echo "(imgs 目录不存在)"'

echo ""
echo "=== 创建 imgs/.DS_Store 空文件补全缓存 ==="
docker exec "$CONTAINER" bash -c '
SNAP=$(ls -d /models/hub/models--BAAI--bge-m3/snapshots/*/ 2>/dev/null | head -1)
if [ -z "$SNAP" ]; then
  echo "找不到 snapshot 目录"
  exit 1
fi
SNAP=${SNAP%/}
mkdir -p "$SNAP/imgs"
touch "$SNAP/imgs/.DS_Store"
# 同时在 blobs 里创建（HF 用 symlink）
echo "已创建: $SNAP/imgs/.DS_Store"
ls -la "$SNAP/imgs/.DS_Store"
'

echo ""
echo "=== 测试模型能否加载（不联网）==="
docker exec -e HF_HUB_OFFLINE=1 "$CONTAINER" python -c "
from FlagEmbedding import BGEM3FlagModel
print('开始加载...')
m = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True, device='cuda')
print('加载成功!')
out = m.encode(['测试文本'], batch_size=1)
print('向量化成功: dense shape =', out['dense_vecs'].shape)
" 2>&1 | tail -10
