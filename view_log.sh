#!/bin/bash
# 查看下载日志
echo "=== 完整日志（\\r 转 \\n，去空行）==="
docker exec grad-rag-backend bash -c "cat /tmp/download_reranker.log" | tr '\r' '\n' | grep -v '^$'

echo
echo "=== refs/main 内容（指向哪个 snapshot）==="
docker exec grad-rag-backend bash -c "cat /models/hub/models--BAAI--bge-reranker-v2-m3/refs/main 2>&1"

echo
echo "=== snapshots 目录 ==="
docker exec grad-rag-backend bash -c "ls -la /models/hub/models--BAAI--bge-reranker-v2-m3/snapshots/ 2>&1"

echo
echo "=== snapshot 内容（软链接到 blobs）==="
docker exec grad-rag-backend bash -c "ls -la /models/hub/models--BAAI--bge-reranker-v2-m3/snapshots/*/ 2>&1"
