#!/bin/bash
# 查询 failed documents 的错误原因
set +e
echo "========== failed documents 错误原因（去重）=========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT COUNT(*) AS failed_count FROM documents WHERE status='failed';"

echo ""
echo "========== 错误类型分布（截取前 120 字符）=========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT left(error_msg,120) AS err_prefix, COUNT(*) FROM documents WHERE status='failed' GROUP BY err_prefix ORDER BY COUNT(*) DESC;"

echo ""
echo "========== 第一条失败的完整错误 =========="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT id, file_path, error_msg FROM documents WHERE status='failed' ORDER BY id LIMIT 1;"

echo ""
echo "========== ingest.log 中的 ERROR 行 =========="
docker exec grad-rag-backend bash -c "grep -i 'error\|exception\|traceback\|failed\|失败' /tmp/ingest.log 2>/dev/null | tail -30"
