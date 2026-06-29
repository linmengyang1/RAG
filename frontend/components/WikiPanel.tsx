"use client";

import { useEffect, useState } from "react";
import ResultCard from "./ResultCard";
import {
  generateWikiApi,
  listWikiApi,
  searchWikiApi,
  type WikiItem,
  type WikiSearchResultItem,
} from "@/lib/api";

const ENTRY_TYPES = [
  { value: "", label: "全部" },
  { value: "person", label: "人物 (person)" },
  { value: "policy", label: "政策 (policy)" },
  { value: "process", label: "流程 (process)" },
];

export default function WikiPanel() {
  const [tab, setTab] = useState<"list" | "search">("list");

  // 列表状态
  const [entryType, setEntryType] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<WikiItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [selectedItem, setSelectedItem] = useState<WikiItem | null>(null);

  // 检索状态
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<WikiSearchResultItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");

  // 生成状态
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState("");

  // 加载列表
  async function loadList() {
    setListLoading(true);
    setListError("");
    try {
      const resp = await listWikiApi(entryType || undefined, page, 20);
      setItems(resp.items);
      setTotal(resp.total);
    } catch (e: any) {
      setListError(e.message);
    } finally {
      setListLoading(false);
    }
  }

  useEffect(() => {
    loadList();
  }, [entryType, page]);

  // 检索
  async function handleSearch() {
    if (!query.trim()) {
      setSearchError("请输入查询文本");
      return;
    }
    setSearchLoading(true);
    setSearchError("");
    setSearchResults([]);
    try {
      const resp = await searchWikiApi(query, 10);
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

  // 生成
  async function handleGenerate() {
    setGenerating(true);
    setGenResult("");
    try {
      const stats = await generateWikiApi(undefined, 50);
      setGenResult(
        `生成完成：新增 ${stats.generated} 条，跳过 ${stats.skipped} 条（已存在），失败 ${stats.errors} 批`
      );
      // 刷新列表
      loadList();
    } catch (e: any) {
      setGenResult(`生成失败：${e.message}`);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* 顶部操作区 */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
        <div className="flex justify-between items-center">
          <h2 className="text-base font-semibold text-slate-800">
            LLM Wiki 沉淀条目
          </h2>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-3 py-1.5 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:bg-slate-400"
          >
            {generating ? "生成中..." : "触发生成（admin）"}
          </button>
        </div>
        {genResult && (
          <div className="text-sm text-slate-700 bg-slate-50 px-3 py-2 rounded">
            {genResult}
          </div>
        )}
        <div className="text-xs text-slate-500">
          Wiki 条目通过 LLM 从摄入的 chunks 中自动提取（人物 / 政策 / 流程三类），
          沉淀到 PG + Milvus wiki 集合供检索使用。
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-2">
        <button
          onClick={() => setTab("list")}
          className={`px-3 py-1.5 text-sm rounded ${
            tab === "list"
              ? "bg-brand-600 text-white"
              : "bg-white border border-slate-200 text-slate-700"
          }`}
        >
          条目列表
        </button>
        <button
          onClick={() => setTab("search")}
          className={`px-3 py-1.5 text-sm rounded ${
            tab === "search"
              ? "bg-brand-600 text-white"
              : "bg-white border border-slate-200 text-slate-700"
          }`}
        >
          检索
        </button>
      </div>

      {/* 列表 Tab */}
      {tab === "list" && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <div className="flex gap-2 items-center">
            <label className="text-sm text-slate-600">类型过滤：</label>
            <select
              value={entryType}
              onChange={(e) => {
                setEntryType(e.target.value);
                setPage(1);
              }}
              className="text-sm border border-slate-300 rounded px-2 py-1"
            >
              {ENTRY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <span className="text-xs text-slate-500 ml-auto">
              共 {total} 条
            </span>
          </div>

          {listLoading && (
            <div className="text-sm text-slate-500 text-center py-4">
              加载中...
            </div>
          )}
          {listError && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
              {listError}
            </div>
          )}

          {!listLoading && items.length === 0 && !listError && (
            <div className="text-center text-slate-400 text-sm py-8">
              暂无 wiki 条目，请先点击「触发生成」
            </div>
          )}

          {/* 列表 */}
          {items.length > 0 && (
            <div className="space-y-2">
              {items.map((item) => (
                <div
                  key={item.id}
                  onClick={() => setSelectedItem(item)}
                  className="border border-slate-200 rounded p-3 hover:bg-slate-50 cursor-pointer"
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="font-medium text-slate-800">
                        {item.title}
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        类型：
                        <span className="ml-1 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                          {item.entry_type}
                        </span>
                        <span className="ml-2">版本 v{item.version}</span>
                        <span className="ml-2">
                          引用 {item.mention_count} 次
                        </span>
                      </div>
                    </div>
                  </div>
                  {item.content_summary && (
                    <div className="text-sm text-slate-600 mt-2">
                      {item.content_summary}
                    </div>
                  )}
                </div>
              ))}

              {/* 分页 */}
              <div className="flex justify-between items-center pt-2">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 text-sm border border-slate-300 rounded disabled:opacity-50"
                >
                  上一页
                </button>
                <span className="text-sm text-slate-600">
                  第 {page} 页 / 共 {Math.ceil(total / 20) || 1} 页
                </span>
                <button
                  onClick={() => setPage(page + 1)}
                  disabled={items.length < 20}
                  className="px-3 py-1 text-sm border border-slate-300 rounded disabled:opacity-50"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 检索 Tab */}
      {tab === "search" && (
        <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="输入查询，例如：导师"
              className="flex-1 px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <button
              onClick={handleSearch}
              disabled={searchLoading}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700 disabled:bg-slate-400"
            >
              {searchLoading ? "检索中..." : "检索"}
            </button>
          </div>

          {searchError && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
              {searchError}
            </div>
          )}

          {searchResults.length > 0 && (
            <div className="space-y-3">
              <div className="text-sm text-slate-600">
                共 {searchResults.length} 条 wiki 结果
              </div>
              {searchResults.map((item, idx) => (
                <ResultCard
                  key={`${item.id}-${idx}`}
                  item={{
                    id: item.id,
                    text: item.text,
                    doc_id: null,
                    category: item.entry_type,
                    college: null,
                    subject: null,
                    source_url: null,
                    score: item.score,
                    retrieval_sources: item.retrieval_sources,
                    rerank_score: null,
                    page_num: null,
                    char_start: null,
                    char_end: null,
                    title: item.title,
                    entry_type: item.entry_type,
                    summary: item.summary,
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* 详情弹窗 */}
      {selectedItem && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50"
          onClick={() => setSelectedItem(null)}
        >
          <div
            className="bg-white rounded-lg p-5 max-w-2xl w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-start mb-3">
              <h3 className="text-lg font-semibold text-slate-800">
                {selectedItem.title}
              </h3>
              <button
                onClick={() => setSelectedItem(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                关闭
              </button>
            </div>
            <div className="text-xs text-slate-500 mb-3">
              类型：
              <span className="ml-1 px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                {selectedItem.entry_type}
              </span>
              <span className="ml-3">版本 v{selectedItem.version}</span>
              <span className="ml-3">
                引用 {selectedItem.mention_count} 次
              </span>
              {selectedItem.source_doc_ids && (
                <span className="ml-3">
                  来源文档 ID：[{selectedItem.source_doc_ids.join(", ")}]
                </span>
              )}
            </div>
            {selectedItem.content_summary && (
              <div className="bg-slate-50 px-3 py-2 rounded text-sm text-slate-700 mb-3 italic">
                摘要：{selectedItem.content_summary}
              </div>
            )}
            <div className="text-sm text-slate-700 whitespace-pre-wrap">
              {selectedItem.content_md}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
