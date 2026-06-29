#!/bin/bash
# 验证 Milvus 实际数据量 + backend API 健康
set +e
echo "========== 1. Milvus 实际数据（query，不依赖 stats）=========="
docker exec grad-rag-backend python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://grad-rag-milvus:19530')
# 查询总数（query 不受 stats 延迟影响）
res = c.query(collection_name='chunks', filter='doc_id >= 0', output_fields=['doc_id','category','college'], limit=10)
print('chunks 前 10 条:')
for r in res:
    print(' ', r)
# 用 query 的方式估算总量（查 limit 1000 看返回多少）
res_all = c.query(collection_name='chunks', filter='doc_id >= 0', output_fields=['doc_id'], limit=1000)
print(f'chunks 实际总数: {len(res_all)}')
# 按 category 分布
from collections import Counter
cats = Counter(r.get('category','') for r in res_all)
print('category 分布:', dict(cats))
" 2>&1

echo ""
echo "========== 2. backend API 健康 =========="
docker exec grad-rag-backend bash -c 'curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/health 2>/dev/null || echo "(无 /health 端点)"'
docker exec grad-rag-backend bash -c 'curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/docs 2>/dev/null || echo "(无 /docs)"'
docker exec grad-rag-backend bash -c 'curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/api/v1/search?q=test 2>/dev/null || echo "(search 不可达)"'

echo ""
echo "========== 3. PG 已 embedded 的文件示例 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT id, file_type, category, college, status FROM documents ORDER BY id LIMIT 10;"
