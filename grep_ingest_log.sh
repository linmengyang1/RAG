#!/bin/bash
# grep ingest 日志关键行
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 关键日志行（加载/向量化/完成/失败/处理）==="
docker exec "$CONTAINER" bash -c 'grep -nE "加载|向量化|完成|失败|处理|embed|Embedding|model|ERROR|WARNING" /tmp/ingest.log | head -40'

echo ""
echo "=== document_id=1 的完整处理流程 ==="
docker exec "$CONTAINER" bash -c 'grep -n "document_id\|doc_id\|WHERE documents.id = .1\|VALUES (.1," /tmp/ingest.log | head -20'

echo ""
echo "=== 日志总行数 + 时间范围 ==="
docker exec "$CONTAINER" bash -c 'wc -l /tmp/ingest.log; head -1 /tmp/ingest.log; tail -1 /tmp/ingest.log'
