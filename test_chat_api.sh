#!/bin/bash
# 测试 chat API（多轮对话 + 意图识别）
set -e
echo "=== 测试 chat API via frontend ==="
HTTP_CODE=$(curl -s -X POST http://localhost:3000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"导师信息怎么查询","top_k":3,"enable_rerank":false}' \
  --max-time 90 \
  -o /tmp/fe_chat.json \
  -w "%{http_code}")
echo "HTTP $HTTP_CODE"
echo ""
echo "=== 解析响应 ==="
python3 << 'PYEOF'
import json
with open("/tmp/fe_chat.json", "r", encoding="utf-8") as f:
    d = json.load(f)
print("question:", d.get("question"))
print("rewritten_query:", d.get("rewritten_query"))
print("intent:", d.get("intent"))
print("conversation_id:", d.get("conversation_id"))
ans = d.get("answer", "")
print("answer (前 150 字):", ans[:150])
sources = d.get("sources", [])
print("sources count:", len(sources))
for i, s in enumerate(sources[:3]):
    print(f"  [{i}] sources={s.get('retrieval_sources')} score={s.get('score')}")
PYEOF
echo ""
echo "=== backend 日志（chat 相关）==="
docker logs grad-rag-backend --tail 30 2>&1 | grep -iE "intent|chat|recognize|deepseek|error|exception" | tail -10
