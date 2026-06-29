#!/bin/bash
# 检查 reranker 相关库版本
set -u
echo "=== 关键库版本 ==="
docker exec grad-rag-backend python -c "
import transformers, FlagEmbedding, torch
print(f'  transformers:    {transformers.__version__}')
print(f'  FlagEmbedding:   {FlagEmbedding.__version__}')
print(f'  torch:           {torch.__version__}')
print(f'  cuda available:  {torch.cuda.is_available()}')
print(f'  cuda device:     {torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}')
"

echo
echo "=== XLMRobertaTokenizer 是否有 prepare_for_model ==="
docker exec grad-rag-backend python -c "
from transformers import XLMRobertaTokenizer
t = XLMRobertaTokenizer.from_pretrained('BAAI/bge-reranker-v2-m3')
print(f'  XLMRobertaTokenizer 类型: {type(t).__name__}')
print(f'  有 prepare_for_model: {hasattr(t, \"prepare_for_model\")}')
print(f'  有 encode_pair: {hasattr(t, \"encode_pair\")}')
methods = [m for m in dir(t) if 'pair' in m.lower() or 'prepare' in m.lower() or 'encode' in m.lower()]
print(f'  相关方法: {methods}')
"

echo
echo "=== FlagReranker compute_score 源码定位 ==="
docker exec grad-rag-backend python -c "
from FlagEmbedding import FlagReranker
import inspect
src_file = inspect.getsourcefile(FlagReranker)
print(f'  FlagReranker 源码: {src_file}')
# 看 compute_score 方法的关键行
src = inspect.getsource(FlagReranker.compute_score)
for i, line in enumerate(src.split('\n')):
    if 'prepare_for_model' in line or 'encode_pair' in line or 'tokenizer' in line or 'truncate' in line:
        print(f'  L{i}: {line}')
" 2>&1 | head -30
