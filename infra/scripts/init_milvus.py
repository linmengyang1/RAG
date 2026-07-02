"""
Milvus 集合与索引初始化（幂等）。

用法：
    python init_milvus.py
    或：make init-milvus

会创建两个 collection：
  1. chunks  — 通用切片检索（dense 1024 + sparse）
  2. wiki    — Wiki 沉淀条目向量

环境变量：
    MILVUS_HOST, MILVUS_PORT, MILVUS_COLLECTION_CHUNKS, MILVUS_COLLECTION_WIKI, EMBED_DIM
"""
from __future__ import annotations

import os
import sys
import time

from pymilvus import MilvusClient, DataType


def get_client() -> MilvusClient:
    host = os.getenv("MILVUS_HOST", "localhost")
    port = int(os.getenv("MILVUS_PORT", "19530"))
    uri = f"http://{host}:{port}"
    print(f"[init_milvus] 连接 Milvus: {uri}")
    # 等待 Milvus 就绪（最多 60s）
    for i in range(60):
        try:
            client = MilvusClient(uri=uri)
            client.list_collections()
            return client
        except Exception as e:  # noqa: BLE001
            if i == 0:
                print(f"[init_milvus] 等待 Milvus 就绪... ({e})")
            time.sleep(1)
    raise RuntimeError("Milvus 在 60s 内未就绪")


def drop_if_exists(client: MilvusClient, name: str) -> None:
    if client.has_collection(name):
        print(f"[init_milvus] 集合 {name} 已存在，先删除重建")
        client.drop_collection(name)


def create_chunks_collection(client: MilvusClient, name: str, dim: int) -> None:
    """通用切片检索：dense + sparse + 元数据过滤"""
    schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("text", DataType.VARCHAR, max_length=8192)
    schema.add_field("doc_id", DataType.INT64)
    schema.add_field("category", DataType.VARCHAR, max_length=64)
    schema.add_field("college", DataType.VARCHAR, max_length=128)
    schema.add_field("subject", DataType.VARCHAR, max_length=128)
    schema.add_field("source_url", DataType.VARCHAR, max_length=512)
    schema.add_field("published_at", DataType.INT64)        # 时间戳，过滤用
    # 原文位置元数据（UI 展示用，不做索引）
    schema.add_field("page_num", DataType.INT64)             # PDF 页码（md 为 0）
    schema.add_field("char_start", DataType.INT64)           # 原文起始字符位置
    schema.add_field("char_end", DataType.INT64)             # 原文结束字符位置

    index_params = client.prepare_index_params()
    # 稠密向量：HNSW + COSINE
    index_params.add_index(
        field_name="dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 256},
    )
    # 稀疏向量：SPARSE_INVERTED_INDEX + IP（等同 BM25）
    index_params.add_index(
        field_name="sparse",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",
        params={"bm25_k1": 1.2, "bm25_b": 0.75},
    )
    # 标量字段索引（加速过滤）
    for f in ("category", "college", "doc_id"):
        index_params.add_index(field_name=f, index_type="", index_name=f"scalar_{f}")

    client.create_collection(
        collection_name=name,
        schema=schema,
        index_params=index_params,
    )
    print(f"[init_milvus] ✓ 创建 chunks 集合: {name} (dim={dim})")


def create_wiki_collection(client: MilvusClient, name: str, dim: int) -> None:
    """Wiki 沉淀条目：仅 dense 向量（条目摘要）"""
    schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("title", DataType.VARCHAR, max_length=255)
    schema.add_field("entry_type", DataType.VARCHAR, max_length=32)
    schema.add_field("content", DataType.VARCHAR, max_length=32768)
    schema.add_field("summary", DataType.VARCHAR, max_length=1024)
    # 新增分类元数据字段（bwiki 风格分类导航用）
    schema.add_field("category", DataType.VARCHAR, max_length=64)
    schema.add_field("college", DataType.VARCHAR, max_length=128)
    schema.add_field("subject", DataType.VARCHAR, max_length=128)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="dense",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 256},
    )
    index_params.add_index(field_name="entry_type", index_type="", index_name="scalar_entry_type")
    # 新增分类字段标量索引
    index_params.add_index(field_name="college", index_type="", index_name="scalar_college")
    index_params.add_index(field_name="category", index_type="", index_name="scalar_category")

    client.create_collection(
        collection_name=name,
        schema=schema,
        index_params=index_params,
    )
    print(f"[init_milvus] ✓ 创建 wiki 集合: {name} (dim={dim})")


def main() -> None:
    chunks_name = os.getenv("MILVUS_COLLECTION_CHUNKS", "chunks")
    wiki_name = os.getenv("MILVUS_COLLECTION_WIKI", "wiki")
    dim = int(os.getenv("EMBED_DIM", "1024"))

    client = get_client()

    # chunks：若已存在则跳过（避免误删数据）；要重建用 --force
    force = "--force" in sys.argv
    if force:
        drop_if_exists(client, chunks_name)
        drop_if_exists(client, wiki_name)

    if not client.has_collection(chunks_name):
        create_chunks_collection(client, chunks_name, dim)
    else:
        print(f"[init_milvus] chunks 已存在，跳过（如需重建加 --force）")

    if not client.has_collection(wiki_name):
        create_wiki_collection(client, wiki_name, dim)
    else:
        print(f"[init_milvus] wiki 已存在，跳过（如需重建加 --force）")

    # 列出最终状态
    cols = client.list_collections()
    print(f"[init_milvus] 当前集合: {cols}")
    for c in cols:
        stats = client.get_collection_stats(c)
        print(f"  - {c}: {stats}")

    # 加载集合到 QueryNode 内存（Milvus 重启后必须，否则检索报 collection on recovering）
    # load_collection 不占磁盘，只把向量数据从 MinIO 读到 QueryNode RAM
    for name in (chunks_name, wiki_name):
        try:
            print(f"[init_milvus] 加载集合到内存: {name} ...")
            client.load_collection(name)
            print(f"[init_milvus] {name} 已加载到内存")
        except Exception as e:
            # load 失败不影响集合创建，只是检索暂不可用（Milvus 未就绪时可能失败）
            print(f"[init_milvus] 加载 {name} 失败（不影响集合创建）: {e}")


if __name__ == "__main__":
    main()
