#!/bin/bash
# 测试 FlagEmbedding 1.2.10 的 encode 参数
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

docker exec -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 "$CONTAINER" python -c "
from FlagEmbedding import BGEM3FlagModel
import inspect

# 查看 encode 方法签名
print('encode 签名:')
print(inspect.signature(BGEM3FlagModel.encode))

# 测试带 return_sparse
m = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True, device='cuda')
out = m.encode(['测试文本', '导师信息'], batch_size=2, return_dense=True, return_sparse=True, return_colbert=False)
print('返回 keys:', list(out.keys()))
print('dense shape:', out['dense_vecs'].shape if out.get('dense_vecs') is not None else None)
print('lexical_weights 类型:', type(out.get('lexical_weights')))
if out.get('lexical_weights'):
    print('sparse 数量:', len(out['lexical_weights']))
    print('第1个 sparse keys(前5):', list(out['lexical_weights'][0].keys())[:5])
" 2>&1 | tail -15
