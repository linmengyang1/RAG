"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  listWikiApi,
  listWikiCollegesApi,
  searchWikiApi,
  type CollegeStat,
  type WikiItem,
  type WikiSearchResultItem,
} from "@/lib/api";

// 一级分类配置
const ENTRY_TYPES = [
  { value: "", label: "全部", icon: "M4 6h16M4 12h16M4 18h16" },
  { value: "person", label: "人物", icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" },
  { value: "policy", label: "政策", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { value: "process", label: "流程", icon: "M13 10V3L4 14h7v7l9-11h-7z" },
];

// 类型徽章配色
const TYPE_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  person: { bg: "bg-purple-100", text: "text-purple-700", label: "人物" },
  policy: { bg: "bg-blue-100", text: "text-blue-700", label: "政策" },
  process: { bg: "bg-emerald-100", text: "text-emerald-700", label: "流程" },
};

function getBadge(entryType: string) {
  return TYPE_BADGE[entryType] || { bg: "bg-slate-100", text: "text-slate-700", label: entryType };
}

export default function WikiPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // 从 URL 恢复搜索词
  const urlSearch = searchParams.get("wikiSearch") || "";

  // 模式：list（列表浏览）/ search（检索结果）
  const [mode, setMode] = useState<"list" | "search">("list");

  // 列表状态
  const [entryType, setEntryType] = useState("");
  const [college, setCollege] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<WikiItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");

  // 学院列表（左侧导航用）
  const [colleges, setColleges] = useState<CollegeStat[]>([]);

  // 检索状态
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<WikiSearchResultItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");

  // 加载学院列表（根据 entryType 过滤）
  useEffect(() => {
    listWikiCollegesApi(entryType || undefined)
      .then(setColleges)
      .catch(() => setColleges([]));
  }, [entryType]);

  // 从 URL 恢复搜索：挂载时如果有 wikiSearch 参数则自动发起搜索
  useEffect(() => {
    if (urlSearch && urlSearch.trim()) {
      setQuery(urlSearch);
      // 需要等 query 更新后再搜索
      doSearch(urlSearch);
    }
  }, []); // 仅在挂载时执行一次

  // 加载条目列表
  async function loadList() {
    setListLoading(true);
    setListError("");
    try {
      const resp = await listWikiApi(
        entryType || undefined,
        page,
        20,
        college || undefined
      );
      setItems(resp.items);
      setTotal(resp.total);
    } catch (e: any) {
      setListError(e.message);
    } finally {
      setListLoading(false);
    }
  }

  useEffect(() => {
    if (mode === "list") {
      loadList();
    }
  }, [entryType, college, page, mode]);

  // 切换一级分类
  function handleEntryTypeChange(value: string) {
    setEntryType(value);
    setCollege(""); // 切换分类时清空学院
    setPage(1);
    setMode("list");
  }

  // 切换学院
  function handleCollegeChange(value: string) {
    setCollege(value);
    setPage(1);
    setMode("list");
  }

  // 执行搜索（不含 URL 更新，供挂载恢复用）
  async function doSearch(q: string) {
    if (!q.trim()) {
      setSearchError("请输入查询文本");
      return;
    }
    setSearchLoading(true);
    setSearchError("");
    setSearchResults([]);
    setMode("search");
    try {
      const resp = await searchWikiApi(q, 10);
      setSearchResults(resp.results);
      if (resp.results.length === 0) {
        setSearchError("未检索到 wiki 条目");
      }
    } catch (e: any) {
      setSearchError(e.message);
    } finally {
      setSearchLoading(false);
    }
  }

  // 检索
  async function handleSearch() {
    if (!query.trim()) {
      setSearchError("请输入查询文本");
      return;
    }
    // 同步搜索词到 URL，用 replace 避免多余历史记录
    router.replace(`/?tab=wiki&wikiSearch=${encodeURIComponent(query)}`, { scroll: false });
    await doSearch(query);
  }

  // 跳转详情页
  function goToDetail(id: number) {
    router.push(`/wiki/${id}`);
  }

  return (
    <div className="space-y-4">
      {/* 搜索栏（紫色渐变） */}
      <div className="bg-gradient-to-r from-purple-600 to-indigo-600 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-3">
          {/* 搜索框 */}
          <div className="flex-1 relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="搜索 Wiki 条目（导师姓名 / 政策 / 流程）..."
              className="w-full pl-11 pr-4 py-3 bg-white border-0 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-white/50 placeholder:text-slate-400"
            />
          </div>
        </div>
      </div>

      {/* 主体：左侧导航 + 右侧内容 */}
      <div className="flex gap-4">
        {/* 左侧分类导航 */}
        <aside className="w-56 flex-shrink-0">
          <nav className="bg-white rounded-lg border border-slate-200 p-3 sticky top-4">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-2">
              分类导航
            </div>
            {/* 一级分类 */}
            <div className="space-y-0.5">
              {ENTRY_TYPES.map((t) => {
                const active = entryType === t.value;
                return (
                  <button
                    key={t.value}
                    onClick={() => handleEntryTypeChange(t.value)}
                    className={`w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-all ${
                      active
                        ? "bg-purple-50 text-purple-700 font-medium border-l-4 border-purple-600 pl-2"
                        : "text-slate-600 hover:bg-slate-50 border-l-4 border-transparent pl-2"
                    }`}
                  >
                    <svg
                      className={`w-4 h-4 ${active ? "text-purple-600" : "text-slate-400"}`}
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
                );
              })}
            </div>

            {/* 二级学院列表（仅 person 类型显示） */}
            {entryType === "person" && colleges.length > 0 && (
              <div className="mt-4 pt-3 border-t border-slate-100">
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-2">
                  按学院
                </div>
                <div className="space-y-0.5 max-h-72 overflow-y-auto">
                  {/* 全部学院（清除学院过滤） */}
                  <button
                    onClick={() => handleCollegeChange("")}
                    className={`w-full flex items-center justify-between px-3 py-1.5 rounded-md text-xs transition-all ${
                      !college
                        ? "bg-indigo-50 text-indigo-700 font-medium"
                        : "text-slate-500 hover:bg-slate-50"
                    }`}
                  >
                    <span>全部学院</span>
                  </button>
                  {colleges.map((c) => {
                    const active = college === c.college;
                    return (
                      <button
                        key={c.college}
                        onClick={() => handleCollegeChange(c.college)}
                        className={`w-full flex items-center justify-between px-3 py-1.5 rounded-md text-xs transition-all ${
                          active
                            ? "bg-indigo-50 text-indigo-700 font-medium"
                            : "text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        <span className="truncate text-left">{c.college}</span>
                        <span className="ml-2 flex-shrink-0 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-slate-100 text-slate-500 text-[10px]">
                          {c.count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </nav>
        </aside>

        {/* 右侧内容区 */}
        <div className="flex-1 min-w-0">
          {/* 列表模式 */}
          {mode === "list" && (
            <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
              {/* 头部：当前过滤条件 + 总数 */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-slate-500">当前：</span>
                  {entryType ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded bg-purple-100 text-purple-700 text-xs font-medium">
                      {ENTRY_TYPES.find((t) => t.value === entryType)?.label}
                    </span>
                  ) : (
                    <span className="text-slate-400 text-xs">全部</span>
                  )}
                  {college && (
                    <>
                      <span className="text-slate-300">/</span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 text-xs font-medium">
                        {college}
                      </span>
                    </>
                  )}
                </div>
                <span className="text-xs text-slate-500">共 {total} 条</span>
              </div>

              {/* 加载态 */}
              {listLoading && (
                <div className="text-sm text-slate-500 text-center py-8">
                  加载中...
                </div>
              )}

              {/* 错误态 */}
              {listError && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
                  {listError}
                </div>
              )}

              {/* 空态 */}
              {!listLoading && items.length === 0 && !listError && (
                <div className="text-center text-slate-400 text-sm py-12">
                  暂无 wiki 条目
                </div>
              )}

              {/* 条目卡片流 */}
              {items.length > 0 && (
                <div className="space-y-3">
                  {items.map((item) => {
                    const badge = getBadge(item.entry_type);
                    return (
                      <div
                        key={item.id}
                        onClick={() => goToDetail(item.id)}
                        className="group border border-slate-200 rounded-lg p-4 hover:shadow-md hover:border-purple-200 hover:-translate-y-0.5 transition-all cursor-pointer bg-white"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            {/* 标题 */}
                            <div className="flex items-center gap-2 mb-1.5">
                              <h3 className="font-semibold text-slate-800 group-hover:text-purple-700 transition-colors">
                                {item.title}
                              </h3>
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium ${badge.bg} ${badge.text}`}
                              >
                                {badge.label}
                              </span>
                            </div>
                            {/* 元数据 */}
                            <div className="flex items-center gap-3 text-xs text-slate-400 mb-2">
                              {item.college && (
                                <span className="flex items-center gap-1">
                                  <svg
                                    className="w-3 h-3"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                  >
                                    <path
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      strokeWidth={2}
                                      d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
                                    />
                                  </svg>
                                  {item.college}
                                </span>
                              )}
                              {item.subject && (
                                <span>{item.subject}</span>
                              )}
                              <span>引用 {item.mention_count} 次</span>
                              <span>v{item.version}</span>
                            </div>
                            {/* 摘要 */}
                            {item.content_summary && (
                              <p className="text-sm text-slate-600 line-clamp-2 leading-relaxed">
                                {item.content_summary}
                              </p>
                            )}
                          </div>
                          {/* 右侧箭头 */}
                          <svg
                            className="w-5 h-5 text-slate-300 group-hover:text-purple-400 transition-colors flex-shrink-0 mt-1"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M9 5l7 7-7 7"
                            />
                          </svg>
                        </div>
                      </div>
                    );
                  })}

                  {/* 分页 */}
                  <div className="flex justify-between items-center pt-3">
                    <button
                      onClick={() => setPage(Math.max(1, page - 1))}
                      disabled={page === 1}
                      className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      上一页
                    </button>
                    <span className="text-sm text-slate-600">
                      第 {page} 页 / 共 {Math.ceil(total / 20) || 1} 页
                    </span>
                    <button
                      onClick={() => setPage(page + 1)}
                      disabled={items.length < 20}
                      className="px-3 py-1.5 text-sm border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 检索模式 */}
          {mode === "search" && (
            <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
              {/* 检索头部 */}
              <div className="flex items-center justify-between">
                <div className="text-sm text-slate-600">
                  {searchLoading ? (
                    "检索中..."
                  ) : (
                    <>
                      共 {searchResults.length} 条 wiki 结果
                      <span className="ml-2 text-xs text-slate-400">
                        关键词：{query}
                      </span>
                    </>
                  )}
                </div>
                <button
                  onClick={() => {
                    setMode("list");
                    setQuery("");
                    setSearchResults([]);
                    setSearchError("");
                    // 清除 URL 中的搜索参数
                    router.replace("/?tab=wiki", { scroll: false });
                  }}
                  className="px-3 py-1 text-xs text-slate-500 hover:text-slate-700 border border-slate-200 rounded hover:bg-slate-50 transition-colors"
                >
                  返回列表
                </button>
              </div>

              {/* 错误态 */}
              {searchError && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
                  {searchError}
                </div>
              )}

              {/* 检索结果卡片 */}
              {searchResults.length > 0 && (
                <div className="space-y-3">
                  {searchResults.map((item, idx) => {
                    const badge = getBadge(item.entry_type);
                    return (
                      <div
                        key={`${item.id}-${idx}`}
                        onClick={() => goToDetail(item.id)}
                        className="group border border-slate-200 rounded-lg p-4 hover:shadow-md hover:border-purple-200 hover:-translate-y-0.5 transition-all cursor-pointer bg-white"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            {/* 标题 + 相似度 */}
                            <div className="flex items-center gap-2 mb-1.5">
                              <h3 className="font-semibold text-slate-800 group-hover:text-purple-700 transition-colors">
                                {item.title}
                              </h3>
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium ${badge.bg} ${badge.text}`}
                              >
                                {badge.label}
                              </span>
                              <span className="text-[10px] text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded">
                                相似度 {item.score.toFixed(4)}
                              </span>
                            </div>
                            {/* 元数据 */}
                            <div className="flex items-center gap-3 text-xs text-slate-400 mb-2">
                              {item.college && (
                                <span>{item.college}</span>
                              )}
                              {item.subject && (
                                <span>{item.subject}</span>
                              )}
                              <span className="text-[10px]">
                                来源：{item.retrieval_sources.join("、")}
                              </span>
                            </div>
                            {/* 摘要 */}
                            {item.summary && (
                              <p className="text-sm text-slate-600 line-clamp-2 leading-relaxed">
                                {item.summary}
                              </p>
                            )}
                          </div>
                          <svg
                            className="w-5 h-5 text-slate-300 group-hover:text-purple-400 transition-colors flex-shrink-0 mt-1"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M9 5l7 7-7 7"
                            />
                          </svg>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
