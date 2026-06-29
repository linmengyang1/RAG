#!/bin/bash
# 检查 RAG 系统当前状态：容器 / GPU依赖 / PG表 / Milvus集合
set +e

echo "========== 1. 容器状态 =========="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

echo ""
echo "========== 2. backend 容器内 GPU 依赖 =========="
docker exec grad-rag-backend python -c "
import torch, FlagEmbedding, transformers, numpy
print('torch       =', torch.__version__)
print('cuda avail  =', torch.cuda.is_available())
print('cuda device =', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')
print('FlagEmbed   =', FlagEmbedding.__version__)
print('transformers=', transformers.__version__)
print('numpy       =', numpy.__version__)
" 2>&1

echo ""
echo "========== 3. PostgreSQL documents 表状态 =========="
docker exec grad-rag-postgres psql -U rag -d rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;" 2>&1
docker exec grad-rag-postgres psql -U rag -d rag -c "SELECT COUNT(*) AS total_chunks, COUNT(milvus_id) AS with_milvus FROM chunks;" 2>&1

echo ""
echo "========== 4. Milvus chunks 集合行数 =========="
docker exec grad-rag-backend python -c "
from pymilvus import MilvusClient
c = MilvusClient(uri='http://grad-rag-milvus:19530')
try:
    s = c.get_collection_stats('chunks')
    print('chunks stats:', s)
except Exception as e:
    print('chunks err:', e)
try:
    s = c.get_collection_stats('wiki')
    print('wiki stats:', s)
except Exception as e:
    print('wiki err:', e)
" 2>&1

echo ""
echo "========== 5. BGE-M3 模型缓存 =========="
docker exec grad-rag-backend bash -c "ls -la /models/hub/models--BAAI--bge-m3/snapshots/*/ 2>&1 | head -20"
docker exec grad-rag-backend bash -c "ls /models/hub/models--BAAI--bge-m3/snapshots/*/imgs/.DS_Store 2>&1"

echo ""
echo "========== 6. ingest 进程是否在跑 =========="
docker exec grad-rag-backend bash -c "for p in /proc/[0-9]*/comm; do v=\$(cat \$p 2>/dev/null); if [ \"\$v\" = 'python' ] || [ \"\$v\" = 'pip' ]; then echo \$p: \$v; fi; done" 2>&1
