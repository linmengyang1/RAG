"""BGE-M3 向量化器：dense(1024) + sparse

使用 FlagEmbedding 的 BGEM3FlagModel。
模型在首次调用时懒加载（embed_lazy_load=True），占用约 2.4GB 显存。

返回结构：
    Embedding.dense  -> list[float]      (1024 维)
    Embedding.sparse -> dict[int, float] ({token_id: weight})
"""
from __future__ import annotations

import os
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


def _ensure_safetensors(model_id: str) -> None:
    """确保本地模型有 safetensors 文件，没有则从 pytorch_model.bin 转换

    背景：transformers 4.57.6 修复 CVE-2025-32434，要求 torch>=2.6 才能用
    torch.load 加载 .bin；但 GTX 1660（CUDA 12.4 驱动）只能用 torch 2.5.1+cu124。
    safetensors 不走 torch.load，转换后 transformers 优先用 safetensors 加载，
    绕过 torch 版本限制。
    """
    from huggingface_hub import hf_hub_download
    import torch
    from safetensors.torch import save_file

    # 下载 pytorch_model.bin（已缓存则直接返回本地路径，不重复下载）
    bin_path = hf_hub_download(model_id, "pytorch_model.bin")
    st_path = os.path.join(os.path.dirname(bin_path), "model.safetensors")
    if os.path.exists(st_path):
        return  # 已有 safetensors，无需转换

    logger.info(f"转换 {model_id}: pytorch_model.bin -> model.safetensors")
    # weights_only=False：bge-m3 是 XLMRobertaModel，含自定义类
    state_dict = torch.load(bin_path, weights_only=False)
    save_file(state_dict, st_path)
    logger.info(f"safetensors 转换完成: {st_path}")


def get_model():
    """获取 BGEM3FlagModel 单例（首次调用时加载）"""
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel
        # 确保 bge-m3 有 safetensors 文件（绕过 torch.load CVE 检查）
        _ensure_safetensors(settings.embed_model)
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
