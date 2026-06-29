#!/bin/bash
# 检查摄入进度
echo "=== 文档状态 ==="
docker exec grad-rag-postgres psql -U grad -d grad_rag -t -c "SELECT status||': '||COUNT(*) FROM documents GROUP BY status;"
echo ""
echo "=== chunks 数量 ==="
docker exec grad-rag-postgres psql -U grad -d grad_rag -t -c "SELECT COUNT(*) FROM chunks;"
echo ""
echo "=== chunks 元数据样本（前 5 条）==="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT id, page_num, char_start, char_end FROM chunks ORDER BY id LIMIT 5;"
echo ""
echo "=== 日志末尾 ==="
docker exec grad-rag-backend tail -8 /tmp/ingest.log 2>/dev/null
echo ""
echo "=== 失败的文档 ==="
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "SELECT id, file_path, status, LEFT(error_msg, 100) FROM documents WHERE status='failed' LIMIT 5;"
