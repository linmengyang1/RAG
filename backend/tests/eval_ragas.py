"""RAGAS 评测脚本：量化 RAG 系统质量基线

评估 4 个维度:
- context_precision: 检索精度（前 K 命中相关 chunk 的比例，越高越好）
- context_recall: 检索召回（ground_truth 被检索 chunk 覆盖的比例，越高越好）
- faithfulness: 答案忠实度（answer 是否基于 context，无幻觉，越高越好）
- answer_relevancy: 答案相关性（answer 是否回应了 question，越高越好）

运行环境：在 backend 容器内执行（需先 pip install -e ".[eval]"）

用法:
    docker exec -it grad-rag-backend bash

    # 基线评测（默认 5 个 QA，rerank 开，wiki 关，top_k=5）
    python tests/eval_ragas.py

    # 完整 30 个 QA 评测（约 10-15 分钟，主要耗在 rerank）
    python tests/eval_ragas.py --limit 30

    # 对比配置：关闭 rerank（验证 rerank 价值，~3s/次）
    python tests/eval_ragas.py --no-rerank --limit 30

    # 对比配置：开启 wiki（验证 wiki 增益）
    python tests/eval_ragas.py --wiki --limit 30

    # 调整 top_k（验证候选集影响）
    python tests/eval_ragas.py --top-k 10 --limit 30

输出:
    backend/tests/eval_results/<config>_<timestamp>/
        - report.md: 汇总报告
        - results.csv: 每条样本的 4 维度分数
        - raw_samples.json: 原始问答样本（含 answer + contexts + 耗时）
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from app.core.config import settings

# ───── 路径常量 ─────
# backend 容器内监听 8000；从容器内调用走 localhost 即可（不走宿主机 18000）
BACKEND_URL = "http://localhost:8000"
DATASET_PATH = Path(__file__).parent / "eval_dataset.json"
OUTPUT_DIR = Path(__file__).parent / "eval_results"


def load_dataset(limit: int | None = None) -> list[dict]:
    """加载评测数据集（按 limit 截取前 N 条）"""
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if limit:
        data = data[:limit]
    return data


def _get_auth_token() -> str:
    """登录 admin 账号拿 JWT token，供 AUTH_DISABLED=false 时调用 /chat

    AUTH_DISABLED=false 后 /chat 需要 Bearer token，否则返回 401。
    用全局 _token_cache 避免每条 QA 重复登录。
    """
    global _token_cache
    if _token_cache:
        return _token_cache
    login_resp = httpx.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
        timeout=30,
    )
    login_resp.raise_for_status()
    _token_cache = login_resp.json().get("access_token")
    if not _token_cache:
        raise RuntimeError("登录 admin 失败：响应无 access_token")
    return _token_cache


_token_cache: str | None = None


def call_chat(
    question: str, top_k: int, enable_rerank: bool, enable_wiki: bool
) -> dict:
    """调用 backend /chat 端点，返回 {answer, sources, intent, elapsed}

    AUTH_DISABLED=false 时自动带 Bearer token（登录 admin/admin123）。
    超时设为 600s：rerank 30 候选约 36s + LLM 生成约 5-10s，留足余量。
    """
    payload = {
        "question": question,
        "top_k": top_k,
        "enable_rerank": enable_rerank,
        "enable_wiki": enable_wiki,
    }
    headers = {"Authorization": f"Bearer {_get_auth_token()}"}
    t0 = time.time()
    with httpx.Client(timeout=600) as client:
        r = client.post(f"{BACKEND_URL}/api/v1/chat", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    data["elapsed"] = time.time() - t0
    return data


def build_llm():
    """构造 RAGAS 用的 LLM（InstructorLLM，DeepSeek 兼容 OpenAI 接口）

    ragas 0.4+ 的 collections metrics 只支持 InstructorLLM，不再接受 LangchainLLMWrapper。
    用 llm_factory 包装 AsyncOpenAI client（ascore 是异步方法，需异步 client；
    DeepSeek 走 OpenAI 兼容协议）。

    设 max_tokens=8192：DeepSeek 默认 max_tokens 较小（~4K），
    faithfulness 评估需长输出（拆解 claim + 验证），输出被截断会报
    "The output is incomplete due to a max_tokens length limit."
    """
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    # DeepSeek 走 OpenAI 兼容协议，base_url 指向 deepseek_api_base
    # 用 AsyncOpenAI：ragas collections metric 的 ascore 是异步方法
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_api_base,
    )
    return llm_factory(
        settings.deepseek_main_model,
        client=client,
        max_tokens=8192,
    )


def build_embeddings():
    """构造 RAGAS 用的 Embeddings（本地 BGE-M3，CPU 模式）

    ragas 0.4+ 的 collections metrics 只支持 InstructorLLM 配套的 embeddings。
    用 ragas.embeddings.HuggingFaceEmbeddings（内部走 sentence-transformers）。

    device="cpu"：强制 CPU 推理，避免与 backend 容器争抢 GTX 1660 SUPER 6GB 显存。
    answer_relevancy 计算 question 和 response 的 embedding 相似度，CPU 上 BGE-M3
    推理单条约 0.5-1s，50 条样本约 25-50s，可接受。
    """
    from ragas.embeddings import HuggingFaceEmbeddings as RagasHuggingFaceEmbeddings

    return RagasHuggingFaceEmbeddings(model=settings.embed_model, device="cpu")


def run_ragas(samples: list[dict]) -> list[dict]:
    """对每个样本逐个评估 4 个维度，返回 [{metric: score}, ...]

    ragas 0.4 的 evaluate() 仍用旧 Metric 类做 isinstance 检查，
    与 collections 新 BaseMetric 不兼容，会抛
    "All metrics must be initialised metric objects" TypeError。
    故改用 RAGAS 0.4 推荐的 SingleTurnSample + single_turn_ascore 逐样本评估，
    绕过 evaluate 的 Metric 类型检查。

    注：AnswerRelevancy 的 strictness 默认 3（采样 3 次），
    DeepSeek API 不支持 n>1 会报 BadRequestError，故设 strictness=1 只采样 1 次。
    """
    import asyncio

    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    llm = build_llm()
    embeddings = build_embeddings()

    # 4 个维度全开：前 3 个仅需 LLM，answer_relevancy 需 embeddings（CPU 模式）
    metrics = {
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings, strictness=1),
    }

    print(
        f"RAGAS 逐样本评估: {len(samples)} 个样本，"
        f"LLM={settings.deepseek_main_model}，"
        f"Embeddings={settings.embed_model}"
    )

    async def _score_one(sample_dict: dict) -> dict:
        # 每个 metric 的 ascore 参数不同（按 RAGAS 0.4 collections 签名）
        # ContextPrecision.ascore(user_input, reference, retrieved_contexts)
        # ContextRecall.ascore(user_input, retrieved_contexts, reference)
        # Faithfulness.ascore(user_input, response, retrieved_contexts)
        # AnswerRelevancy.ascore(user_input, response)
        user_input = sample_dict["question"]
        response = sample_dict["answer"]
        retrieved_contexts = sample_dict["contexts"]
        reference = sample_dict["ground_truth"]

        # 用 lambda 延迟调用，便于捕获每个 metric 单独的异常
        metric_calls = {
            "context_precision": lambda: metrics["context_precision"].ascore(
                user_input=user_input,
                reference=reference,
                retrieved_contexts=retrieved_contexts,
            ),
            "context_recall": lambda: metrics["context_recall"].ascore(
                user_input=user_input,
                retrieved_contexts=retrieved_contexts,
                reference=reference,
            ),
            "faithfulness": lambda: metrics["faithfulness"].ascore(
                user_input=user_input,
                response=response,
                retrieved_contexts=retrieved_contexts,
            ),
            "answer_relevancy": lambda: metrics["answer_relevancy"].ascore(
                user_input=user_input,
                response=response,
            ),
        }

        scores: dict[str, float | None] = {}
        for name, call in metric_calls.items():
            try:
                # ascore 返回 MetricResult，取 .value 拿分数（0.0-1.0）
                result = await call()
                v = result.value if hasattr(result, "value") else result
                scores[name] = float(v) if v is not None else None
            except Exception as e:
                print(f"    {name} 评估失败: {e}", flush=True)
                scores[name] = None
        return scores

    async def _score_all() -> list[dict]:
        all_scores: list[dict] = []
        # 串行评估：避免并发触发 DeepSeek 限流（429）
        for i, s in enumerate(samples, 1):
            print(f"  评估 [{i}/{len(samples)}]...", flush=True)
            scores = await _score_one(s)
            all_scores.append(scores)
            print(f"    -> {scores}", flush=True)
        return all_scores

    return asyncio.run(_score_all())


def write_report(args, samples: list[dict], all_scores: list[dict]) -> tuple[Path, dict]:
    """输出 markdown 报告 + csv + 原始样本，返回 (输出目录, 各维度均分)

    all_scores 是 [{metric: score}, ...]，与 samples 一一对应。
    score 为 None 表示该维度评估失败。
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    config_tag = f"rerank-{int(args.rerank)}_wiki-{int(args.wiki)}_topk-{args.top_k}"
    out_dir = OUTPUT_DIR / f"{config_tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    metric_names = [
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevancy",
    ]

    # 1. 原始样本（含 answer + contexts + 耗时）
    (out_dir / "raw_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2. csv 详细结果：每条样本 + 4 维度分数
    import csv

    csv_path = out_dir / "results.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        header = ["question", "answer", "intent", "elapsed"] + metric_names
        writer.writerow(header)
        for s, sc in zip(samples, all_scores):
            row = [
                s["question"],
                s["answer"],
                s.get("intent", ""),
                f"{s.get('elapsed', 0):.1f}",
            ] + [sc.get(m) if sc.get(m) is not None else "NaN" for m in metric_names]
            writer.writerow(row)

    # 3. 计算各 metric 均值（None 跳过）
    avg_scores: dict[str, float] = {}
    for m in metric_names:
        vals = [sc.get(m) for sc in all_scores if sc.get(m) is not None]
        avg_scores[m] = sum(vals) / len(vals) if vals else float("nan")

    # 4. markdown 汇总报告
    avg_elapsed = sum(s.get("elapsed", 0) for s in samples) / max(len(samples), 1)
    report = f"""# RAGAS 评测报告

## 配置
- enable_rerank: {args.rerank}
- enable_wiki: {args.wiki}
- top_k: {args.top_k}
- 样本数: {len(samples)}
- 平均 /chat 耗时: {avg_elapsed:.1f}s

## 总分（每个 metric 的样本均值，NaN 表示该维度全部样本评估失败）
"""
    for m in metric_names:
        v = avg_scores[m]
        if v == v:
            report += f"- **{m}**: {v:.4f}\n"
        else:
            report += f"- **{m}**: NaN（评估失败）\n"

    report += f"""
## 维度说明
- context_precision: 检索精度，前 K 命中相关 chunk 的比例，越高越好
- context_recall: 检索召回，ground_truth 被检索 chunk 覆盖比例，越高越好
- faithfulness: 答案忠实度，answer 是否基于 context 无幻觉，越高越好
- answer_relevancy: 答案相关性，answer 是否回应了 question，越高越好
  （注：DeepSeek API 不支持 n>1 多次采样，已设 strictness=1；若仍失败可能需换 LLM）

## 文件
- results.csv: 每条样本的 4 维度分数
- raw_samples.json: 原始问答样本（含 answer + contexts + 耗时）
"""
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    return out_dir, avg_scores


def main():
    parser = argparse.ArgumentParser(description="RAGAS 评测脚本")
    parser.add_argument(
        "--limit", type=int, default=5, help="评测 QA 数量上限（默认 5）"
    )
    parser.add_argument("--top-k", type=int, default=5, help="检索 top_k（默认 5）")
    parser.add_argument(
        "--rerank", dest="rerank", action="store_true", default=True, help="启用 rerank（默认）"
    )
    parser.add_argument(
        "--no-rerank", dest="rerank", action="store_false", help="禁用 rerank"
    )
    parser.add_argument(
        "--wiki", dest="wiki", action="store_true", default=False, help="启用 wiki 检索"
    )
    parser.add_argument(
        "--no-wiki", dest="wiki", action="store_false", help="禁用 wiki 检索（默认）"
    )
    args = parser.parse_args()

    print(
        f"配置: rerank={args.rerank}, wiki={args.wiki}, "
        f"top_k={args.top_k}, limit={args.limit}"
    )
    print(f"加载评测数据集: {DATASET_PATH}")

    dataset = load_dataset(args.limit)
    print(f"加载 {len(dataset)} 个 QA\n")

    # 1. 调 backend /chat 拿答案 + contexts
    samples: list[dict] = []
    total_t0 = time.time()
    for i, qa in enumerate(dataset, 1):
        q = qa["question"]
        print(f"[{i}/{len(dataset)}] Q: {q}", flush=True)
        try:
            resp = call_chat(
                q,
                top_k=args.top_k,
                enable_rerank=args.rerank,
                enable_wiki=args.wiki,
            )
            answer = resp.get("answer", "")
            sources = resp.get("sources", [])
            contexts = [s.get("text", "") for s in sources if s.get("text")]
            elapsed = resp.get("elapsed", 0)
            print(
                f"  -> answer_len={len(answer)}, contexts={len(contexts)}, "
                f"intent={resp.get('intent', '?')}, elapsed={elapsed:.1f}s",
                flush=True,
            )
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            answer = ""
            contexts = []
            elapsed = 0

        samples.append(
            {
                "question": q,
                "answer": answer,
                "contexts": contexts,
                "ground_truth": qa["ground_truth"],
                "intent": qa.get("intent", ""),
                "elapsed": elapsed,
            }
        )

    print(f"\n/chat 阶段完成，总耗时 {time.time() - total_t0:.1f}s")

    # 2. RAGAS evaluate
    print("\n开始 RAGAS evaluate（会调用 DeepSeek 评估，约 2-3 分钟）...")
    t0 = time.time()
    result = run_ragas(samples)
    print(f"RAGAS 完成，耗时 {time.time() - t0:.1f}s\n")

    # 3. 输出报告
    out_dir, avg_scores = write_report(args, samples, result)
    print(f"报告已保存: {out_dir / 'report.md'}")
    print(f"详细结果: {out_dir / 'results.csv'}")
    print(f"原始样本: {out_dir / 'raw_samples.json'}")
    print("\n分数（每个 metric 的样本均值）:")
    for k, v in avg_scores.items():
        if v == v:  # NaN check
            print(f"  {k}: {v:.4f}")
        else:
            print(f"  {k}: NaN（评估失败）")


if __name__ == "__main__":
    main()
