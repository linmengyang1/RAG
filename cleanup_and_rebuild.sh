#!/bin/bash
# 清理 Milvus 脏数据 + PG 残留，准备重跑 ingest
# - Milvus：用 init_milvus.py --force 重建 chunks + wiki 集合
# - PG：清空 chunks + documents 表
set -e
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend
PG=grad-rag-postgres

echo "========== 1. 重建 Milvus chunks + wiki 集合（drop + recreate）=========="
docker exec "$CONTAINER" bash -c 'cd /app/infra/scripts && python init_milvus.py --force'

echo ""
echo "========== 2. 清空 PG chunks + documents =========="
# 先删 chunks（有 FK 指向 documents），再删 documents
docker exec "$PG" psql -U grad -d grad_rag -c "DELETE FROM chunks;"
docker exec "$PG" psql -U grad -d grad_rag -c "DELETE FROM documents;"

echo ""
echo "========== 3. 验证清理结果 =========="
docker exec "$PG" psql -U grad -d grad_rag -c "SELECT 'documents=' || COUNT(*) FROM documents; SELECT 'chunks=' || COUNT(*) FROM chunks;"
docker exec "$CONTAINER" python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://grad-rag-milvus:19530')
print('chunks:', c.get_collection_stats('chunks'))
print('wiki:', c.get_collection_stats('wiki'))
print('collections:', c.list_collections())
"

echo ""
echo "[OK] 清理完成，可重跑 ingest"
