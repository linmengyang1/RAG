"""重排序器：用 bge-reranker-v2-m3 对召回结果精排

照搬 embedder.py 的单例懒加载模式（_model + get_reranker）。
FlagReranker 与 BGEM3FlagModel 同属 FlagEmbedding 包，无新增依赖。

用法：
    from app.services.retrieval.reranker import rerank
    pairs = rerank("导师信息怎么查", ["张三是导师", "李四是学生"], top_k=2)
    # 返回 [(原索引, 归一化分数), ...] 降序
"""
from __future__ import annotations

from typing import List, Tuple

from app.core.config import settings
from app.core.logging import logger

# 模型单例（懒加载）
_model = None


def get_reranker():
    """获取 FlagReranker 单例（首次调用时加载）"""
    global _model
    if _model is None:
        from FlagEmbedding import FlagReranker
        logger.info(
            f"加载 reranker 模型: {settings.reranker_model}, "
            f"device={settings.torch_device}, use_fp16={settings.torch_device == 'cuda'}"
        )
        _model = FlagReranker(
            settings.reranker_model,
            use_fp16=settings.torch_device == "cuda",
            device=settings.torch_device,
        )
        logger.info("reranker 模型加载完成")
    return _model


def rerank(
    query: str, documents: List[str], top_k: int = 5
) -> List[Tuple[int, float]]:
    """对 documents 重排，返回 [(原索引, 归一化分数)] 降序前 top_k

    Args:
        query: 查询文本
        documents: 待重排的文档列表
        top_k: 返回前 K 条

    Returns:
        [(原索引, 归一化分数)]，分数范围 [0, 1]，按分数降序
    """
    if not documents:
        return []

    model = get_reranker()
    pairs = [[query, doc] for doc in documents]
    logger.info(f"rerank 开始: query={query[:50]!r}, docs={len(documents)}, top_k={top_k}")

    # compute_score: normalize=True 输出 sigmoid 归一化分数（0-1）
    scores = model.compute_score(pairs, normalize=True)
    # 单条时 compute_score 返回 float，需归一化为 list
    if isinstance(scores, float):
        scores = [scores]

    # 加原索引后按分数降序
    indexed: list[tuple[int, float]] = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"rerank 完成: top1 score={indexed[0][1]:.4f}" if indexed else "rerank 空")
    return indexed[:top_k]
