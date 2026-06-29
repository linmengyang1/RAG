#!/bin/bash
# 干净测试：保存响应到文件再解析
echo "=== 测试 search API（enable_rerank=false, enable_wiki=true）==="
curl -s -G http://localhost:18000/api/v1/search \
  --data-urlencode "q=导师" \
  --data-urlencode "top_k=3" \
  --data-urlencode "enable_rerank=false" \
  --data-urlencode "enable_wiki=true" \
  --max-time 90 \
  -o /tmp/search_resp.json

echo "响应文件大小：$(wc -c < /tmp/search_resp.json) 字节"
echo ""
echo "=== 解析响应 ==="
python3 << 'PYEOF'
import json
with open("/tmp/search_resp.json", "r", encoding="utf-8") as f:
    d = json.load(f)
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
    text = (r.get("text") or "")[:60].replace("\n", " ")
    title = r.get("title", "")
    cat = r.get("category", "")
    print(f"  [{i}] sources={sources} score={score} rerank={rerank}")
    print(f"      page={page} char={cs}-{ce} category={cat}")
    if title:
        print(f"      title={title}")
    print(f"      text={text}")
PYEOF
