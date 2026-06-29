#!/bin/bash
# 下载 reranker 模型 BAAI/bge-reranker-v2-m3
# - 使用 HF_ENDPOINT=https://hf-mirror.com（已通过环境变量配置）
# - 自动续传（huggingface_hub 检测 .incomplete 文件自动 resume）
# - 输出实时进度到 stdout/stderr（huggingface_hub 1.21 原生进度条）
# - 完成后写标志文件，便于外部检测
set -u

MODEL_ID="BAAI/bge-reranker-v2-m3"
CACHE_DIR="${HF_HOME:-/models}/hub"
FLAG_FILE="${CACHE_DIR}/.download_complete_${MODEL_ID//\//_}"

echo "============================================"
echo "reranker 模型下载"
echo "============================================"
echo "  模型:      $MODEL_ID"
echo "  缓存目录:  $CACHE_DIR"
echo "  HF镜像:    $HF_ENDPOINT"
echo "  开始时间:  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo

# 检查是否已完成
if [ -f "$FLAG_FILE" ]; then
    echo "[SKIP] 已存在完成标志: $FLAG_FILE"
    echo "  如需重新下载，请先删除该标志文件"
    exit 0
fi

# 启动下载（hf download 自动检测 .incomplete 文件 resume）
# hf 是 huggingface-cli 的新版本（1.21+ 起 huggingface-cli 已弃用）
# hf download 会下载所有文件（model.safetensors + config.json + tokenizer 等）
hf download "$MODEL_ID" 2>&1

DOWNLOAD_EXIT=$?
echo
echo "============================================"
echo "下载命令退出码: $DOWNLOAD_EXIT"
echo "结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

if [ $DOWNLOAD_EXIT -eq 0 ]; then
    # 验证 safetensors 文件存在
    SAFETENSORS=$(find "$CACHE_DIR/models--$MODEL_ID" -name "*.safetensors" -not -name "*.incomplete" 2>/dev/null | head -1)
    if [ -n "$SAFETENSORS" ]; then
        SIZE=$(du -h "$SAFETENSORS" | cut -f1)
        echo "[OK] 下载完成，safetensors 文件: $SAFETENSORS ($SIZE)"
        touch "$FLAG_FILE"
        echo "[OK] 完成标志已写入: $FLAG_FILE"
    else
        echo "[WARN] 退出码 0 但未找到 safetensors 文件，请检查"
    fi
else
    echo "[ERROR] 下载失败，退出码 $DOWNLOAD_EXIT"
    echo "  可重新运行本脚本续传"
fi

exit $DOWNLOAD_EXIT
