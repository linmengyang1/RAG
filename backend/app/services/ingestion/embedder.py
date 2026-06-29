"""BGE-M3 向量化器：dense(1024) + sparse

使用 FlagEmbedding 的 BGEM3FlagModel。
模型在首次调用时懒加载（embed_lazy_load=True），占用约 2.4GB 显存。

返回结构：
    Embedding.dense  -> list[float]      (1024 维)
    Embedding.sparse -> dict[int, float] ({token_id: weight})
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.core.config import settings
from app.core.logging import logger


@dataclass
class Embedding:
    """一个文本的向量表示"""
    dense: List[float]            # 1024 维稠密向量
    sparse: Dict[int, float]      # 稀疏向量 {token_id: weight}


# 模型单例（懒加载）
_model = None


def get_model():
    """获取 BGEM3FlagModel 单例（首次调用时加载）"""
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel
        logger.info(
            f"加载 BGE-M3 模型: {settings.embed_model}, "
            f"device={settings.torch_device}, use_fp16={settings.torch_device == 'cuda'}"
        )
        _model = BGEM3FlagModel(
            settings.embed_model,
            use_fp16=settings.torch_device == "cuda",
            device=settings.torch_device,
        )
        logger.info("BGE-M3 模型加载完成")
    return _model


def embed(texts: List[str]) -> List[Embedding]:
    """批量向量化文本，返回 dense + sparse 向量

    Args:
        texts: 文本列表

    Returns:
        Embedding 列表（顺序与输入一致）
    """
    if not texts:
        return []

    model = get_model()
    logger.info(f"开始向量化 {len(texts)} 段文本")

    # BGEM3FlagModel.encode 返回 dict:
    #   'dense_vecs': numpy.ndarray, shape (n, 1024)
    #   'lexical_weights': list[dict[int, float]]
    # 注意：return_sparse 默认 False，必须显式开启才有稀疏向量（BM25 检索用）
    output = model.encode(
        texts,
        batch_size=12,
        max_length=8192,
        return_dense=True,
        return_sparse=True,           # 开启稀疏向量（BM25 检索用）
        return_colbert_vecs=False,
    )

    dense_vecs = output["dense_vecs"]
    lexical_weights = output["lexical_weights"]

    results: list[Embedding] = []
    for i in range(len(texts)):
        # dense: numpy array -> list[float]
        dense = dense_vecs[i].tolist()
        # sparse: dict[int, float]（key 可能是 int 或 numpy int）
        sparse = {int(k): float(v) for k, v in lexical_weights[i].items()}
        results.append(Embedding(dense=dense, sparse=sparse))

    logger.info(f"向量化完成: {len(results)} 个向量")
    return results
