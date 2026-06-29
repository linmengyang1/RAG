#!/bin/bash
# 测试检索 + 问答 API（AUTH_DISABLED=true，无需 token）
# 用 -G --data-urlencode 编码中文，避免 "Invalid HTTP request received"
set +e
BASE=http://localhost:18000

echo "========== 1. search 测试（导师）=========="
curl -s -G "$BASE/api/v1/search" --data-urlencode "q=导师" --data-urlencode "top_k=3" 2>&1
echo ""

echo ""
echo "========== 2. search 测试（教学成果奖）=========="
curl -s -G "$BASE/api/v1/search" --data-urlencode "q=教学成果奖" --data-urlencode "top_k=3" 2>&1
echo ""

echo ""
echo "========== 3. search 带 category 过滤（导师信息）=========="
curl -s -G "$BASE/api/v1/search" --data-urlencode "q=教授" --data-urlencode "top_k=3" --data-urlencode "category=导师信息" 2>&1
echo ""

echo ""
echo "========== 4. chat 测试（RAG 问答，会调 DeepSeek）=========="
curl -s -X POST "$BASE/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"question":"导师信息怎么查","top_k":3}' 2>&1
echo ""
