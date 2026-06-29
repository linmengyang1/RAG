#!/bin/bash
# 验证 hybrid_search wiki 路修复（不依赖 reranker，用 enable_rerank=false）
echo "=== 测试 search API（enable_rerank=false, enable_wiki=true）==="
RESP=$(curl -s -G http://localhost:18000/api/v1/search \
  --data-urlencode "q=导师" \
  --data-urlencode "top_k=3" \
  --data-urlencode "enable_rerank=false" \
  --data-urlencode "enable_wiki=true" \
  --max-time 60)

echo "$RESP" | python3 << 'PYEOF'
import sys, json
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print("JSON 解析失败:", e)
    sys.exit(1)
print("total:", d.get("total"))
print("query:", d.get("query"))
results = d.get("results", [])
print("results count:", len(results))
for i, r in enumerate(results):
    sources = r.get("retrieval_sources", [])
    score = r.get("score")
    rerank = r.get("rerank_score")
    page = r.get("page_num")
    cs = r.get("char_start")
    ce = r.get("char_end")
    text = (r.get("text") or "")[:50].replace("\n", " ")
    title = r.get("title", "")
    entry_type = r.get("category", "")
    print(f"  [{i}] sources={sources} score={score} rerank={rerank} page={page} char={cs}-{ce}")
    if title:
        print(f"      title={title} type={entry_type}")
    print(f"      text={text}")
PYEOF

echo ""
echo "=== backend 日志（wiki 相关，最近 2 分钟）==="
docker logs grad-rag-backend --since 2m 2>&1 | grep -iE "wiki|hybrid_search|检索结果" | tail -10
