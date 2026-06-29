#!/bin/bash
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
echo "=== 所有表 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
echo ""
echo "=== chunks 表结构 ==="
docker compose exec postgres psql -U grad -d grad_rag -c "\d chunks" 2>&1 | head -20
