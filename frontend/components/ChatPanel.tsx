"use client";

import { useState } from "react";
import ResultCard from "./ResultCard";
import { chatApi, type ChatSource } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  rewritten_query?: string;
  intent?: string;
  sources?: ChatSource[];
  conversation_id?: number;
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

  async function handleSend() {
    if (!input.trim()) return;
    const userMsg: ChatMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setError("");

    const currentInput = input;
    setInput("");

    try {
      const resp = await chatApi({
        question: currentInput,
        top_k: topK,
        conversation_id: conversationId ?? undefined,
        enable_rerank: enableRerank,
        enable_wiki: enableWiki,
      });
      setConversationId(resp.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: resp.answer,
          rewritten_query: resp.rewritten_query,
          intent: resp.intent,
          sources: resp.sources,
          conversation_id: resp.conversation_id,
        },
      ]);
    } catch (e: any) {
      setError(e.message || "问答失败");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `出错：${e.message || "问答失败"}`,
        },
      ]);
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

  return (
    <div className="space-y-4">
      {/* 会话控制 */}
      <div className="bg-white rounded-lg border border-slate-200 p-3 flex items-center justify-between shadow-card">
        <div className="text-sm text-slate-600 flex items-center gap-2">
          <svg className="w-4 h-4 text-brand-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          <span>当前会话 ID：</span>
          <span className="font-mono px-2 py-0.5 rounded bg-brand-50 text-brand-700 text-xs">
            {conversationId ?? "（新会话）"}
          </span>
          <span className="text-xs text-slate-400 ml-2 hidden sm:inline">
            （多轮对话：第 1 轮建立会话，后续轮次自动消解代词）
          </span>
        </div>
        <button
          onClick={handleNewConversation}
          className="px-3 py-1 text-xs bg-slate-100 hover:bg-slate-200 rounded text-slate-700 transition-colors flex items-center gap-1"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          新建会话
        </button>
      </div>

      {/* 参数区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-3 space-y-2 shadow-card">
        <div className="flex items-center justify-between">
          <label className="text-xs text-slate-600 flex items-center gap-2">
            <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
            </svg>
            返回片段数 (top_k)：<span className="font-mono text-brand-700 font-medium">{topK}</span>
          </label>
        </div>
        <input
          type="range"
          min={1}
          max={20}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="w-full accent-brand-600"
        />
        <div className="flex flex-wrap gap-4 pt-1">
          <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer hover:text-slate-800">
            <input
              type="checkbox"
              checked={enableRerank}
              onChange={(e) => setEnableRerank(e.target.checked)}
              className="w-3.5 h-3.5 accent-accent-600"
            />
            启用 rerank 精排（需 reranker 模型就绪）
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer hover:text-slate-800">
            <input
              type="checkbox"
              checked={enableWiki}
              onChange={(e) => setEnableWiki(e.target.checked)}
              className="w-3.5 h-3.5 accent-purple-600"
            />
            启用 Wiki 检索
          </label>
        </div>
      </div>

      {/* 对话区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 min-h-[300px] shadow-card">
        {messages.length === 0 ? (
          <div className="text-center text-slate-400 text-sm py-12">
            <svg className="w-10 h-10 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 3v-3z" />
            </svg>
            开始一段对话吧。例如：导师信息怎么查？
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex animate-slide-up ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl p-3.5 shadow-sm ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-brand-600 to-brand-700 text-white rounded-br-sm"
                      : "bg-slate-50 text-slate-800 border border-slate-200 rounded-bl-sm"
                  }`}
                >
                  {/* 角色标签 */}
                  <div className="text-xs opacity-70 mb-1.5 flex items-center gap-1">
                    {msg.role === "user" ? "用户" : "助手"}
                    {msg.intent && (
                      <span className="ml-1 px-1.5 py-0.5 rounded bg-accent-100 text-accent-700 text-[10px] font-medium">
                        意图：{msg.intent}
                      </span>
                    )}
                  </div>

                  {/* 改写后的问题（如果有） */}
                  {msg.rewritten_query && msg.rewritten_query !== msg.content && (
                    <div className="text-xs opacity-80 mb-1.5 italic bg-black/5 px-2 py-1 rounded">
                      改写后：{msg.rewritten_query}
                    </div>
                  )}

                  {/* 内容 */}
                  <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                    {msg.content}
                  </div>

                  {/* 引用来源 */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3 space-y-2 border-t border-slate-200/60 pt-2">
                      <div className="text-xs opacity-70 flex items-center gap-1">
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        引用来源（{msg.sources.length} 条）：
                      </div>
                      {msg.sources.map((src, sIdx) => (
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
              </div>
            ))}
            {loading && (
              <div className="flex justify-start animate-fade-in">
                <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-sm p-3.5 text-sm text-slate-500 flex items-center gap-2">
                  <span className="flex gap-1">
                    <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </span>
                  助手思考中...
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2.5 rounded-lg text-sm flex items-center gap-2">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      )}

      {/* 输入区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-2.5 flex gap-2 shadow-card">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="输入问题（回车发送，Shift+Enter 换行）"
          className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent transition-all"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 disabled:bg-slate-300 transition-colors flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
          发送
        </button>
      </div>
    </div>
  );
}
