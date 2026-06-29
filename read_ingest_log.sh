#!/bin/bash
# 读取 ingest 日志的关键错误信息
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag
CONTAINER=grad-rag-backend

echo "=== 日志总行数 ==="
docker exec "$CONTAINER" wc -l /tmp/ingest.log

echo ""
echo "=== 前 60 行（看第一个失败）==="
docker exec "$CONTAINER" head -60 /tmp/ingest.log

echo ""
echo "=== 错误关键词统计 ==="
docker exec "$CONTAINER" bash -c 'grep -c "ERROR\|Error\|Exception\|Traceback" /tmp/ingest.log'

echo ""
echo "=== 第一个 Traceback 上下文 ==="
docker exec "$CONTAINER" bash -c 'grep -n "Traceback" /tmp/ingest.log | head -1'
