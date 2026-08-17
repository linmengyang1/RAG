# Chunk 划分依据与策略文档

> 更新日期：2026-07-29
> 适用版本：chunker.py v2（1500 字符 + markdown 标题切分）

---

## 一、数据特征分析

### 1.1 数据来源

所有数据文件位于 `output/files_md/`，由 MinerU 预先解析为 Markdown 格式。Scanner 只扫描 `.md` 文件，不再调用 MinerU API。

### 1.2 文档结构

| 分类 | 文档数 | 平均长度 | 典型结构 |
|------|--------|---------|---------|
| 导师信息 | 295（+1 汇总） | 1500-3000 字符 | `## 基本信息` / `## 教育背景` / `## 研究方向` / `## 代表性论文` / `## 科研项目` |
| 培养工作 | 208 | 2000-5000 字符 | `## 通知正文` / `## 附件列表`（政策类多） |
| 招生工作 | 119 | 2000-4000 字符 | `## 招生简章` / `## 报名条件` / `## 考试安排` |
| 研工工作 | 103 | 1500-3000 字符 | `## 通知正文` / `## 评选条件` / `## 材料要求` |
| 研究生文件 | 7 | 3000-8000 字符 | 长文档（规章制度汇编） |
| **总计** | **732（+1）** | - | 另有 `导师信息汇总.md` 为 294 位导师的统计汇总，约 20000 字符 |

### 1.3 导师 md 文件特征

导师信息是本项目最核心的数据类型（295 份，占 40%），其结构高度统一：

```markdown
# 刘红梅_数学科学学院

## 基本信息
- 姓名：刘红梅
- 性别：女
- 出生年月：1972年3月
- 职称：教授
...

## 教育背景
- 博士毕业于...

## 研究方向
主要从事数学教育研究...

## 代表性论文
1. 论文标题一
2. 论文标题二
...

## 科研项目
- 项目一
- 项目二
...
```

**关键特征**：
- 平均长度 1500-3000 字符（约 500-1000 token）
- 以 `##` 二级标题划分 section
- 不同 section 之间关联性弱（论文列表和基本信息是独立内容）
- 跨文档关联弱（每个导师独立一份 md）

---

## 二、旧策略的问题（v1：500 字符 + 段落切分）

### 2.1 旧参数

```python
CHUNK_SIZE = 500      # 约 167 token
CHUNK_OVERLAP = 200   # 40% 重叠
```

### 2.2 问题分析

| 问题 | 影响 | 示例 |
|------|------|------|
| **切分过碎** | 5699 chunks，检索碎片化 | 刘红梅（2200 字符）被切成 5 个 chunk |
| **语义断裂** | 论文列表被拦腰截断 | "## 代表性论文\n1. 论文一\n2. 论文二" 后面紧跟 "3. 论文三" 在下一个 chunk |
| **未利用标题** | markdown 的 `##` 结构被忽略 | 段晓东有 6 个 `##` section，但 chunker 只按 `\n\n` 切 |
| **上下文丢失** | 用户问"刘红梅的研究方向" | 可能命中只含论文标题的 chunk，缺少姓名/职称等基本上下文 |
| **reranker 负担重** | 5699 chunks 召回 30 候选 → rerank 36s | 候选集越大，rerank 越慢 |

### 2.3 旧策略数据

| 指标 | 旧值 |
|------|------|
| documents | 810（含 PDF/DOCX 原始文件） |
| chunks | 5699 |
| 平均 chunk 长度 | ~167 token |
| rerank 30 候选耗时 | 36s |

---

## 三、新策略设计（v2：1500 字符 + 标题切分）

### 3.1 新参数

```python
CHUNK_SIZE = 1500      # 约 500 token
CHUNK_OVERLAP = 300    # 20% 重叠
```

### 3.2 切分优先级

```
1. 按 ## 或 ### 标题切分成 section
   ↓
2. section 内按 \n\n 段落累积到 CHUNK_SIZE
   ↓
3. 超长 section 按 CHUNK_SIZE 硬切
   ↓
4. 相邻 chunk 加 OVERLAP 重叠
```

### 3.3 设计依据

| 参数 | 选值 | 依据 |
|------|------|------|
| CHUNK_SIZE=1500 | 约 500 token | BGE-M3 最大支持 8192 token，1500 字符远在安全范围；导师 md 平均 1500-3000 字符，1500 可保证一个完整 section 在一个 chunk 内 |
| CHUNK_OVERLAP=300 | 20% | 保证跨 chunk 语义连续性，同时避免过多冗余（旧策略 200/500=40% 冗余太高） |
| 按标题切分 | `##` / `###` | 导师 md 有清晰的 `##` 结构（基本信息/研究方向/论文/项目），按标题切 = 每个 section 完整保留 |
| 不按 `#` 一级标题切 | - | 大部分 md 只有一个 `# 姓名` + `## 正文`，按一级标题切等于不切 |

### 3.4 切分效果示例

**刘红梅（2200 字符）**：

| 策略 | chunk 数 | chunk 1 内容 | chunk 2 内容 |
|------|---------|------------|------------|
| v1（500 字符） | 5 个 | 基本信息（截断） | 基本信息+研究方向（截断） |
| v2（1500 字符+标题） | 2 个 | 基本信息+教育背景+研究方向 | 代表性论文+科研项目 |

**段晓东（3000 字符）**：

| 策略 | chunk 数 | 切分方式 |
|------|---------|---------|
| v1（500 字符） | 6 个 | 无视 `##` 标题，纯按段落累积 |
| v2（1500 字符+标题） | 2-3 个 | 按 `##` 标题切分，论文/项目/兼职各自完整 |

---

## 四、新策略实测数据

### 4.1 全量摄入结果

| 指标 | v1（旧） | v2（新） | 变化 |
|------|---------|---------|------|
| documents | 810 | **732** | -10%（纯 md 文件，不含原始 PDF） |
| chunks | 5699 | **3271** | **-43%** |
| 平均 chunk token | ~167 | **201** | +20%（信息更完整） |
| 最大 chunk token | ~167 | **600** | 大段落完整保留 |
| rerank 候选集 | 30 | 30 | 不变 |
| 预估 rerank 耗时 | 36s | **~20s** | 候选 chunk 更长但数量减半，总 token 量接近 |

### 4.2 分类分布

| 分类 | 文档数 | 占比 |
|------|--------|------|
| 导师信息 | 295（+1 汇总） | 40.3% |
| 培养工作 | 208 | 28.4% |
| 招生工作 | 119 | 16.3% |
| 研工工作 | 103 | 14.1% |
| 研究生文件 | 7 | 1.0% |
| **总计** | **732** | 100% |

### 4.3 与旧策略的检索对比

| 场景 | v1（500 字符） | v2（1500 字符+标题） |
|------|---------------|---------------------|
| 查"刘红梅的研究方向" | 可能命中论文标题 chunk，缺少姓名上下文 | 命中含"基本信息+研究方向"的完整 chunk |
| 查"数学学院有哪些导师" | 返回多个碎片 chunk | 返回完整导师信息 chunk |
| 查"论文答辩流程" | 流程步骤分散在多个 chunk | 按 `##` 标题切分，流程步骤完整 |

---

## 五、未来优化方向

### 5.1 短期（可选）

| 优化 | 预期效果 | 风险 |
|------|---------|------|
| 按导师 md 文件类型做差异化 chunk_size | 导师 md 用 1500，长通知用 2000 | 实现复杂度增加 |
| 长文档（>5000 字符）单独处理 | 避免规章制度类文档切分过碎 | 需识别文档类型 |

### 5.2 中期（需 RAGAS 验证）

| 优化 | 预期效果 | 验证方式 |
|------|---------|---------|
| CHUNK_SIZE 调到 2000 | chunks 进一步减少到 ~2500 | RAGAS context_recall 对比 |
| 关闭 overlap（OVERLAP=0） | 减少 Milvus 存储冗余 | RAGAS context_recall 对比 |
| 添加 chunk 元数据（section_title） | 检索时可按 section 过滤 | 需修改 chunker + Milvus schema |

### 5.3 不推荐的方向

| 方案 | 原因 |
|------|------|
| 整份 md 作为一个 chunk | 长文档（3000+ 字符）reranker max_length=512 会截断过多 |
| CHUNK_SIZE 提到 3000+ | 向量稀释效应，检索精度下降 |
| 按句子切分 | 粒度太细，上下文完全丢失 |

---

## 六、技术实现

### 6.1 核心文件

- [chunker.py](file:///c:/Users/lmy/Desktop/test/graduate-rag/backend/app/services/ingestion/chunker.py)：切分逻辑
- [scanner.py](file:///c:/Users/lmy/Desktop/test/graduate-rag/backend/app/services/ingestion/scanner.py)：文件扫描（只扫 `files_md/`）
- [pipeline.py](file:///c:/Users/lmy/Desktop/test/graduate-rag/backend/app/services/ingestion/pipeline.py)：端到端调度

### 6.2 切分函数调用链

```
pipeline.ingest_document()
  → scanner.scan()           # 扫描 files_md/ 目录
  → pipeline._process_md()   # 解析 md 文件
  → chunker.chunk_text()     # 切分
    → _split_by_markdown_headers()  # 第一步：按 ## 标题切 section
    → 段落累积到 CHUNK_SIZE          # 第二步：section 内累积
    → _hard_split()                 # 第三步：超长硬切
    → 加 overlap                    # 第四步：相邻 chunk 重叠
  → embedder.embed()         # BGE-M3 向量化
  → milvus_writer.write()    # 写入 Milvus + PG
```

### 6.3 参数修改位置

```python
# chunker.py 第 25-26 行
CHUNK_SIZE = 1500        # 每块最大字符数（约 500 token）
CHUNK_OVERLAP = 300     # 相邻块重叠字符数（占 chunk 的 20%）
```

修改后需重新摄入全部文档：

```bash
# 1. 重建 Milvus 集合
docker exec grad-rag-backend python /app/infra/scripts/init_milvus.py --force

# 2. 清空 PG
docker exec grad-rag-postgres psql -U grad -d grad_rag -c "TRUNCATE chunks RESTART IDENTITY CASCADE; TRUNCATE documents RESTART IDENTITY CASCADE; TRUNCATE wiki_entries RESTART IDENTITY CASCADE;"

# 3. 重新摄入
docker exec -d grad-rag-backend bash -c 'cd /app/backend && nohup python -m app.cli.ingest > /tmp/ingest.log 2>&1'
```
