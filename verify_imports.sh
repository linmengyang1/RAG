#!/bin/bash
# 验证所有新模块 import 无误
docker exec grad-rag-backend python -c '
from app.services.retrieval.reranker import rerank
from app.services.retrieval.hybrid_search import hybrid_search
from app.services.wiki.generator import generate_wiki_entries
from app.services.wiki.searcher import search_wiki
from app.services.llm.intent_recognition import recognize_intent
from app.services.llm.prompt_builder import build_rag_prompt
from app.api.v1.wiki import router
from app.api.v1.chat import chat
from app.api.v1.search import search
from app.api.v1 import api_router
print("all imports OK")
'
