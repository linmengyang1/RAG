"""重排序器：用 bge-reranker-v2-m3 对召回结果精排

照搬 embedder.py 的单例懒加载模式（_model + get_reranker）。
FlagReranker 与 BGEM3FlagModel 同属 FlagEmbedding 包，无新增依赖。

用法：
    from app.services.retrieval.reranker import rerank
    pairs = rerank("导师信息怎么查", ["张三是导师", "李四是学生"], top_k=2)
    # 返回 [(原索引, 归一化分数), ...] 降序
"""
from __future__ import annotations

import time
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
    t0 = time.perf_counter()

    # compute_score: normalize=True 输出 sigmoid 归一化分数（0-1）
    # max_length=512：FlagReranker 用 dynamic padding（pad 到 batch 内最长），
    # max_length 控制截断上限。长文档（>512 token）截断到 512 既能加速
    # （30 文档 621 token：512=37s vs 1024=46s），又保留前 512 token 信息
    # （中文约 340 字，通常覆盖文档核心内容）。
    # batch_size=8：实测最优区间。两次探测（临时脚本，已删，结论记此）：
    #
    # [探测1 短文档] 30 个相同短文档（~100 字）：
    #   batch_size=1:  18.32s（30 次独立前向传播，最慢）
    #   batch_size=4:   4.35s（8 批，最快）
    #   batch_size=8:   4.73s（4 批）
    #   batch_size=16:  4.54s（2 批）
    #   batch_size=30:  5.97s（1 批，单批反而慢——显存压力大或 GPU 降频）
    #   batch_size=128: 5.95s（FlagReranker 默认，同 30）
    #
    # [探测2 真实文档] 30 个真实检索候选（avg 583 字, max 702 字）：
    #   batch_size=4:  22.22s（8 批）
    #   batch_size=8:  19.10s（4 批，最优）
    #   batch_size=16: 24.25s（2 批）
    #   batch_size=30: 34.96s（1 批，最慢，即 FlagReranker 默认行为）
    #
    # 真实场景 batch_size=8 相比默认 128 提升 ~45%（19s vs 35s）。
    # 另测得 max_length 影响（batch_size=8, 30 真实候选）：
    #   max_length=128:  5.83s（3.3x 加速，但截断 85% 文档，质量风险高）
    #   max_length=256: 11.53s（1.7x 加速，截断 70%，需 RAGAS 验证）
    #   max_length=384: 16.63s
    #   max_length=512: 19.24s（当前值）
    # 若需进一步优化，降 max_length 到 256 收益最大（19s→11.5s），
    # 但需先跑 RAGAS 对比评测验证不降召回。
    scores = model.compute_score(
        pairs, normalize=True, max_length=512, batch_size=8
    )
    # 单条时 compute_score 返回 float，需归一化为 list
    if isinstance(scores, float):
        scores = [scores]

    # 加原索引后按分数降序
    indexed: list[tuple[int, float]] = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    elapsed = time.perf_counter() - t0
    logger.info(
        f"rerank 完成: top1 score={indexed[0][1]:.4f}, "
        f"耗时={elapsed:.2f}s, batch_size=8"
        if indexed
        else f"rerank 空, 耗时={elapsed:.2f}s"
    )
    return indexed[:top_k]
