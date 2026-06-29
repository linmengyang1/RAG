#!/bin/bash
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
echo "=== 所有表 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
echo ""
echo "=== chunks 表结构 ==="
docker compose exec postgres psql -U grad -d grad_rag -c "\d chunks" 2>&1 | head -15
echo ""
echo "=== 清理上次失败的 documents 记录 ==="
docker compose exec postgres psql -U grad -d grad_rag -c "DELETE FROM documents WHERE status='failed';" 2>&1
echo ""
echo "=== documents 现有记录数 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT COUNT(*) FROM documents;"
