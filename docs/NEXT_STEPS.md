# 本机 Trae IDE 接手指南

> 本文档面向本机的 Trae IDE（Windows + WSL2 + Docker 环境）。
> 远程环境已把 P0 全部代码写好并通过 17/17 单元测试，本机只需验证容器编排，然后接手 P1。

---

## 一、当前状态

### 已完成（P0）
- ✅ docker-compose.yml（Milvus standalone + etcd + minio + postgres + backend）
- ✅ 后端 FastAPI 骨架 + JWT 鉴权（注册/登录/me）+ /health 端点
- ✅ ORM 模型：User / Mentor / MentorIdentity / Document / Chunk / WikiEntry / WikiLink / Conversation / Message
- ✅ PostgreSQL 初始化脚本（含 pg_trgm 扩展、所有索引、updated_at 触发器）
- ✅ Milvus 初始化脚本（chunks 集合 dense+sparse + wiki 集合）
- ✅ **DeepSeek API 真实实现**（OpenAI 兼容，主力 v4-flash / Wiki v4-pro）
- ✅ **MinerU API 真实实现**（本地文件 → 申请上传链接 → PUT → 轮询 batch → 下载 zip）
- ✅ 17/17 单元测试通过

### 待本机验证（P0 收尾）
- ⬜ 在 Windows 本机启动 docker compose
- ⬜ 初始化 Milvus 集合
- ⬜ 后端健康检查通过

---

## 二、本机验证步骤（必做）

### 0. 前置条件
- Windows + WSL2 + Docker Desktop 已装（你说 Dify 能跑就说明 Docker 没问题）
- 项目代码已同步到本机，路径例如 `D:\Trae_file\graduate-rag`（或 WSL 内 `/mnt/d/Trae_file/graduate-rag`）
- 数据 `output/` 在项目同级（`../output/`）

### 1. 进入项目目录

```bash
# WSL 内
cd /mnt/d/Trae_file/graduate-rag
# 或本机 PowerShell
cd D:\Trae_file\graduate-rag
```

### 2. 检查 .env

`.env.example` 已预填 DeepSeek 和 MinerU 真实 key，直接复制即可：

```bash
cp .env.example .env
```

**重要检查项**（必看）：

```bash
# 1) JWT_SECRET 改成随机串（默认值不安全）
# Linux/WSL: 生成随机串
openssl rand -hex 32
# 把输出填到 .env 的 JWT_SECRET=

# 2) 端口已规划好，避开了 Dify：
#    backend 18000 / postgres 15432 / minio 19000-19001 / milvus 19530+9091
#    如果你本机还有其他应用占用这些端口，改 docker-compose.yml 的端口映射
```

### 3. 启动所有服务

```bash
make up
# 或：docker compose --env-file .env up -d
```

首次启动需要：
- 拉取 milvus / postgres / minio / etcd 镜像（约 5-10 分钟，取决于网速）
- 构建 backend 镜像（安装 fastapi/sqlalchemy/pymilvus 等，约 3-5 分钟）

**注意**：backend 镜像构建时如果国内网络慢，可以加镜像源。在 Dockerfile 顶部加：
```dockerfile
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 检查所有服务健康

```bash
make ps
# 期望：所有 5 个容器都是 Up + healthy 状态
# grad-rag-etcd       Up (healthy)
# grad-rag-minio       Up (healthy)
# grad-rag-milvus      Up (healthy)
# grad-rag-postgres    Up (healthy)
# grad-rag-backend     Up (healthy)
```

如果某容器不健康，看日志：
```bash
make logs                # 实时所有日志
docker compose logs -f backend   # 仅 backend
docker compose logs -f milvus     # 仅 milvus
```

### 5. 初始化 Milvus 集合

```bash
make init-db
# 期望输出：
#   [init_milvus] ✓ 创建 chunks 集合: chunks (dim=1024)
#   [init_milvus] ✓ 创建 wiki 集合: wiki (dim=1024)
#   [init_milvus] 当前集合: ['chunks', 'wiki']
```

如果出错，看 backend 日志：`docker compose logs backend`

### 6. 验证后端

```bash
curl http://localhost:18000/health
# 期望返回：
# {
#   "status": "ok",
#   "postgres": "ok",
#   "milvus": "ok",
#   "llm_mock": false,         ← false 表示 DeepSeek 真实接入
#   "mineru_mock": false,      ← false 表示 MinerU 真实接入
#   "auth_disabled": false
# }

# 打开浏览器访问：
#   http://localhost:18000/docs     ← Swagger UI，可调所有 API
#   http://localhost:19001          ← MinIO 控制台（minioadmin/minioadmin）
```

### 7. 跑测试（可选但推荐）

```bash
make backend-test
# 期望：17 passed
```

### 8. 注册第一个管理员账号

```bash
curl -X POST http://localhost:18000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# 第一个用户自动成为 admin
# 返回 token，存起来后续用
```

---

## 三、关键约束和注意事项

### 端口规划（避开 Dify）

| 服务 | 端口 | 说明 |
|------|------|------|
| backend | **18000** | 宿主机访问后端 |
| postgres | 15432 | 本机 psql 调试用 |
| minio API | 19000 | S3 API |
| minio 控制台 | 19001 | Web UI |
| milvus | 19530 | gRPC |
| milvus 健康 | 9091 | HTTP |

### 已知约束

1. **bcrypt 必须 < 4.0**：passlib 1.7.4 与 bcrypt 4.x 不兼容。pyproject.toml 已锁 `"bcrypt>=3.2,<4.0"`，构建时若被覆盖需手动 `pip install 'bcrypt<4.0'`。
2. **DeepSeek API base**：用 `https://api.deepseek.com`（不带 /v1 后缀，SDK 内部处理）。
3. **MinerU 流程**：本地文件必须走 `/file-urls/batch` 上传（接口不支持直接上传文件体）。
4. **MinerU 配额**：每天 2000 页高优先级；你的数据 PDF 总页数估算 < 5000 页，分两天跑完。
5. **GPU**：docker-compose 中 GPU 配置已注释，P1 启用 BGE-M3 时取消 `backend` 服务的 `deploy.resources` 注释。

### DeepSeek API 速查
- 主力：`deepseek-v4-flash`（便宜，$0.14/M 输入）
- Wiki 生成：`deepseek-v4-pro`（旗舰，$0.435/M 输入）
- 旧别名 `deepseek-chat` / `deepseek-reasoner` 将于 **2026/07/24** 弃用，代码已用新名

### MinerU API 速查
- 提交：`POST https://mineru.net/api/v4/file-urls/batch`（本地文件）
- 提交：`POST https://mineru.net/api/v4/extract/task`（公网 URL）
- 轮询：`GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`
- 单文件轮询：`GET https://mineru.net/api/v4/extract/task/{task_id}`
- 模型版本：`vlm`（推荐）/ `pipeline`（默认）/ `MinerU-HTML`

---

## 四、P1：数据接入管线（本机 Trae IDE 接手实现）

### P1 目标
把 `output/` 下 ~800 个文件（436 pdf + 121 docx + 239 md + 杂项）全部解析、切片、向量化、写入 Milvus，元数据写入 PostgreSQL。

### P1 文件清单（按依赖顺序）

所有文件位于 `backend/app/services/ingestion/`，**已存在 `mineru_client.py`**，新增以下：

```
backend/app/services/ingestion/
├── mineru_client.py          ✅ 已完成（DeepSeek 已接入）
├── markdown_parser.py        ⬜ 待实现
├── scanner.py                ⬜ 待实现
├── mentor_matcher.py         ⬜ 待实现
├── chunker.py                ⬜ 待实现
├── embedder.py               ⬜ 待实现（需 GPU）
├── milvus_writer.py          ⬜ 待实现
└── pipeline.py               ⬜ 待实现（总调度）
```

外加：
```
backend/app/cli/
└── ingest.py                 ⬜ 待实现（make ingest 的入口）
```

### 每个文件的职责

#### 1. `scanner.py` — 双路扫描器
- 扫描 `output/markdown/**/*.md` → 列表 A（doc_source=web_md）
- 扫描 `output/files/**/*.{pdf,docx,doc,xlsx,xls}` → 列表 B（doc_source=attachment）
- 对比 `documents` 表，按 `file_path` 去重，输出 `status=pending` 的待处理列表
- 解析路径推断 category/college/subject（导师信息/培养工作/招生工作/研工工作/研究生文件 + 学院 + 学科方向）

#### 2. `markdown_parser.py` — 元数据表解析
- 输入：md 文件路径
- 输出：`ParsedDocument(metadata=dict, content=str)`
- 解析规则：md 开头的「| 属性 | 内容 |」表，提取 `日期/分类/来源/原始URL/附件/爬取时间`
- 跳过 `---` 分隔线，正文从 `## 正文` 开始
- 附件 URL 拆成 `attachment_urls: list[str]`（多个用 `<br>` 分隔）

#### 3. `mentor_matcher.py` — 导师聚合
- 输入：导师信息类 md（含 姓名 + 学院 + 学科方向）
- 按 `name` 查 `mentors` 表，存在则复用；不存在则新建
- 写入 `mentor_identities`（多身份）：college / subject_direction / title / source_doc_id / raw_md_path
- 同名+同年视为同一人（UNIQUE 约束在 SQL 已建好）

#### 4. `chunker.py` — 分类切片策略
- **导师信息**：按 H2 章节切（基本信息/研究方向/科研成果/招生方向），保留导师 ID 关联
- **通知公告（培养/招生/研工）**：按 H2/H3 + 段落切，保留「截止日期/联系人」结构化字段
- 每块加 `doc_id/category/college/subject/source_url/published_at` 元数据
- 切片大小：500-800 字（中文按字符数，不用 tokenizer）

#### 5. `embedder.py` — BGE-M3 向量化
- 加载 `BAAI/bge-m3`（懒加载，首次调用时加载到显存）
- 输入：list[str]
- 输出：`list[(dense: np.ndarray(1024), sparse: dict[int, float])]`
- **批量推理**：每批 32 条，避免显存炸
- 需要 GPU（docker-compose 中取消注释 nvidia 配置）

#### 6. `milvus_writer.py` — 写入 Milvus
- 输入：list[ChunkData(dense, sparse, text, doc_id, category, college, subject, source_url, published_at)]
- 写入 `chunks` collection
- 返回 milvus_id 列表，回写到 PostgreSQL `chunks.milvus_id`

#### 7. `pipeline.py` — 总调度
```
for each pending file in scanner.scan():
    if doc_source == web_md:
        md_text = file.read_text()                # 直接读
    else:
        result = await mineru_client.parse(path)  # 调 MinerU API
        md_text = result.markdown
        save to mineru_cache

    parsed = markdown_parser.parse(md_text, metadata)
    doc = upsert_document(parsed)
    if category == "导师信息":
        mentor_matcher.match(parsed, doc.id)

    chunks = chunker.chunk(parsed, doc.id)
    embeddings = embedder.embed([c.text for c in chunks])
    milvus_ids = milvus_writer.write(chunks, embeddings)
    update_chunks_milvus_id(chunks, milvus_ids)
    mark_document_status(doc.id, "embedded")
```

幂等：以 `file_path` 唯一键，重跑不重复。

### P1 验收标准
- `documents` 表有 ~800 条记录，status=embedded
- `chunks` 表有 1-2 万条记录
- `mentors` 表有 ~50-80 个导师（去重后）
- `mentor_identities` 表有 ~190 条（每个 md 一条身份）
- Milvus chunks 集合有对应数量的向量
- 用 `milvus_client.search(...)` 能查到结果

### P1 实施建议
1. 先写 `markdown_parser.py` + `scanner.py`（不依赖外部服务，纯本地逻辑，最容易测）
2. 再写 `chunker.py` + `mentor_matcher.py`（同样纯本地）
3. 然后 `embedder.py`（需要装 GPU 依赖：`pip install -e ".[gpu]"`）
4. 然后 `milvus_writer.py`
5. 最后 `pipeline.py` 总调度
6. 先用 mock MinerU 跑通 `output/markdown/*.md` 全链路（不耗 MinerU 配额）
7. 真实跑 `output/files/*.pdf` 走 MinerU API（分批，每天 < 2000 页）

---

## 五、给 Trae IDE 的明确指令

把以下文字复制给本机 Trae IDE 作为下一轮 prompt：

```
请接手 graduate-rag 项目的 P1 阶段实现。

当前状态：P0 已完成（远程已写好），所有容器可启动，DeepSeek 和 MinerU API 已接入真实接口。

请阅读 /mnt/big_disk_0/lmy/test/graduate-rag/docs/NEXT_STEPS.md（即本文件）的「四、P1：数据接入管线」部分，
按建议顺序实现 P1 的 7 个文件：
  1. backend/app/services/ingestion/markdown_parser.py
  2. backend/app/services/ingestion/scanner.py
  3. backend/app/services/ingestion/chunker.py
  4. backend/app/services/ingestion/mentor_matcher.py
  5. backend/app/services/ingestion/embedder.py
  6. backend/app/services/ingestion/milvus_writer.py
  7. backend/app/services/ingestion/pipeline.py
  + backend/app/cli/ingest.py（CLI 入口）

实现要求：
- 代码风格与 P0 一致：用 loguru 日志、async def、SQLAlchemy async、pydantic 数据类
- 每个模块带单元测试，放在 backend/tests/test_p1_<module>.py
- markdown_parser / scanner / chunker / mentor_matcher 不依赖外部服务，先实现并测通
- embedder 需要 GPU，先用 mock 实现（CPU 也能跑，慢），后续切到 cuda
- pipeline 必须幂等：以 documents.file_path 唯一键，重跑不重复嵌入

数据约定：
- output/markdown/ 是已抓取的网页正文（含元数据表）
- output/files/ 是附件 PDF/DOCX，与 markdown 互补，独立摄入
- 研究生文件类别只有 files（markdown 为空）

完成后告诉我，我会用 make ingest 触发实际数据导入。
```

---

## 六、遇到问题的常见排查

### Q: `make up` 后 backend 容器一直 unhealthy
```bash
docker compose logs backend
# 常见原因：
# 1) 连不上 postgres → 检查 postgres 容器是否 healthy
# 2) 连不上 milvus → 检查 milvus 容器是否 healthy（首次启动要 60s）
# 3) 端口被占用 → 改 docker-compose.yml 端口映射
```

### Q: `make init-db` 报错 "Milvus 在 60s 内未就绪"
```bash
docker compose logs milvus
# 常见原因：milvus 容器还在启动中（首次要 60-90s），等一会儿重试
# 或：milvus 依赖 etcd/minio 未就绪，检查它们的状态
```

### Q: DeepSeek API 调用失败
```bash
docker compose exec backend python -c "
import asyncio
from app.services.llm.deepseek_client import get_llm_client
async def t():
    c = get_llm_client()
    async for chunk in c.chat_stream([{'role':'user','content':'你好'}]):
        print(chunk, end='')
asyncio.run(t())
"
```
如果报 401，说明 API key 错；如果报 model not found，确认 model 名是 `deepseek-v4-flash` / `deepseek-v4-pro`。

### Q: MinerU 调用失败
```bash
docker compose exec backend python -c "
import asyncio
from app.services.ingestion.mineru_client import get_mineru_client
async def t():
    c = get_mineru_client()
    # 用 output 里随便一个 pdf 测
    r = await c.parse('/data/output/files/导师信息/.../xxx.pdf')
    print('markdown len:', len(r.markdown))
asyncio.run(t())
"
```
MinerU 解析一个 PDF 要 30s-2min，耐心等。

### Q: backend 镜像构建慢
在 backend/Dockerfile 顶部加：
```dockerfile
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 想看 PostgreSQL 里的数据
```bash
docker compose exec postgres psql -U grad -d grad_rag
\dt                          # 列出所有表
SELECT count(*) FROM documents;
SELECT status, count(*) FROM documents GROUP BY status;
\q
```
或本机直接：`psql -h localhost -p 15432 -U grad -d grad_rag`

---

## 七、文件清单（P0 最终交付）

```
graduate-rag/
├── .env.example            # 已预填 DeepSeek + MinerU key
├── docker-compose.yml      # 5 服务编排，端口规划好
├── Makefile                # make up/down/init-db/test/...
├── README.md
├── docs/
│   └── NEXT_STEPS.md       # 本文件
├── infra/scripts/
│   ├── init_milvus.py      # 建 chunks/wiki 集合
│   └── init_postgres.sql   # 8 张表 + 触发器
└── backend/
    ├── Dockerfile
    ├── pyproject.toml      # bcrypt<4.0 已锁
    ├── app/
    │   ├── main.py         # FastAPI 入口
    │   ├── core/{config,security,logging}.py
    │   ├── db/session.py
    │   ├── models/         # 8 个 ORM 模型
    │   ├── schemas/auth.py
    │   ├── api/v1/auth.py  # 注册/登录/me
    │   └── services/
    │       ├── llm/deepseek_client.py     # DeepSeek 真实实现
    │       └── ingestion/mineru_client.py # MinerU 真实实现
    └── tests/test_p0.py    # 17 个测试，全过
```

---

**最后**：本机验证完 P0（make up + make init-db + curl health 返回 ok）后，把本文件「五、给 Trae IDE 的明确指令」那段复制给 Trae IDE 开始 P1。
