#!/bin/bash
# 验证所有修复（v2）：health / search / chat / wiki generate / wiki list

set -u
BASE="http://localhost:18000"

echo "========================================"
echo "[1/5] backend health"
echo "========================================"
curl -s -o /tmp/health.json -w "HTTP %{http_code}\n" $BASE/health
cat /tmp/health.json; echo; echo

echo "========================================"
echo "[2/5] search GET (验证 char_start=0 不再被当 falsy)"
echo "========================================"
curl -s -G -o /tmp/search.json -w "HTTP %{http_code}\n" \
  "$BASE/api/v1/search" \
  --data-urlencode "q=导师" \
  --data-urlencode "top_k=3" \
  --data-urlencode "enable_rerank=false" \
  --data-urlencode "enable_wiki=false"
python3 -c "
import json
d=json.load(open('/tmp/search.json'))
items=d.get('results',[])
print(f'  total={d.get(\"total\")}, len={len(items)}')
if not items:
    print('  PAYLOAD:', json.dumps(d, ensure_ascii=False)[:400])
else:
    for i,it in enumerate(items[:3]):
        print(f'  [{i}] text={it.get(\"text\",\"\")[:35]!r}')
        print(f'      char_start={it.get(\"char_start\")!r}  char_end={it.get(\"char_end\")!r}  page_num={it.get(\"page_num\")!r}')
        print(f'      sources={it.get(\"retrieval_sources\")}  score={it.get(\"score\"):.4f}')
"
echo; echo

echo "========================================"
echo "[3/5] chat (enable_rerank=false)"
echo "========================================"
curl -s -o /tmp/chat.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"question":"导师信息怎么查？","top_k":3,"enable_rerank":false,"enable_wiki":false}'
python3 -c "
import json
d=json.load(open('/tmp/chat.json'))
print('  intent      =', d.get('intent'))
print('  rewritten   =', d.get('rewritten_query'))
print('  conv_id     =', d.get('conversation_id'))
print('  answer[:200]=', (d.get('answer') or '')[:200])
print('  sources#    =', len(d.get('sources',[])))
if d.get('detail'): print('  ERROR detail=', d.get('detail'))
"
echo; echo

echo "========================================"
echo "[4/5] wiki generate"
echo "========================================"
curl -s -o /tmp/wiki.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/api/v1/wiki/generate" \
  -H "Content-Type: application/json" \
  -d '{"limit":20}'
cat /tmp/wiki.json; echo; echo

echo "========================================"
echo "[5/5] wiki list"
echo "========================================"
curl -s -o /tmp/wikilist.json -w "HTTP %{http_code}\n" \
  "$BASE/api/v1/wiki?page=1&page_size=5"
python3 -c "
import json
d=json.load(open('/tmp/wikilist.json'))
print(f'  total={d.get(\"total\")}, items={len(d.get(\"items\",[]))}')
for it in d.get('items',[])[:3]:
    print(f'  - id={it.get(\"id\")} type={it.get(\"entry_type\")} title={it.get(\"title\")!r}')
if d.get('detail'): print('  ERROR detail=', d.get('detail'))
"
echo
echo "DONE"
