#!/bin/bash
# 检查 backend 容器内的 huggingface 下载工具
set -u
echo "=== 1. huggingface-cli 是否存在 ==="
which huggingface-cli 2>&1 || echo "NOT FOUND huggingface-cli"
which hf 2>&1 || echo "NOT FOUND hf"

echo
echo "=== 2. huggingface_hub 版本 ==="
python -c "import huggingface_hub; print(huggingface_hub.__version__)" 2>&1

echo
echo "=== 3. HF 环境变量 ==="
env | grep -iE "HF_|HUGGINGFACE" | sort

echo
echo "=== 4. 当前 incomplete 文件大小 ==="
ls -la /data/models/hub/models--BAAI--bge-reranker-v2-m3/blobs/ 2>&1 | grep -E "incomplete|^total"

echo
echo "=== 5. 网络可达 huggingface.co / hf-mirror.com ==="
curl -sS -o /dev/null -w "huggingface.co: %{http_code} (%{time_total}s)\n" --connect-timeout 5 https://huggingface.co 2>&1
curl -sS -o /dev/null -w "hf-mirror.com: %{http_code} (%{time_total}s)\n" --connect-timeout 5 https://hf-mirror.com 2>&1
