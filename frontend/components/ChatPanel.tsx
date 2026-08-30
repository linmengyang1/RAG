"use client";

import { useState, useEffect, useCallback } from "react";
import ResultCard from "./ResultCard";
import {
  chatStreamApi,
  listConversationsApi,
  getConversationApi,
  deleteConversationApi,
  type ChatSource,
  type ConversationItem,
} from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  rewritten_query?: string;
  intent?: string;
  sources?: ChatSource[];
  conversation_id?: number;
  // 流式思考阶段：intent / intent_done / retrieving / retrieved / generating / done / error
  stage?: string;
  // 检索子阶段：embedding / dense / sparse / rerank（仅 stage="retrieving" 时有效）
  retrieveStage?: string;
  // 各阶段精确耗时（ms），由后端提供；done 后为后端整体下发的完整数据
  stageTimes?: Record<string, number>;
  // 请求开始的时间戳（performance.now()），用于实时计时显示
  startTime?: number;
}

// 阶段提示文本
function stageText(stage?: string): string {
  switch (stage) {
    case "intent":
      return "意图识别中...";
    case "retrieving":
      return "检索中（向量 + 关键词双路 RRF + rerank）...";
    case "retrieved":
      return "检索完成，准备生成...";
    case "generating":
      return "生成中...";
    default:
      return "";
  }
}

// 检索子阶段提示文本（stage="retrieving" 时根据 retrieveStage 显示更细的进度）
function retrieveStageText(stage?: string): string {
  switch (stage) {
    case "embedding":
      return "向量化查询中（BGE-M3 编码 query）...";
    case "dense":
      return "向量检索中（dense HNSW + COSINE）...";
    case "sparse":
      return "关键词检索中（sparse BM25）...";
    case "rerank":
      return "rerank 精排中（bge-reranker-v2-m3）...";
    default:
      return "检索中（向量 + 关键词双路 RRF + rerank）...";
  }
}

// 检索子阶段固定展示顺序
const RETRIEVE_STAGES: { key: string; label: string }[] = [
  { key: "retrieve_embedding", label: "查询向量化" },
  { key: "retrieve_dense", label: "向量检索" },
  { key: "retrieve_sparse", label: "关键词检索" },
  { key: "retrieve_rerank", label: "rerank 精排" },
];

// 耗时格式化：毫秒转秒，保留 1 位小数
function fmtSec(ms?: number): string {
  if (ms === undefined) return "-";
  return `${(ms / 1000).toFixed(1)}s`;
}

// 可折叠引用来源：默认收起，点击展开完整 ResultCard 列表
function SourcesSection({ sources }: { sources: ChatSource[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 pt-2 border-t border-slate-200/70">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between text-xs text-slate-500 hover:text-slate-700 transition-colors py-1 group"
      >
        <span className="flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          引用来源（{sources.length} 条）
          <span className="text-slate-400 group-hover:text-slate-600">
            {open ? "点击收起" : "点击展开"}
          </span>
        </span>
        <svg
          className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="mt-2 space-y-2 animate-fade-in">
          {sources.map((src, sIdx) => (
            <ResultCard
              key={sIdx}
              item={{
                id: sIdx,
                text: src.text,
                doc_id: src.doc_id,
                category: src.category,
                college: src.college,
                subject: src.subject,
                source_url: src.source_url,
                score: src.score,
                retrieval_sources: src.retrieval_sources,
                rerank_score: src.rerank_score,
                page_num: src.page_num,
                char_start: src.char_start,
                char_end: src.char_end,
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel() {
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(5);
  const [enableRerank, setEnableRerank] = useState(false);
  const [enableWiki, setEnableWiki] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);

  // 会话列表
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [showSidebar, setShowSidebar] = useState(true);

  // 加载会话列表
  const loadConversations = useCallback(async () => {
    try {
      const resp = await listConversationsApi(1, 30);
      setConversations(resp.items);
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // loading 期间每 100ms 触发重渲染，让思考阶段的实时耗时持续更新
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => setTick((t) => t + 1), 100);
    return () => clearInterval(timer);
  }, [loading]);

  async function handleSend() {
    if (!input.trim()) return;
    const userMsg: ChatMessage = { role: "user", content: input };
    // 占位 assistant message，流式回调会逐步更新它
    const assistantIdx = messages.length + 1;
    // 记录请求开始时间，用于实时计时（直到后端首个事件到达）
    const startTime = performance.now();
    setMessages((prev) => [
      ...prev,
      userMsg,
      { role: "assistant", content: "", stage: "intent", startTime },
    ]);
    setLoading(true);
    setError("");

    const currentInput = input;
    setInput("");

    try {
      await chatStreamApi(
        {
          question: currentInput,
          top_k: topK,
          conversation_id: conversationId ?? undefined,
          enable_rerank: enableRerank,
          enable_wiki: enableWiki,
        },
        {
          onIntent: (intent, rewrittenQuery, elapsedMs) => {
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                intent,
                rewritten_query: rewrittenQuery,
                stage: "intent_done",
                stageTimes: {
                  ...(next[assistantIdx].stageTimes || {}),
                  intent: elapsedMs,
                },
              };
              return next;
            });
          },
          onRetrieving: (elapsedMs) => {
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                stage: "retrieving",
                stageTimes: {
                  ...(next[assistantIdx].stageTimes || {}),
                  retrieving: elapsedMs,
                },
              };
              return next;
            });
          },
          onRetrievingStage: (stage, durationMs) => {
            // 检索子阶段完成：后端已精确计时该阶段耗时（embedding / dense / sparse / rerank）
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                retrieveStage: stage,
                stageTimes: {
                  ...(next[assistantIdx].stageTimes || {}),
                  [`retrieve_${stage}`]: durationMs,
                },
              };
              return next;
            });
          },
          onRetrieved: (count, elapsedMs) => {
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                stage: "retrieved",
                stageTimes: {
                  ...(next[assistantIdx].stageTimes || {}),
                  retrieved: elapsedMs,
                },
              };
              return next;
            });
          },
          onGenerating: (elapsedMs) => {
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                stage: "generating",
                stageTimes: {
                  ...(next[assistantIdx].stageTimes || {}),
                  generating: elapsedMs,
                },
              };
              return next;
            });
          },
          onToken: (delta) => {
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                content: next[assistantIdx].content + delta,
              };
              return next;
            });
          },
          onDone: (data) => {
            setConversationId(data.conversation_id);
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                content: data.answer,
                intent: data.intent,
                rewritten_query: data.rewritten_query,
                sources: data.sources,
                conversation_id: data.conversation_id,
                stage: "done",
                // 后端整体下发各阶段精确耗时，前端不再自行减法计算
                stageTimes: {
                  ...(data.stage_times || {}),
                  done: data.elapsed_ms,
                },
              };
              return next;
            });
          },
          onError: (msg) => {
            setError(msg);
            setMessages((prev) => {
              const next = [...prev];
              next[assistantIdx] = {
                ...next[assistantIdx],
                content: `出错：${msg}`,
                stage: "error",
              };
              return next;
            });
          },
        }
      );
    } catch (e: any) {
      setError(e.message || "问答失败");
      setMessages((prev) => {
        const next = [...prev];
        next[assistantIdx] = {
          ...next[assistantIdx],
          content: `出错：${e.message || "问答失败"}`,
          stage: "error",
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  function handleNewConversation() {
    setMessages([]);
    setConversationId(null);
    setError("");
    setInput("");
  }

  // 切换到某个会话
  async function switchConversation(convId: number) {
    try {
      const detail = await getConversationApi(convId);
      const msgs: ChatMessage[] = detail.messages.map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));
      setMessages(msgs);
      setConversationId(convId);
      setError("");
    } catch (e: any) {
      setError(e.message || "加载会话失败");
    }
  }

  // 删除会话
  async function deleteConversation(convId: number) {
    try {
      await deleteConversationApi(convId);
      if (conversationId === convId) {
        setMessages([]);
        setConversationId(null);
      }
      loadConversations();
    } catch (e: any) {
      setError(e.message || "删除会话失败");
    }
  }

  return (
    <div className="flex gap-4">
      {/* 左侧会话列表 */}
      {showSidebar && (
        <aside className="w-56 flex-shrink-0">
          <div className="bg-white rounded-xl border border-slate-200/80 p-2.5 sticky top-28 max-h-[calc(100vh-8rem)] overflow-y-auto shadow-card">
            <div className="flex items-center justify-between mb-2 px-1">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                会话列表
              </span>
              <button
                onClick={() => setShowSidebar(false)}
                className="text-slate-300 hover:text-slate-500 transition-colors"
                title="收起侧栏"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {/* 新建会话 */}
            <button
              onClick={handleNewConversation}
              className="w-full text-left px-2.5 py-2 text-xs rounded-lg bg-brand-50 text-brand-700 hover:bg-brand-100 mb-1.5 flex items-center gap-1.5 font-medium transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              新建会话
            </button>
            {/* 会话列表 */}
            <div className="space-y-0.5">
              {conversations.map((conv) => (
                <div
                  key={conv.id}
                  className={`group flex items-center justify-between px-2.5 py-2 rounded-lg text-xs cursor-pointer transition-colors ${
                    conversationId === conv.id
                      ? "bg-brand-50 text-brand-700 font-medium"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <span
                    className="truncate flex-1"
                    onClick={() => switchConversation(conv.id)}
                    title={conv.title || `会话 #${conv.id}`}
                  >
                    {conv.title || `会话 #${conv.id}`}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm("确定删除该会话？")) deleteConversation(conv.id);
                    }}
                    className="ml-1 text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                    title="删除会话"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              ))}
              {conversations.length === 0 && (
                <div className="text-xs text-slate-400 px-2.5 py-2">暂无会话</div>
              )}
            </div>
          </div>
        </aside>
      )}

      {/* 主对话区域 */}
      <div className="flex-1 min-w-0 space-y-4">
        {/* 会话控制 + 参数设置（合并为一行卡片） */}
        <div className="bg-white rounded-xl border border-slate-200/80 px-4 py-3 shadow-card space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm text-slate-600 flex items-center gap-2">
              {!showSidebar && (
                <button
                  onClick={() => setShowSidebar(true)}
                  className="mr-1 text-slate-400 hover:text-slate-600 transition-colors"
                  title="展开侧栏"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                </button>
              )}
              <svg className="w-4 h-4 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span>当前会话</span>
              <span className="font-mono px-2 py-0.5 rounded-md bg-brand-50 text-brand-700 text-xs font-medium">
                {conversationId ? `#${conversationId}` : "新会话"}
              </span>
            </div>
            <button
              onClick={handleNewConversation}
              className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-700 transition-colors font-medium"
            >
              新建会话
            </button>
          </div>

          {/* 参数区：紧凑一行 */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pt-2.5 border-t border-slate-100">
            <label className="flex items-center gap-2 text-xs text-slate-600 min-w-[240px] flex-1">
              <span className="whitespace-nowrap">返回片段数</span>
              <input
                type="range"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="flex-1 accent-brand-600 h-1"
              />
              <span className="font-mono text-brand-700 font-semibold w-7 text-right">{topK}</span>
            </label>
            <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer hover:text-slate-800 transition-colors">
              <input
                type="checkbox"
                checked={enableRerank}
                onChange={(e) => setEnableRerank(e.target.checked)}
                className="w-3.5 h-3.5 accent-accent-600"
              />
              rerank 精排
            </label>
            <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer hover:text-slate-800 transition-colors">
              <input
                type="checkbox"
                checked={enableWiki}
                onChange={(e) => setEnableWiki(e.target.checked)}
                className="w-3.5 h-3.5 accent-purple-600"
              />
              Wiki 检索
            </label>
          </div>
        </div>

        {/* 对话区 */}
        <div className="min-h-[320px] space-y-4">
          {messages.length === 0 ? (
            <div className="bg-white rounded-xl border border-slate-200/80 shadow-card text-center py-16">
              <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-brand-500 to-accent-600 flex items-center justify-center shadow-card-hover">
                <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 3v-3z" />
                </svg>
              </div>
              <p className="text-slate-500 text-sm font-medium mb-1">开始一段对话吧</p>
              <p className="text-slate-400 text-xs">例如：导师信息怎么查？</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex animate-slide-up gap-2.5 ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {/* 助手头像 */}
                {msg.role === "assistant" && (
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-accent-600 flex items-center justify-center flex-shrink-0 shadow-sm mt-0.5">
                    <svg className="w-[18px] h-[18px] text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                  </div>
                )}

                <div className={`min-w-0 ${msg.role === "user" ? "max-w-[85%]" : "max-w-[92%] flex-1"}`}>
                  {msg.role === "user" ? (
                    /* 用户气泡：渐变蓝 */
                    <div className="rounded-2xl rounded-br-sm px-4 py-2.5 bg-gradient-to-br from-brand-600 to-brand-700 text-white shadow-card text-sm leading-relaxed whitespace-pre-wrap break-words">
                      {msg.content}
                    </div>
                  ) : (
                    /* 助手消息：白底卡片，含思考过程 / 内容 / 引用来源 */
                    <div className="bg-white rounded-2xl rounded-tl-sm border border-slate-200/80 shadow-card px-4 py-3">
                      {/* 改写后的问题 */}
                      {msg.rewritten_query && msg.rewritten_query !== msg.content && (
                        <div className="text-xs text-slate-500 mb-2 italic bg-slate-50 border border-slate-100 px-2.5 py-1.5 rounded-lg">
                          改写后：{msg.rewritten_query}
                        </div>
                      )}

                      {/* 思考阶段提示（流式进行中：已完成阶段精确耗时 + 当前阶段动画） */}
                      {msg.stage && msg.stage !== "done" && msg.stage !== "error" && (
                        <div className="text-xs text-slate-500 space-y-1 py-1">
                          {/* 已完成阶段（含各自精确耗时） */}
                          {msg.stageTimes?.intent !== undefined && (
                            <div className="flex items-center gap-1.5 text-emerald-600">
                              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                              意图识别 <span className="font-mono">{fmtSec(msg.stageTimes.intent)}</span>
                            </div>
                          )}
                          {RETRIEVE_STAGES.map(({ key, label }) =>
                            msg.stageTimes?.[key] !== undefined ? (
                              <div key={key} className="flex items-center gap-1.5 text-emerald-600">
                                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                                {label} <span className="font-mono">{fmtSec(msg.stageTimes[key])}</span>
                              </div>
                            ) : null
                          )}
                          {/* 当前进行中的阶段 */}
                          <div className="flex items-center gap-1.5 text-accent-600">
                            <span className="flex gap-1">
                              <span className="w-1.5 h-1.5 bg-accent-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                              <span className="w-1.5 h-1.5 bg-accent-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                              <span className="w-1.5 h-1.5 bg-accent-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                            </span>
                            {msg.stage === "retrieving" && msg.retrieveStage
                              ? retrieveStageText(msg.retrieveStage)
                              : stageText(msg.stage)}
                            {msg.startTime && (
                              <span className="text-slate-400 font-mono">
                                ({((performance.now() - msg.startTime) / 1000).toFixed(1)}s)
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* 内容（流式逐 token 追加） */}
                      {msg.content && (
                        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800">
                          {msg.content}
                          {msg.stage === "generating" && (
                            <span className="inline-block w-1.5 h-4 bg-accent-500 ml-0.5 animate-pulse align-middle rounded-sm" />
                          )}
                        </div>
                      )}

                      {/* 错误状态 */}
                      {msg.stage === "error" && (
                        <div className="text-sm text-red-600">{msg.content}</div>
                      )}

                      {/* 思考过程摘要（完成后显示，数据为后端下发的各阶段精确耗时） */}
                      {msg.stage === "done" && msg.stageTimes && (
                        <div className="mt-2 bg-gradient-to-r from-slate-50 to-brand-50/40 border border-slate-200/70 rounded-xl px-3.5 py-3">
                          <div className="text-xs text-slate-400 mb-2 flex items-center gap-1.5 font-medium">
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                            </svg>
                            思考过程
                          </div>
                          {/* 各阶段耗时（后端精确计时，直接展示） */}
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-slate-600">
                            {msg.stageTimes.intent !== undefined && (
                              <div className="flex justify-between gap-2">
                                <span>意图识别</span>
                                <span className="font-mono text-slate-800 tabular-nums">{fmtSec(msg.stageTimes.intent)}</span>
                              </div>
                            )}
                            {msg.stageTimes.stats !== undefined ? (
                              <div className="flex justify-between gap-2">
                                <span>统计聚合</span>
                                <span className="font-mono text-slate-800 tabular-nums">{fmtSec(msg.stageTimes.stats)}</span>
                              </div>
                            ) : msg.stageTimes.multi !== undefined ? (
                              <div className="flex justify-between gap-2">
                                <span>多问题拆解</span>
                                <span className="font-mono text-slate-800 tabular-nums">{fmtSec(msg.stageTimes.multi)}</span>
                              </div>
                            ) : (
                              <>
                                {RETRIEVE_STAGES.map(({ key, label }) =>
                                  msg.stageTimes?.[key] !== undefined ? (
                                    <div key={key} className="flex justify-between gap-2">
                                      <span>{label}</span>
                                      <span className="font-mono text-slate-800 tabular-nums">{fmtSec(msg.stageTimes[key])}</span>
                                    </div>
                                  ) : null
                                )}
                                {msg.stageTimes.llm !== undefined && (
                                  <div className="flex justify-between gap-2">
                                    <span>LLM 生成</span>
                                    <span className="font-mono text-slate-800 tabular-nums">{fmtSec(msg.stageTimes.llm)}</span>
                                  </div>
                                )}
                              </>
                            )}
                            {msg.stageTimes.done !== undefined && (
                              <div className="flex justify-between gap-2 font-semibold border-t border-slate-200/70 pt-1 -mt-0.5">
                                <span>总计</span>
                                <span className="font-mono text-brand-700 tabular-nums">{fmtSec(msg.stageTimes.done)}</span>
                              </div>
                            )}
                          </div>
                          {/* 工具/方法说明 */}
                          <div className="mt-2.5 pt-2 border-t border-slate-100 text-[10px] text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
                            {msg.intent && (
                              <span className="inline-flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                                意图：{msg.intent}
                              </span>
                            )}
                            {msg.conversation_id && (
                              <span className="inline-flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                                多轮对话
                              </span>
                            )}
                            {msg.stageTimes.stats === undefined && msg.stageTimes.multi === undefined && (
                              <span className="inline-flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                                BGE-M3 双路 (dense+sparse) RRF 融合
                              </span>
                            )}
                            {msg.sources && msg.sources.length > 0 && (
                              <span className="inline-flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                                检索命中 {msg.sources.length} 条
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* 引用来源（可折叠） */}
                      {msg.sources && msg.sources.length > 0 && (
                        <SourcesSection sources={msg.sources} />
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2.5 rounded-xl text-sm flex items-center gap-2">
            <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {error}
          </div>
        )}

        {/* 输入区 */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-3 shadow-card focus-within:ring-2 focus-within:ring-brand-500/30 focus-within:border-brand-400 transition-all">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={2}
              placeholder="输入问题（Enter 发送，Shift+Enter 换行）"
              className="flex-1 px-3 py-2 text-sm resize-none border-0 focus:outline-none bg-transparent placeholder:text-slate-400 leading-relaxed"
              disabled={loading}
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              className="px-4 py-2 bg-gradient-to-br from-brand-600 to-brand-700 text-white rounded-xl text-sm hover:from-brand-500 hover:to-brand-600 disabled:from-slate-300 disabled:to-slate-300 disabled:cursor-not-allowed transition-all shadow-sm flex items-center gap-1.5 flex-shrink-0"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
