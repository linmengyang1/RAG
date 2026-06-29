#!/bin/bash
set -u
echo "=== FlagEmbedding 当前版本 ==="
docker exec grad-rag-backend pip show FlagEmbedding 2>&1 | grep -E "^(Name|Version|Location)"

echo
echo "=== FlagEmbedding 可用版本（前 15 个）==="
docker exec grad-rag-backend pip index versions FlagEmbedding 2>&1 | head -5

echo
echo "=== FlagReranker compute_score 关键代码 ==="
docker exec grad-rag-backend python -c "
from FlagEmbedding import FlagReranker
import inspect
src = inspect.getsource(FlagReranker.compute_score)
print(src[:2000])
" 2>&1 | head -60

echo
echo "=== transformers 是否可降级到 4.x ==="
docker exec grad-rag-backend pip index versions transformers 2>&1 | head -3
