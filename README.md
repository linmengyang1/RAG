# Graduate RAG

研究生院知识库 RAG 系统 — 基于 DeepSeek API + MinerU API + Milvus 2.4 + 本地 BGE-M3 Embedding。

## 技术栈

| 层 | 选型 |
|------|------|
| LLM | DeepSeek API（v4-flash 主力 / v4-pro Wiki 生成） |
| PDF 解析 | MinerU API（vlm 模型） |
| 向量库 | Milvus 2.4 Standalone（Dense + Sparse 混合检索） |
| Embedding | BGE-M3（本地，GTX 1660 SUPER 6GB，1024 维 Dense + Sparse） |
| Reranker | bge-reranker-v2-m3（本地，已启用） |
| 元数据 | PostgreSQL 16 |
| Agent | LangGraph（P3 阶段，Wiki 优先 → RAG → 沉淀） |
| 后端 | FastAPI + SQLAlchemy async |
| 前端 | Next.js 14 + Tailwind CSS（已实现） |

## 端口规划（避开 Dify 占用）

| 服务 | 宿主机端口 | 容器内端口 | 说明 |
|------|-----------|-----------|------|
| backend | **18000** | 8000 | FastAPI + Swagger |
| postgres | **15432** | 5432 | PG（避开 Dify 的 5432） |
| minio API | **19000** | 9000 | S3 API |
| minio 控制台 | **19001** | 9001 | Web 控制台 |
| milvus gRPC | 19530 | 19530 | 不冲突，保留 |
| milvus 健康 | 9091 | 9091 | 不冲突，保留 |
| frontend | **3000** | 3000 | Next.js Web UI（检索/问答/Wiki） |

## 快速开始

### 前置条件

1. Windows 11 + WSL2（Ubuntu 24.04）
2. Docker Engine（装在 WSL2 内）
3. NVIDIA 显卡 + nvidia-container-toolkit（GPU 模式，见下方 [GPU 配置说明](#gpu-配置说明)）
4. `../output/` 目录有数据（markdown + files）

### 首次启动

```bash
# 1. 复制环境变量（已预填 DeepSeek / MinerU 真实 key）
cp .env.example .env

# 2. 启动所有服务（首次会构建 backend 镜像，装 torch + FlagEmbedding，约 5-10 分钟）
make up

# 3. 检查所有服务 healthy
make ps

# 4. 初始化 Milvus 集合（PG 表已由 init.sql 自动建）
make init-db

# 5. 验证后端
curl http://localhost:18000/health
# 预期: {"status":"ok","postgres":"ok","milvus":"ok",...}
```

### 访问入口

- **前端 Web UI：http://localhost:3000** （检索/问答/Wiki 三 Tab）
- 后端 API 文档：http://localhost:18000/docs
- 后端健康检查：http://localhost:18000/health
- MinIO 控制台：http://localhost:19001 （minioadmin / minioadmin）
- PostgreSQL（本机调试）：`psql -h localhost -p 15432 -U grad -d grad_rag`

## JWT_SECRET 是什么

**JWT_SECRET** 是用于签发和验证 JWT（JSON Web Token）令牌的密钥，采用 HS256 对称加密算法。

### 工作原理

1. **用户登录**时，服务端用 JWT_SECRET 签名生成一个 token，返回给客户端
2. **客户端请求**时携带 `Authorization: Bearer <token>` 头
3. **服务端验证** token 时，用同一个 JWT_SECRET 验证签名是否有效

### 生成方法

```bash
# 生成 64 字符的随机十六进制串
openssl rand -hex 32
# 输出示例: d446f1720bfba0096777ad042fd80fbe15c2a68eb984a3789f27853d5dd25bc7
```

### 当前状态

`.env` 中已预填一个随机生成的 JWT_SECRET（64 字符），可直接使用。**生产环境务必重新生成**，且不要提交到 git。

### 关闭鉴权（仅本地内网）

如果不想登录就能调接口，在 `.env` 中设置：

```env
AUTH_DISABLED=true
```

关闭后所有接口无需 Authorization 头，`get_current_user` 会返回一个虚拟 admin 用户。

## GPU 配置说明

本机显卡：NVIDIA GeForce GTX 1660 SUPER（6144 MiB 显存），够跑 BGE-M3（约需 2.4GB 显存）。

### 安装 nvidia-container-toolkit（让 Docker 容器能用 GPU）

```bash
# 在 WSL2 Ubuntu 内执行（需要 root）
# 1. 配置 NVIDIA 仓库
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL -o /tmp/nvidia.list https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list
sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' /tmp/nvidia.list \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# 2. 安装
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# 3. 配置 Docker daemon
sudo nvidia-ctk runtime configure --runtime=docker

# 4. 重启 Docker
sudo systemctl restart docker

# 5. 验证（应输出 GPU 信息）
docker run --rm --gpus all ubuntu nvidia-smi
```

### CPU 降级模式

如果 GPU 直通不可用，在 `.env` 中设置：

```env
TORCH_DEVICE=cpu
```

BGE-M3 在 CPU 上跑 24 个 md + 5 个 pdf 向量化约需 3-5 分钟（GPU 约 30 秒）。

## RAG 使用流程

### 1. 数据摄入

```bash
# 摄入 10% 数据（默认：md 24 + pdf 5）
make ingest

# 全量摄入（不限制数量，慎用，MinerU 有配额）
make ingest-all

# 自定义数量
docker compose exec backend python -m app.cli.ingest --limit-md 100 --limit-pdf 20
```

摄入流程：扫描 → 解析（md 直读 / pdf 走 MinerU）→ 切片 → BGE-M3 向量化 → 写入 Milvus + PG。

### 2. 检索

```bash
# 先登录拿 token
TOKEN=$(curl -s -X POST http://localhost:18000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<你的密码>"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 检索
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:18000/api/v1/search?q=导师&top_k=5"

# 带分类过滤
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:18000/api/v1/search?q=导师&top_k=5&category=导师信息"
```

检索方式：Dense（HNSW + COSINE）+ Sparse（BM25）双路，RRF 融合，召回 K=max(top_k×6, 30) 候选集 → bge-reranker-v2-m3 精排（可选 `enable_rerank=true`），可选 wiki 第三路附加（`enable_wiki=true`）。每条结果含检索来源标签（向量/关键词/Wiki）+ 相似度 + 原文页码元数据（page_num/char_start/char_end）。

### 3. 问答

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"导师信息怎么查询？","top_k":5}' \
  http://localhost:18000/api/v1/chat
```

问答流程：意图识别（代词消解 + 意图分类，用 deepseek-v4-flash）→ 改写 query → 检索 top_k 相关 chunk（含 rerank）→ 拼接 context prompt（含历史 4 轮）→ 调 DeepSeek 生成答案 → 持久化多轮对话（Conversation/Message 表）→ 返回答案 + sources + rewritten_query + intent + conversation_id。

支持多轮对话：携带 `conversation_id` 即可继续上一轮，系统自动拉历史 8 条做代词消解（"他/她/它"等指代消解）。返回的 `rewritten_query` 是消解后的查询，`intent` 是意图标签（8 类：导师查询/统计查询/政策咨询/流程办理/招生信息/学位管理/奖学金/其他）。意图识别带 8 个 few-shot 示例和 confidence 阈值（<0.5 回退"其他"）；包含多个子问题时自动拆解为独立子问题分别检索后由 LLM 合并答案；输出长度按问题复杂度自动控制（简单≤200字/中等≤500字/统计不限）。

## 增强功能

### 1. Chunk 切片（500/200 重叠）

- **chunk_size=500**：每个切片约 500 字符（按段落累积，超长硬切）
- **overlap=200**：相邻切片有 200 字符重叠，避免语义断裂
- **位置跟踪**：每个 chunk 记录 `char_start/char_end`（原文字符位置）+ `page_num`（PDF 页码，md 为 None）

### 2. 双路检索 + RRF + Rerank

- **Dense 路**：BGE-M3 1024 维向量，HNSW + COSINE
- **Sparse 路**：BGE-M3 sparse 向量，SPARSE_INVERTED_INDEX + IP（等同 BM25）
- **RRF 融合**：Reciprocal Rank Fusion（k=60），公式 `score(d) = sum(1/(k+rank+1))`
- **召回 K=30**：`search_limit = max(top_k * 6, 30)`，保证 rerank 前候选集 ≥ 30
- **Rerank**：bge-reranker-v2-m3 对候选集精排，输出 sigmoid 归一化分数，截断到 top_k
- **来源标注**：每条结果含 `retrieval_sources`（如 `["dense","sparse"]`），前端用三色标签展示

### 3. 意图识别 + 代词消解（多轮对话）

- **意图识别**：用 deepseek-v4-flash 判断意图（8 类标签）+ 8 个 few-shot 示例 + confidence 阈值（<0.5 回退"其他"）
- **代词消解**：拉历史 8 条消息，消解"他/她/它/这个/那个"等指代
- **query 改写**：输出 `rewritten_query`，用于检索和生成
- **多问题拆解**：子问题独立检索 → LLM 合并答案（`COMBINE_ANSWERS_PROMPT`）
- **输出长度控制**：简单问题≤200字 / 中等≤500字 / 统计不限（`_get_length_hint`）
- **持久化**：Conversation/Message 表，Message.trace JSONB 存 `{retrieved, wiki_used, intent, rewritten_query}`

### 4. LLM Wiki

- **Wiki 生成**：从 Milvus chunks 查全文 → 每 10 个 chunk 一批调 deepseek-v4-pro → 提取 person/policy/process 三类候选 → 去重 → 写 PG WikiEntry + Milvus wiki 集合
- **Wiki 检索**：在 wiki 集合做 dense 检索，结果独立附加在 chunks 结果末尾（不参与 RRF 融合）
- **Wiki API**：`POST /api/v1/wiki/generate`（admin）、`GET /api/v1/wiki`（列表）、`GET /api/v1/wiki/search?q=`（检索）、`GET /api/v1/wiki/{id}`（详情）

### 5. 可视化 UI

- **技术栈**：Next.js 14 + React 18 + TypeScript + Tailwind CSS
- **3 个 Tab**：
  - **检索 Tab**：query/top_k/category/rerank/wiki 开关，结果卡片显示检索方式标签 + 相似度进度条 + 原文位置
  - **问答 Tab**：多轮对话，显示 rewritten_query + intent + 答案 + sources
  - **Wiki Tab**：列表/检索 + 独立详情页（`/wiki/[id]`，支持 markdown 渲染 + 相关元数据）
- **元数据展示**：每条结果卡片含：
  - 检索方式标签（向量检索=蓝 / 关键词检索=绿 / Wiki 沉淀=紫）
  - 相似度（rerank 分数优先，否则 RRF 分数）+ 进度条
  - 原文位置（doc_id + 页码 + 字符范围）
  - rerank 分数（如启用）
  - 分类/学院/学科

### 6. SSE 流式问答（POST /api/v1/chat/stream）

- **分阶段推送**：intent_done → retrieving → retrieving_stage（4 个子阶段）→ retrieved → generating → token（多次）→ done
- **检索子阶段拆分**：retrieving_stage 事件推送 4 个子阶段进度：
  - `embedding`：BGE-M3 向量化查询（~1.2s）
  - `dense`：向量检索（HNSW + COSINE，~0.4s）
  - `sparse`：关键词检索（BM25，~0.0s）
  - `reranking`：rerank 精排（bge-reranker-v2-m3，~36s，硬件瓶颈）
- **耗时显示**：每个 SSE 事件带 `elapsed_ms`（从请求开始累计），前端实时显示 + 完成后折叠卡片展示各阶段细分耗时
- **关键技术**：hybrid_search 在 `asyncio.to_thread` 子线程运行，用 `asyncio.run_coroutine_threadsafe` 跨线程投递进度到主事件循环；Next.js 必须设置 `compress: false` 禁用 gzip（否则浏览器 reader.read() 解压阻塞，流式失效）

## 前端使用

### 启动

```bash
# 方式一：docker compose（推荐）
make frontend-up          # 首次会构建镜像 + npm install
make frontend-logs        # 查看启动日志

# 方式二：本机直接运行（开发调试）
cd frontend && npm install && npm run dev
```

访问 http://localhost:3000

### API 代理

前端通过 `next.config.js` 的 rewrites 把 `/api/*` 转发到 backend:8000（容器内网络），无需处理 CORS。浏览器访问 `http://localhost:3000`，API 请求实际走 `backend:8000`。

### 鉴权说明

当前 `.env` 中 `AUTH_DISABLED=true`（测试期间免登录）。生产部署前改为 `false`，前端需在请求头加 `Authorization: Bearer <token>`。

## 数据摄入状态

全量数据已摄入完成。

| 表 | 数量 | 说明 |
|----|------|------|
| documents | **810** | 全量摄入完成，全部 status=embedded |
| chunks | **5699** | 全量向量化完成，已入 Milvus |
| wiki_entries | **1072** | 全量生成完成，person/policy/process 三类 |
| mentors | **793** | 从 wiki person 反推构建，chunks.mentor_id 关联率 98.1% |
| conversations | 3 | 会话历史（测试数据） |
| messages | 84 | 对话消息 |

### documents 分类分布

| 分类 | 文档数 | 占比 |
|------|--------|------|
| 导师信息 | 380 | 46.9% |
| 培养工作 | 209 | 25.8% |
| 招生工作 | 119 | 14.7% |
| 研工工作 | 95 | 11.7% |
| 学位工作 | 0 | 0% |
| 其他 | 17 | 2.1% |

### 重新摄入

```bash
# 全量重跑（跳过已摄入，幂等）
docker compose exec backend python -m app.cli.ingest

# 强制清空重跑
make init-milvus-force
docker compose exec postgres psql -U grad -d grad_rag -c "DELETE FROM chunks; DELETE FROM documents;"
make ingest-all
```

## 目录结构

```
graduate-rag/
├── docker-compose.yml      # Milvus/PG/MinIO/Backend 编排
├── .env                    # 环境变量（含 JWT_SECRET / API key）
├── .env.example            # 模板
├── Makefile
├── README.md
├── models/                 # BGE-M3 模型缓存（bind mount，首次下载后持久化）
├── backend/                # FastAPI 后端
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── app/
│       ├── core/           # 配置 / 鉴权 / 日志
│       ├── models/         # ORM 模型（Document / Chunk / User / Mentor）
│       ├── api/v1/         # REST 接口（auth / search / chat / wiki / conversations）
│       ├── services/
│       │   ├── ingestion/  # scanner / markdown_parser / chunker / embedder / milvus_writer / pipeline / mineru_client
│       │   ├── retrieval/  # hybrid_search（dense + sparse RRF 融合 + rerank）
│       │   ├── llm/        # DeepSeek API + 意图识别 + prompt 构建（含长度控制）
│       │   ├── wiki/       # 知识沉淀（生成 + 检索）
│       │   ├── mentor/     # 导师实体构建（从 wiki 反推 + chunks 关联）
│       │   └── agent/      # LangGraph（P3）
│       └── cli/            # CLI 入口（ingest.py）
└── infra/
    └── scripts/
        ├── init_milvus.py
        └── init_postgres.sql
```

## 数据集

数据位于 `../output/`（与项目并列），通过 docker-compose 只读挂载到容器 `/data/output`：

- `markdown/` — 已抓取的网页正文（导师信息 380 / 培养工作 209 / 招生工作 119 / 研工工作 95）
- `files/` — 附件 PDF/DOCX（与 markdown 互补，独立摄入）
- 全量 810 文档已经过 MinerU 解析 → BGE-M3 向量化 → 写入 Milvus + PG

## 实施阶段

- [x] **P0** 基础设施：docker-compose + Milvus + PG + 占位 client + DeepSeek/MinerU 接入
- [x] **P1** 数据接入管线：scanner + markdown_parser + chunker + embedder + milvus_writer + pipeline
- [x] **P2** 检索层：Milvus hybrid search（dense + sparse RRF 融合）+ search/chat API
- [x] **P3** LLM 增强：意图识别 + 代词消解 + 多轮对话 + SSE 流式问答
- [x] **P4** Wiki 沉淀：Wiki 生成（v4-pro）+ Wiki 检索 + Wiki 管理 API
- [x] **P5** Next.js 前端：3 Tab（检索/问答/Wiki）+ 元数据展示 + 流式思考过程 + 耗时卡片
- [x] **P6** 全量摄入：810 文档 / 5699 chunks，全部 embedded
- [ ] **P7** 加固（RAGAS 评测 + Reranker 优化 + 鉴权 UI + 监控）
  - [x] Mentors 实体补全（793 导师，98.1% chunks 关联）
  - [x] 会话管理 UI（CRUD + 侧边栏）
  - [x] 意图 few-shot + confidence + 多问题拆解 + 长度控制

> 项目完善计划详见 [.trae/documents/project-completion-plan.md](../.trae/documents/project-completion-plan.md)。当前数据摄入 810/810（全量完成）。

## API 接口一览

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/health` | 健康检查 | 否 |
| GET | `/docs` | Swagger 文档 | 否 |
| POST | `/api/v1/auth/register` | 注册管理员 | 否 |
| POST | `/api/v1/auth/login` | 登录获取 token | 否 |
| GET | `/api/v1/search?q=xxx` | 混合检索（含 rerank/wiki 开关） | 是 |
| POST | `/api/v1/chat` | RAG 问答（多轮对话 + 意图识别） | 是 |
| POST | `/api/v1/chat/stream` | RAG 流式问答（SSE 分阶段推送 + 检索子阶段拆分） | 是 |
| POST | `/api/v1/wiki/generate` | 触发 Wiki 生成 | 是(admin) |
| GET | `/api/v1/wiki` | Wiki 列表（分页 + 类型过滤） | 是 |
| GET | `/api/v1/wiki/search?q=` | Wiki 检索 | 是 |
| GET | `/api/v1/wiki/{id}` | Wiki 详情 | 是 |
| GET | `/api/v1/conversations` | 会话列表（分页） | 是 |
| GET | `/api/v1/conversations/{id}` | 会话详情（含历史消息） | 是 |
| PATCH | `/api/v1/conversations/{id}` | 重命名会话 | 是 |
| DELETE | `/api/v1/conversations/{id}` | 删除会话（CASCADE messages） | 是 |

## 测试

```bash
# 走 docker
make backend-test

# 本机直接跑（需先 pip install -e ".[dev]"）
make test-local
```

## 常见问题

### Q: `docker compose ps` 显示 backend 是 `unhealthy`？
A: 检查日志 `docker compose logs backend`，常见原因：GPU 直通未配置（容器内 torch 检测不到 CUDA）、Milvus 未就绪、PG 未就绪。

### Q: 摄入时报 `FlagEmbedding` 导入失败？
A: 镜像没装 `.[gpu]` 依赖。重新 `make build` 构建 backend 镜像。

### Q: BGE-M3 模型下载很慢？
A: 已配置 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）。首次下载约 2.4GB，之后缓存在 `./models/` 目录，重启容器不用重下。

### Q: MinerU 解析 PDF 失败？
A: 检查 `.env` 的 `MINERU_API_TOKEN` 是否有效。可在 `.env` 中设置 `MINERU_USE_MOCK=true` 走 mock（返回占位文本），先测通 md 链路。
