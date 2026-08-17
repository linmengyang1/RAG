"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import SearchPanel from "@/components/SearchPanel";
import ChatPanel from "@/components/ChatPanel";
import WikiPanel from "@/components/WikiPanel";
import { useAuth } from "@/lib/auth-context";

type Tab = "chat" | "search" | "wiki";

// Tab 配置：问答放首位（RAG 核心：检索+生成融合）
const TABS: { id: Tab; label: string; icon: string; desc: string }[] = [
  {
    id: "chat",
    label: "问答",
    icon: "M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 3v-3z",
    desc: "多轮对话 + 意图识别 + 代词消解 + 检索增强生成（内含向量+关键词双路 RRF 融合 + rerank）",
  },
  {
    id: "search",
    label: "检索",
    icon: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
    desc: "纯检索调试工具：向量+关键词 双路 RRF 融合 + rerank（不调 LLM，用于验证召回效果）",
  },
  {
    id: "wiki",
    label: "Wiki",
    icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
    desc: "LLM 沉淀的人物/政策/流程条目，支持检索",
  },
];

function HomeContent() {
  const router = useRouter();
  const { user, loading, logout } = useAuth();
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as Tab) || "chat";
  const [tab, setTab] = useState<Tab>(initialTab);

  // 路由守卫：未登录跳 /login
  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  // 加载中或未登录时显示加载态（避免未登录内容闪烁）
  if (loading || !user) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-500 text-sm">加载中...</div>
      </div>
    );
  }

  // 切换 tab 时同步到 URL
  function handleTabChange(tabId: Tab) {
    setTab(tabId);
    router.push(`/?tab=${tabId}`, { scroll: false });
  }

  return (
    <div className="min-h-screen">
      {/* 顶部标题栏 */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20 shadow-sticky">
        <div className="max-w-5xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {/* Logo 图标 */}
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-brand-600 to-accent-600 flex items-center justify-center shadow-sm">
                <svg
                  className="w-5 h-5 text-white"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-base font-bold text-slate-800 tracking-tight">
                  研究生院 RAG 知识库
                </h1>
                <p className="text-xs text-slate-500">
                  Graduate RAG · 检索 / 问答 / Wiki 一体化
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {/* 用户信息 */}
              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-700">{user.username}</span>
                {user.role === "admin" && (
                  <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 text-xs rounded">
                    管理员
                  </span>
                )}
              </div>
              {/* 登出 */}
              <button
                onClick={() => {
                  logout();
                  router.push("/login");
                }}
                className="text-sm text-slate-500 hover:text-red-600 transition-colors"
              >
                登出
              </button>
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
                onClick={() => handleTabChange(t.id)}
                className={`px-4 py-3 text-sm border-b-2 transition-all flex items-center gap-2 ${
                  tab === t.id
                    ? "border-brand-600 text-brand-700 font-medium"
                    : "border-transparent text-slate-600 hover:text-slate-800 hover:bg-slate-50"
                }`}
              >
                <svg
                  className={`w-4 h-4 ${tab === t.id ? "text-brand-600" : "text-slate-400"}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d={t.icon}
                  />
                </svg>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* Tab 描述条 */}
      <div className="bg-gradient-to-r from-brand-50 to-accent-50 border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-2 text-xs text-slate-600">
          <span className="text-slate-400">当前模式：</span>
          {TABS.find((t) => t.id === tab)?.desc}
        </div>
      </div>

      {/* 主内容 */}
      <main className={`${tab === "wiki" ? "max-w-7xl" : "max-w-5xl"} mx-auto px-4 py-5`}>
        <div key={tab} className="animate-fade-in">
          {tab === "chat" && <ChatPanel />}
          {tab === "search" && <SearchPanel />}
          {tab === "wiki" && <WikiPanel />}
        </div>
      </main>

      {/* 底部 */}
      <footer className="border-t border-slate-200 bg-white mt-8">
        <div className="max-w-5xl mx-auto px-4 py-3 text-xs text-slate-400 text-center">
          Graduate RAG · BGE-M3 + bge-reranker-v2-m3 + DeepSeek v4
        </div>
      </footer>
    </div>
  );
}

// 用 Suspense 包裹，因为 useSearchParams 需要
export default function Home() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50 flex items-center justify-center"><div className="text-slate-500 text-sm">加载中...</div></div>}>
      <HomeContent />
    </Suspense>
  );
}
