#!/bin/bash
# 诊断 pip 死因 + 容器资源
cd /mnt/c/Users/lmy/Desktop/test/graduate-rag

echo "=== 容器内存限制 ==="
docker compose exec backend bash -c 'cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo unknown'

echo ""
echo "=== 容器内存使用 ==="
docker compose exec backend bash -c 'free -m 2>/dev/null || cat /proc/meminfo | head -3'

echo ""
echo "=== dmesg OOM kill 记录（宿主机）==="
dmesg 2>/dev/null | grep -i "killed process\|out of memory" | tail -5 || echo "(无法读 dmesg)"

echo ""
echo "=== pip_install.log 完整大小 ==="
docker compose exec backend bash -c 'wc -c /tmp/pip_install.log 2>/dev/null; stat -c "modified: %y" /tmp/pip_install.log 2>/dev/null'

echo ""
echo "=== 容器最近的日志 ==="
docker compose logs backend --tail 15 2>&1 | tail -15
