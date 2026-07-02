# RAGAS 评测报告

## 配置
- enable_rerank: True
- enable_wiki: False
- top_k: 5
- 样本数: 50
- 平均 /chat 耗时: 30.4s

## 总分（每个 metric 的样本均值，NaN 表示该维度全部样本评估失败）
- **context_precision**: 0.4064
- **context_recall**: 0.5333
- **faithfulness**: 0.6841
- **answer_relevancy**: 0.5399

## 维度说明
- context_precision: 检索精度，前 K 命中相关 chunk 的比例，越高越好
- context_recall: 检索召回，ground_truth 被检索 chunk 覆盖比例，越高越好
- faithfulness: 答案忠实度，answer 是否基于 context 无幻觉，越高越好
- answer_relevancy: 答案相关性，answer 是否回应了 question，越高越好
  （注：DeepSeek API 不支持 n>1 多次采样，已设 strictness=1；若仍失败可能需换 LLM）

## 文件
- results.csv: 每条样本的 4 维度分数
- raw_samples.json: 原始问答样本（含 answer + contexts + 耗时）
