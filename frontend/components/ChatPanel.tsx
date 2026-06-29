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
      <div className="bg-white rounded-lg border border-slate-200 p-3 flex items-center justify-between">
        <div className="text-sm text-slate-600">
          当前会话 ID：
          <span className="font-mono ml-1 text-brand-700">
            {conversationId ?? "（新会话）"}
          </span>
          <span className="text-xs text-slate-400 ml-2">
            （多轮对话测试：第 1 轮建立会话，后续轮次自动消解代词）
          </span>
        </div>
        <button
          onClick={handleNewConversation}
          className="px-3 py-1 text-xs bg-slate-100 hover:bg-slate-200 rounded text-slate-700"
        >
          新建会话
        </button>
      </div>

      {/* 参数区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-3 space-y-2">
        <label className="text-xs text-slate-600">
          返回片段数 (top_k)：{topK}
        </label>
        <input
          type="range"
          min={1}
          max={20}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="w-full"
        />
        <div className="flex gap-4 pt-1">
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={enableRerank}
              onChange={(e) => setEnableRerank(e.target.checked)}
              className="rounded"
            />
            启用 rerank 精排（需 reranker 模型就绪）
          </label>
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={enableWiki}
              onChange={(e) => setEnableWiki(e.target.checked)}
              className="rounded"
            />
            启用 Wiki 检索
          </label>
        </div>
      </div>

      {/* 对话区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 min-h-[300px]">
        {messages.length === 0 ? (
          <div className="text-center text-slate-400 text-sm py-8">
            开始一段对话吧。例如：导师信息怎么查？
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-lg p-3 ${
                    msg.role === "user"
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {/* 角色标签 */}
                  <div className="text-xs opacity-70 mb-1">
                    {msg.role === "user" ? "用户" : "助手"}
                    {msg.intent && (
                      <span className="ml-2 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                        意图：{msg.intent}
                      </span>
                    )}
                  </div>

                  {/* 改写后的问题（如果有） */}
                  {msg.rewritten_query && msg.rewritten_query !== msg.content && (
                    <div className="text-xs opacity-80 mb-1 italic">
                      改写后：{msg.rewritten_query}
                    </div>
                  )}

                  {/* 内容 */}
                  <div className="whitespace-pre-wrap break-words text-sm">
                    {msg.content}
                  </div>

                  {/* 引用来源 */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3 space-y-2 border-t border-slate-200 pt-2">
                      <div className="text-xs opacity-70">
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
              <div className="flex justify-start">
                <div className="bg-slate-100 rounded-lg p-3 text-sm text-slate-500">
                  助手思考中...
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded text-sm">
          {error}
        </div>
      )}

      {/* 输入区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-3 flex gap-2">
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
          className="flex-1 px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-brand-600 text-white rounded text-sm hover:bg-brand-700 disabled:bg-slate-400"
        >
          发送
        </button>
      </div>
    </div>
  );
}
