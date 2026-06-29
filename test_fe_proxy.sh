#!/bin/bash
# 测试 frontend 代理是否正确转发到 backend
set -e
echo "=== frontend 日志 ==="
docker logs grad-rag-frontend --tail 8 2>&1
echo ""
echo "=== 测试 search via frontend（localhost:3000 → backend:8000）==="
HTTP_CODE=$(curl -s -G http://localhost:3000/api/v1/search \
  --data-urlencode "q=导师" \
  --data-urlencode "top_k=3" \
  --data-urlencode "enable_rerank=false" \
  --data-urlencode "enable_wiki=false" \
  --max-time 30 \
  -o /tmp/fe_search.json \
  -w "%{http_code}")
echo "HTTP $HTTP_CODE"
echo ""
echo "=== 解析响应 ==="
python3 << 'PYEOF'
import json
with open("/tmp/fe_search.json", "r", encoding="utf-8") as f:
    d = json.load(f)
print("total:", d.get("total"))
for i, r in enumerate(d.get("results", [])[:3]):
    print(f"  [{i}] sources={r.get('retrieval_sources')} char={r.get('char_start')}-{r.get('char_end')} score={r.get('score')}")
PYEOF
