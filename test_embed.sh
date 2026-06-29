#!/bin/bash
# 测试 BGE-M3 模型加载 + 向量化（离线模式）
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 测试模型加载 + 向量化（HF_HUB_OFFLINE=1）==="
docker exec -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 "$CONTAINER" python -c "
import time
t0 = time.time()
from FlagEmbedding import BGEM3FlagModel
print(f'[{time.time()-t0:.1f}s] 导入完成')
m = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True, device='cuda')
print(f'[{time.time()-t0:.1f}s] 模型加载完成')
out = m.encode(['测试文本', '研究生导师信息'], batch_size=2)
print(f'[{time.time()-t0:.1f}s] 向量化完成')
print('dense shape:', out['dense_vecs'].shape)
print('sparse 数量:', len(out['lexical_weights']))
print('第1个 sparse keys:', list(out['lexical_weights'][0].keys())[:5])
" 2>&1 | tail -15
