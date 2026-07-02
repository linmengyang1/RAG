# Graduate RAG 项目现状与下一步计划

> 本文档记录项目当前进展、已实现功能、数据摄入现状，以及下一步工作。
> 更新时间：2026-07-02

---

## 一、项目现状

### 实施阶段进度

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
  - [x] 意图 few-shot + confidence 阈值
  - [x] 多问题拆解 + 输出长度控制

### 数据摄入现状（截至 2026-07-02）

| 类型 | 总数 | 已摄入 | 状态 |
|------|------|--------|------|
| Markdown（output/markdown） | 239 | 239 | 完成 |
| PDF（output/files） | 436 | 436 | 完成 |
| DOCX（output/files） | 121 | 121 | 完成 |
| **合计** | **810** | **810** | 全部 embedded |

- documents 表：810 条，全部 status=embedded
- chunks 表：5699 条，全部有 milvus_id（已写入 Milvus）
- wiki_entries 表：**1072 条**全量生成完成（person/policy/process 三类）
- mentors 表：**793 条**（从 wiki person 反推构建），mentor_id 填充率 98.1%
- conversations 表：3 条（测试数据），messages 表：对话消息

**全量摄入已完成**，数据管道端到端跑通。

---

## 二、已实现的核心功能

### 1. 数据接入管线（P1）

- scanner.py：递归扫描 output 目录，按路径推断 category/college/subject
- markdown_parser.py：解析 md 文件元数据表（日期/分类/来源/原始URL/附件）
- chunker.py：500 字符切片 + 200 重叠，记录 char_start/char_end + page_num
- embedder.py：BGE-M3 向量化（dense 1024 维 + sparse），safetensors 自动转换
- milvus_writer.py：写入 Milvus chunks 集合
- pipeline.py：端到端调度，幂等（file_path 唯一键，重跑不重复）

### 2. 混合检索（P2）

- dense 路：HNSW + COSINE（BGE-M3 1024 维）
- sparse 路：SPARSE_INVERTED_INDEX + IP（等同 BM25）
- RRF 融合：k=60，召回 K=max(top_k×6, 30)
- 可选 rerank：bge-reranker-v2-m3 精排（max_length=512）
- 可选 wiki 第三路：独立附加，不参与 RRF 融合

### 3. LLM 增强（P3）

- 意图识别：deepseek-v4-flash，8 类标签 + 8 个 few-shot 示例 + confidence 阈值（<0.5 回退"其他"）
- 代词消解：拉历史 8 条消息，消解指代
- query 改写：输出 rewritten_query 用于检索
- 多问题拆解：子问题独立检索 → LLM 合并答案（`COMBINE_ANSWERS_PROMPT`）
- 输出长度控制：简单问题≤200字 / 中等≤500字 / 统计不限（`_get_length_hint`）
- 多轮对话：Conversation/Message 表持久化
- 对话管理 CRUD：list/get/rename/delete + 前端侧边栏
- SSE 流式问答：分阶段推送思考过程（intent/retrieving/retrieved/generating/token/done）

### 4. Wiki 沉淀（P4）

- Wiki 生成：从 Milvus chunks 查全文，每 10 个 chunk 一批调 deepseek-v4-pro
- 提取 person/policy/process 三类候选，去重写 PG + Milvus
- Wiki 检索：在 wiki 集合做 dense 检索，独立附加在 chunks 结果末尾

### 5. 前端可视化（P5）

- 3 个 Tab：检索 / 问答 / Wiki
- 问答 Tab 支持 SSE 流式：
  - 实时显示思考阶段（意图识别 / 检索 / 生成）+ 实时耗时
  - 检索子阶段动态切换（向量化 / 向量检索 / 关键词检索 / rerank 精排）
  - 完成后折叠卡片显示各阶段耗时（意图识别 / 向量检索 / 关键词检索 / rerank 精排 / LLM 生成 / 总计）
- 元数据展示：检索方式三色标签 + 相似度进度条 + 原文位置（页码/字符范围）

---

## 三、关键技术决策记录

### 1. SSE 流式：Next.js 必须禁用 gzip 压缩

- 问题：Next.js 默认 `compress: true` 对 SSE 响应做 gzip，浏览器 `reader.read()` 需等足够数据才能解压，导致流式事件卡住（前端永远停在"意图识别中"）
- 解决：next.config.js 设置 `compress: false`
- 教训：curl 默认不发 `Accept-Encoding: gzip`，所以 curl 测试正常但浏览器异常，是诊断盲区

### 2. 检索子阶段进度推送：asyncio.Queue 跨线程桥接

- hybrid_search 在 `asyncio.to_thread` 子线程运行（避免 reranker 推理阻塞事件循环）
- 用 `asyncio.run_coroutine_threadsafe(queue.put(stage), loop)` 从子线程安全投递进度到主事件循环
- 主协程并发 yield `retrieving_stage` SSE 事件，实现 4 个子阶段实时推送：
  - embedding（BGE-M3 向量化）
  - dense（HNSW 向量检索）
  - sparse（BM25 关键词检索）
  - reranking（bge-reranker 精排）

### 3. MinerU 转换的 markdown 已落盘缓存（已实现）

- pipeline.py 对 pdf/docx 调 MinerU API，解析结果缓存到 `output/files_md/`（`_save_mineru_cache`，103-109 行）
- 重跑摄入时优先读缓存（`_mineru_cache_path`，86-98 行），不重复调 MinerU API
- 缓存按原始目录结构保存（`files/培养工作/xxx.pdf` → `files_md/培养工作/xxx.md`）
- 注意：缓存的 md 不含 page_map 页码映射，但不影响切片

### 4. 向量化结果只存 Milvus，不落盘

- embedding 结果直接写入 Milvus chunks 集合（dense + sparse 向量）
- chunk 文本存 PostgreSQL chunks 表
- 原始文件在 output/ 目录（只读挂载到容器 /data/output）
- 没有把向量单独存为文件（Milvus 已持久化，通过 milvus_data volume）

### 5. GPU 硬件限制

- 显卡：GTX 1660 SUPER 6GB（Turing 架构 GTX 系列，无 Tensor Core）
- BGE-M3 向量化：~2.4GB 显存，单 query 向量化约 0.3s
- bge-reranker-v2-m3：单次 rerank 30 个候选约 36s（fp16 无加速，硬件瓶颈）
- 显存占用 4.5/6.0GB 是模型权重，利用率 92% 是计算瓶颈，占满显存不会更快

---

## 四、下一步工作

全量数据摄入已完成（810 文档 / 5699 chunks）。后续完善工作详见综合计划书：

> [.trae/documents/project-completion-plan.md](../.trae/documents/project-completion-plan.md)

### 核心待办（按优先级，已移除完成项）

| 优先级 | 任务 | 预计 | 说明 |
|--------|------|------|------|
| ~~1~~ | ~~Mentors 实体补全~~ | — | ✅ 已完成（793 导师，98.1% 关联） |
| 1 | Reranker 优化 | 1 天 | 当前 36s 延迟，目标 10-15s |
| 2 | RAGAS 评测 | 1 天 | 建立检索/回答质量量化基线 |
| 3 | WikiLink 双向链接 | 0.5-1 天 | 零 token 成本方案（纯 SQL，见 plan v3 2.3） |
| ~~4~~ | ~~会话管理 UI~~ | — | ✅ 已完成（CRUD + 侧边栏） |
| 4 | 鉴权 UI | 1 天 | 登录页 + token 管理 + 路由守卫 |
| 5 | 错误处理增强 | 1 天 | MinerU 重试 / DeepSeek 限流 / Milvus 重连 / Toast |
| 6 | 监控 + 部署文档 | 2 天 | 摄入进度 / Milvus 健康 / etcd 备份 |

---

## 五、文件位置速查

### 数据文件

| 内容 | 位置 | 说明 |
|------|------|------|
| 原始 md | `c:\Users\lmy\Desktop\test\output\markdown\` | 已抓取网页正文，239 个 |
| 原始 PDF/DOCX | `c:\Users\lmy\Desktop\test\output\files\` | 附件，557 个 |
| 容器内挂载 | `/data/output/`（只读） | docker-compose 挂载 |

### 向量化结果存储

| 内容 | 位置 | 说明 |
|------|------|------|
| 向量数据 | Milvus `chunks` 集合 | dense + sparse 向量，5699 条 |
| chunk 文本 | PostgreSQL `chunks` 表 | 含 milvus_id / char_start / char_end / page_num |
| 文档元数据 | PostgreSQL `documents` 表 | file_path / status / category / college / subject |
| Wiki 向量 | Milvus `wiki` 集合 | 1072 条全量生成完成 |
| Wiki 元数据 | PostgreSQL `wiki_entries` 表 | person/policy/process 三类 |

### MinerU 转换的 md 位置

已落盘到 `output/files_md/`（按原始目录结构，`_save_mineru_cache` 实现）。
重跑摄入时优先读缓存，不重复调 MinerU API。

### 模型缓存

| 模型 | 位置 | 说明 |
|------|------|------|
| BGE-M3 | `graduate-rag/models/`（bind mount） | 约 2.4GB，首次下载后持久化 |
| bge-reranker-v2-m3 | HuggingFace cache（docker volume `huggingface_cache`） | 容器内 /root/.cache/huggingface |

---

## 六、环境约束速查

- Windows 11 + WSL2（Ubuntu）+ Docker Engine（在 WSL2 内）
- GPU：GTX 1660 SUPER 6GB，torch 2.5.1+cu124，CUDA 直通
- AUTH_DISABLED=true（测试期间免登录）
- DeepSeek API：v4-flash（主力）/ v4-pro（Wiki 生成）
- MinerU API：每天 2000 页高优先级配额
- 后端端口 18000，前端端口 3000
