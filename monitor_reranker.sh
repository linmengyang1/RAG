#!/bin/bash
# 监控 reranker 模型下载进度
# 用法：bash monitor_reranker.sh [间隔秒数] [次数]
#   默认：每 10 秒一次，共 6 次（1 分钟）
INTERVAL="${1:-10}"
COUNT="${2:-6}"

CACHE_DIR="/models/hub/models--BAAI--bge-reranker-v2-m3/blobs"
FLAG_FILE="/models/hub/.download_complete_BAAI_bge-reranker-v2-m3"

echo "=========================================="
echo "reranker 下载进度监控"
echo "  间隔: ${INTERVAL}s, 共 ${COUNT} 次"
echo "  开始: $(date '+%H:%M:%S')"
echo "=========================================="

for i in $(seq 1 "$COUNT"); do
    echo
    echo "----- [$i/$COUNT] $(date '+%H:%M:%S') -----"

    # 检查完成标志
    if docker exec grad-rag-backend test -f "$FLAG_FILE" 2>/dev/null; then
        echo "[DONE] 检测到完成标志，下载已完成！"
        docker exec grad-rag-backend bash -c "tail -15 /tmp/download_reranker.log | tr '\r' '\n' | tail -15"
        exit 0
    fi

    # 当前 incomplete 文件大小
    echo "[incomplete 文件]"
    docker exec grad-rag-backend bash -c "ls -la $CACHE_DIR/*.incomplete 2>/dev/null | awk '{printf \"  %s  %s bytes  %s\n\", \$9, \$5, \$6\" \"\$7\" \"\$8}'"

    # 已完成的文件
    echo "[已完成文件]"
    docker exec grad-rag-backend bash -c "ls -la $CACHE_DIR/ 2>/dev/null | grep -v incomplete | grep -v '^total' | grep -v '^d' | awk '{printf \"  %s  %s bytes\n\", \$9, \$5}' | head -10"

    # 最新日志（进度条，\r 转 \n）
    echo "[最新进度]"
    docker exec grad-rag-backend bash -c "tail -5 /tmp/download_reranker.log 2>/dev/null | tr '\r' '\n' | grep -v '^$' | tail -5"

    # 进程是否还在
    echo "[进程状态]"
    docker exec grad-rag-backend bash -c "ps aux | grep -E 'hf download|huggingface' | grep -v grep | head -3"

    if [ "$i" -lt "$COUNT" ]; then
        sleep "$INTERVAL"
    fi
done

echo
echo "=========================================="
echo "监控结束: $(date '+%H:%M:%S')"
echo "  如需继续监控: bash monitor_reranker.sh 10 6"
echo "  手动查看日志: docker exec grad-rag-backend tail -f /tmp/download_reranker.log"
echo "=========================================="
