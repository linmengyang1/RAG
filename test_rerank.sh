#!/bin/bash
# 测试 reranker 是否能正常加载并返回 rerank_score
# 首次加载 2.2GB 模型可能需要 30-60 秒
set -u
BASE="http://localhost:18000"

echo "=== 测试 search with enable_rerank=true ==="
echo "  开始时间: $(date '+%H:%M:%S')"
echo "  首次加载 2.2GB 模型，请耐心等待 30-60 秒..."
echo

START=$(date +%s)
HTTP_CODE=$(curl -s -G -o /tmp/rerank_test.json -w "%{http_code}" \
  --max-time 180 \
  "$BASE/api/v1/search" \
  --data-urlencode "q=导师信息" \
  --data-urlencode "top_k=3" \
  --data-urlencode "enable_rerank=true" \
  --data-urlencode "enable_wiki=false")
END=$(date +%s)
COST=$((END - START))

echo "  HTTP 状态码: $HTTP_CODE"
echo "  耗时: ${COST}s"
echo

if [ "$HTTP_CODE" = "200" ]; then
    python3 -c "
import json
d=json.load(open('/tmp/rerank_test.json'))
items=d.get('results',[])
print(f'  total={d.get(\"total\")}, len={len(items)}')
for i,it in enumerate(items[:3]):
    rs = it.get('retrieval_sources', [])
    rs_str = '/'.join(rs) if rs else '-'
    rerank = it.get('rerank_score')
    rerank_str = f'{rerank:.4f}' if rerank is not None else 'None'
    print(f'  [{i}] score={it.get(\"score\"):.4f}  rerank_score={rerank_str}  sources=[{rs_str}]')
    print(f'      text={it.get(\"text\",\"\")[:40]!r}')
print()
print('  [OK] reranker 加载成功！rerank_score 已返回' if any(it.get('rerank_score') is not None for it in items) else '  [WARN] rerank_score 全为 None，reranker 可能未生效')
"
else
    echo "  [ERROR] HTTP $HTTP_CODE"
    cat /tmp/rerank_test.json | head -20
fi

echo
echo "=== backend 日志最近 20 行（看 reranker 加载日志）==="
docker logs grad-rag-backend --tail 20 2>&1 | tail -20
