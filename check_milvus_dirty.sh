#!/bin/bash
# 检查 backend healthy + Milvus 脏数据量
set +e
echo "========== 1. backend 健康状态 =========="
docker ps --filter name=grad-rag-backend --format '{{.Names}} {{.Status}}'

echo ""
echo "========== 2. Milvus chunks 集合脏数据量 =========="
docker exec grad-rag-backend python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://grad-rag-milvus:19530')
print('chunks row_count:', c.get_collection_stats('chunks'))
print('wiki row_count:', c.get_collection_stats('wiki'))
# 查询前 3 条看看 doc_id
try:
    res = c.query(collection_name='chunks', filter='doc_id >= 0', output_fields=['doc_id','category'], limit=3)
    print('chunks 样本:', res)
except Exception as e:
    print('query err:', e)
" 2>&1

echo ""
echo "========== 3. PG 残留状态 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status; SELECT COUNT(*) AS chunks FROM chunks;"
