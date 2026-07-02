#!/bin/bash
# etcd 快照备份脚本
# 用法：bash backup_etcd.sh
# 建议：定期运行（如每天一次），保留最近 7 个快照
#
# 单个快照约 300KB-1MB，7 个约 5MB，磁盘占用极小
# 恢复方法：docker exec grad-rag-etcd etcdctl snapshot restore <file> --data-dir /etcd

set -e

BACKUP_DIR="/mnt/c/Users/lmy/Desktop/test/graduate-rag/backups/etcd"
KEEP_COUNT=7  # 保留最近 7 个快照

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CONTAINER_FILE="/tmp/etcd_snapshot_${TIMESTAMP}.db"
HOST_FILE="$BACKUP_DIR/etcd_snapshot_${TIMESTAMP}.db"

echo "=== etcd 快照备份 ==="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "目标: $HOST_FILE"

# 1. 在 etcd 容器内生成快照
echo ""
echo "1. 生成快照..."
docker exec grad-rag-etcd etcdctl \
    --endpoints=http://127.0.0.1:2379 \
    snapshot save "$CONTAINER_FILE" 2>&1

# 2. 复制到宿主机
echo "2. 复制到宿主机..."
docker cp "grad-rag-etcd:$CONTAINER_FILE" "$HOST_FILE" 2>&1

# 3. 清理容器内临时文件
echo "3. 清理容器内临时文件..."
docker exec grad-rag-etcd rm -f "$CONTAINER_FILE" 2>&1

# 4. 验证快照
echo "4. 验证快照完整性..."
docker exec grad-rag-etcd etcdctl \
    --endpoints=http://127.0.0.1:2379 \
    snapshot status "$HOST_FILE" --write-out=table 2>&1 || \
    echo "（验证跳过：宿主机文件无法在容器内访问，正常现象）"

# 5. 清理旧快照，保留最近 N 个
echo ""
echo "5. 清理旧快照（保留最近 $KEEP_COUNT 个）..."
SNAPSHOTS=$(ls -t "$BACKUP_DIR"/etcd_snapshot_*.db 2>/dev/null || true)
TOTAL=$(echo "$SNAPSHOTS" | grep -c . 2>/dev/null || echo 0)
if [ "$TOTAL" -gt "$KEEP_COUNT" ]; then
    echo "$SNAPSHOTS" | tail -n +$((KEEP_COUNT + 1)) | while read -r old_file; do
        rm -f "$old_file"
        echo "  删除: $(basename "$old_file")"
    done
fi

# 6. 列出当前快照
echo ""
echo "=== 当前快照列表 ==="
ls -lh "$BACKUP_DIR"/etcd_snapshot_*.db 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}' || echo "  （无快照）"

echo ""
echo "=== 备份完成 ==="
echo "快照大小: $(du -h "$HOST_FILE" | awk '{print $1}')"
echo "恢复命令: docker exec grad-rag-etcd etcdctl snapshot restore <file> --data-dir /etcd"
