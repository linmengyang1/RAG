#!/bin/bash
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
echo "=== 重新执行 init_postgres.sql（完整输出）==="
docker compose exec postgres psql -U grad -d grad_rag -f /docker-entrypoint-initdb.d/init.sql 2>&1
echo ""
echo "=== 执行后所有表 ==="
docker compose exec postgres psql -U grad -d grad_rag -t -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
