#!/bin/bash
# PostgreSQL 状态检查（用户名 grad / 库 grad_rag）
set +e

echo "========== 表清单 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "\dt"

echo ""
echo "========== documents 状态分布 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;"

echo ""
echo "========== chunks 统计 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT COUNT(*) AS total_chunks, COUNT(milvus_id) AS with_milvus FROM chunks;"

echo ""
echo "========== 失败的 documents（前 5 条）=========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT id, file_path, status, left(error_msg,80) as err FROM documents WHERE status='failed' LIMIT 5;"
