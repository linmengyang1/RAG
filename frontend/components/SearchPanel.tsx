"use client";

import { useState } from "react";
import ResultCard from "./ResultCard";
import { searchApi, type SearchResultItem } from "@/lib/api";

export default function SearchPanel() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [enableRerank, setEnableRerank] = useState(true);
  const [enableWiki, setEnableWiki] = useState(false);
  const [category, setCategory] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searchedQuery, setSearchedQuery] = useState("");

  async function handleSearch() {
    if (!query.trim()) {
      setError("请输入查询文本");
      return;
    }
    setLoading(true);
    setError("");
    setResults([]);
    setSearchedQuery(query);
    try {
      const resp = await searchApi({
        q: query,
        top_k: topK,
        category: category || undefined,
        enable_rerank: enableRerank,
        enable_wiki: enableWiki,
      });
      setResults(resp.results);
      if (resp.results.length === 0) {
        setError("未检索到相关资料");
      }
    } catch (e: any) {
      setError(e.message || "检索失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* 查询输入区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            查询文本
          </label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：导师信息怎么查？"
            className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            rows={2}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                handleSearch();
              }
            }}
          />
        </div>

        {/* 参数控制区 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* top_k */}
          <div>
            <label className="block text-xs text-slate-600 mb-1">
              返回数量 (top_k)：{topK}
            </label>
            <input
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-full"
            />
          </div>

          {/* category */}
          <div>
            <label className="block text-xs text-slate-600 mb-1">
              分类过滤（可选）
            </label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="如：导师信息"
              className="w-full px-2 py-1 text-sm border border-slate-300 rounded"
            />
          </div>

          {/* rerank 开关 */}
          <div className="flex items-end">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableRerank}
                onChange={(e) => setEnableRerank(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm text-slate-700">启用 rerank 重排</span>
            </label>
          </div>

          {/* wiki 开关 */}
          <div className="flex items-end">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableWiki}
                onChange={(e) => setEnableWiki(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm text-slate-700">
                附带 wiki 沉淀条目
              </span>
            </label>
          </div>
        </div>

        {/* 搜索按钮 */}
        <div className="flex justify-between items-center">
          <div className="text-xs text-slate-500">
            检索方式：向量检索(dense) + 关键词检索(sparse) 双路 RRF 融合
            {enableWiki ? " + wiki 沉淀路" : ""}
          </div>
          <button
            onClick={handleSearch}
            disabled={loading}
            className="px-4 py-2 bg-brand-600 text-white rounded text-sm hover:bg-brand-700 disabled:bg-slate-400"
          >
            {loading ? "检索中..." : "检索"}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded text-sm">
          {error}
        </div>
      )}

      {/* 结果区 */}
      {results.length > 0 && (
        <div className="space-y-3">
          <div className="text-sm text-slate-600">
            查询「{searchedQuery}」共返回 {results.length} 条结果
          </div>
          {results.map((item, idx) => (
            <ResultCard key={`${item.id}-${idx}`} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
