"use client";

import { useState } from "react";
import SearchPanel from "@/components/SearchPanel";
import ChatPanel from "@/components/ChatPanel";
import WikiPanel from "@/components/WikiPanel";

type Tab = "search" | "chat" | "wiki";

const TABS: { id: Tab; label: string; desc: string }[] = [
  { id: "search", label: "检索", desc: "向量+关键词 双路 RRF 融合 + rerank" },
  { id: "chat", label: "问答", desc: "多轮对话 + 意图识别 + 代词消解" },
  { id: "wiki", label: "Wiki", desc: "LLM 沉淀的人物/政策/流程条目" },
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("search");

  return (
    <div className="min-h-screen">
      {/* 顶部标题栏 */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-bold text-slate-800">
                研究生院 RAG 知识库
              </h1>
              <p className="text-xs text-slate-500">
                Graduate RAG 检索 / 问答 / Wiki 一体化界面
              </p>
            </div>
            <div className="text-xs text-slate-400">
              API: localhost:18000
            </div>
          </div>
        </div>
      </header>

      {/* Tab 切换 */}
      <nav className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4">
          <div className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-4 py-3 text-sm border-b-2 transition-colors ${
                  tab === t.id
                    ? "border-brand-600 text-brand-700 font-medium"
                    : "border-transparent text-slate-600 hover:text-slate-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* Tab 描述 */}
      <div className="bg-slate-50 border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-2 text-xs text-slate-500">
          {TABS.find((t) => t.id === tab)?.desc}
        </div>
      </div>

      {/* 主内容 */}
      <main className="max-w-5xl mx-auto px-4 py-4">
        {tab === "search" && <SearchPanel />}
        {tab === "chat" && <ChatPanel />}
        {tab === "wiki" && <WikiPanel />}
      </main>

      {/* 底部 */}
      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-5xl mx-auto px-4 py-3 text-xs text-slate-400 text-center">
          Graduate RAG - BGE-M3 + bge-reranker-v2-m3 + DeepSeek v4
        </div>
      </footer>
    </div>
  );
}
