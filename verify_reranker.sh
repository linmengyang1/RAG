#!/bin/bash
# 验证 reranker 模型下载完整性 + 清理旧 incomplete 文件
# 所有操作通过 docker exec 在 backend 容器内执行
set -u

CONTAINER="grad-rag-backend"
BLOBS_DIR="/models/hub/models--BAAI--bge-reranker-v2-m3/blobs"

echo "=== 1. snapshot 目录 ==="
SNAPSHOT_DIR=$(docker exec "$CONTAINER" bash -c "ls -d /models/hub/models--BAAI--bge-reranker-v2-m3/snapshots/*/ 2>/dev/null | head -1")
echo "  $SNAPSHOT_DIR"

echo
echo "=== 2. snapshot 内文件（软链接）==="
docker exec "$CONTAINER" bash -c "ls -la ${SNAPSHOT_DIR} 2>/dev/null | grep -v '^total' | grep -v '^d'"

echo
echo "=== 3. model.safetensors 实际文件大小 ==="
docker exec "$CONTAINER" bash -c "
SAFE_REAL=\$(readlink -f '${SNAPSHOT_DIR}model.safetensors' 2>/dev/null)
if [ -n \"\$SAFE_REAL\" ]; then
    SIZE_BYTES=\$(stat -c %s \"\$SAFE_REAL\")
    SIZE_HUMAN=\$(du -h \"\$SAFE_REAL\" | cut -f1)
    echo \"  软链接: ${SNAPSHOT_DIR}model.safetensors\"
    echo \"  实际:   \$SAFE_REAL\"
    echo \"  大小:   \$SIZE_BYTES bytes (\$SIZE_HUMAN)\"
    if [ \"\$SIZE_BYTES\" -gt 1000000000 ]; then
        echo '  状态:   [OK] 大于 1GB，符合预期'
    else
        echo '  状态:   [WARN] 小于 1GB，可能不完整'
    fi
fi
"

echo
echo "=== 4. 残留的 .incomplete 文件 ==="
INCOMPLETE_COUNT=$(docker exec "$CONTAINER" bash -c "ls $BLOBS_DIR/*.incomplete 2>/dev/null | wc -l")
if [ "$INCOMPLETE_COUNT" -gt 0 ]; then
    echo "  发现 $INCOMPLETE_COUNT 个 .incomplete 文件："
    docker exec "$CONTAINER" bash -c "ls -lah $BLOBS_DIR/*.incomplete 2>/dev/null | awk '{printf \"    %s  %s\n\", \$5, \$9}'"
    echo
    echo "  清理中..."
    docker exec "$CONTAINER" bash -c "rm -f $BLOBS_DIR/*.incomplete"
    echo "  [OK] 已清理"
else
    echo "  无 .incomplete 文件（已清理或已合并）"
fi

echo
echo "=== 5. 写入完成标志 ==="
docker exec "$CONTAINER" bash -c "touch /models/hub/.download_complete_BAAI_bge-reranker-v2-m3 && echo '  [OK] 标志已写入'"

echo
echo "=== 6. blobs 目录总文件清单 ==="
docker exec "$CONTAINER" bash -c "ls -lah $BLOBS_DIR | grep -v '^total' | grep -v '^d' | awk '{printf \"    %s  %s\n\", \$5, \$9}'"

echo
echo "============================================"
echo "reranker 模型下载验证完成"
echo "============================================"
