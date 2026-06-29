# ───────── 构建阶段 ─────────
FROM python:3.11-slim AS builder

# 系统依赖（torch/sentence-transformers 需要）
# 国内网络：先换清华 Debian 源，再 apt 安装
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 单独拷贝依赖文件以利用 Docker 缓存
COPY pyproject.toml ./
# 国内网络：用清华 PyPI 源加速 pip
# 装 .[gpu]：torch + FlagEmbedding + sentence-transformers（BGE-M3 推理依赖）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[gpu]"

# ───────── 运行阶段 ─────────
FROM python:3.11-slim AS runtime

# 国内网络：先换清华 Debian 源
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true \
    && apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# HuggingFace 镜像源（国内加速模型下载）
ENV HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/models

# 从 builder 拷贝已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 拷贝应用代码
COPY . /app/backend/

# 把 infra_scripts 暴露给容器（make init-db 用）
# 通过 volume 挂载 ./infra 到 /app/infra_scripts
ENV PYTHONPATH=/app/backend
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
