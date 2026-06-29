"use client";

import { useState } from "react";

// 检索结果项（兼容 search 和 chat 的 source）
export interface ResultItem {
  id: number;
  text: string;
  doc_id: number | null;
  category: string | null;
  college: string | null;
  subject: string | null;
  source_url: string | null;
  score: number;
  retrieval_sources: string[];
  rerank_score: number | null;
  page_num: number | null;
  char_start: number | null;
  char_end: number | null;
  // wiki 路附加字段
  title?: string;
  entry_type?: string;
  summary?: string;
}

// 检索方式标签颜色映射
const SOURCE_COLOR: Record<string, string> = {
  dense: "bg-blue-100 text-blue-700",
  sparse: "bg-green-100 text-green-700",
  wiki: "bg-purple-100 text-purple-700",
};

// 检索方式中文标签
const SOURCE_LABEL: Record<string, string> = {
  dense: "向量检索",
  sparse: "关键词检索",
  wiki: "Wiki 沉淀",
};

export default function ResultCard({ item }: { item: ResultItem }) {
  const [expanded, setExpanded] = useState(false);
  const isWiki = item.retrieval_sources.includes("wiki");

  // 文本截断（默认显示前 200 字符）
  const preview = item.text.length > 200 && !expanded
    ? item.text.slice(0, 200) + "..."
    : item.text;

  // 分数显示（rerank 优先，否则 score）
  const displayScore = item.rerank_score ?? item.score;
  const scorePercent = Math.round(displayScore * 100);

  // 原文位置文本
  let locationText = "";
  if (item.page_num) {
    locationText = `原文位置：doc_${item.doc_id ?? "?"} 第 ${item.page_num} 页`;
    if (item.char_start !== null && item.char_end !== null) {
      locationText += ` (字符 ${item.char_start}-${item.char_end})`;
    }
  } else if (item.char_start !== null && item.char_end !== null) {
    locationText = `原文位置：doc_${item.doc_id ?? "?"} 字符 ${item.char_start}-${item.char_end}`;
  } else if (item.doc_id !== null) {
    locationText = `原文 doc_id: ${item.doc_id}`;
  }

  return (
    <div className="border border-slate-200 rounded-lg p-4 hover:shadow-md transition-shadow bg-white">
      {/* 顶部：检索方式 + 相似度 */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex flex-wrap gap-1">
          {item.retrieval_sources.length === 0 ? (
            <span className="px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600">
              未知来源
            </span>
          ) : (
            item.retrieval_sources.map((src) => (
              <span
                key={src}
                className={`px-2 py-0.5 text-xs rounded ${
                  SOURCE_COLOR[src] || "bg-slate-100 text-slate-600"
                }`}
              >
                {SOURCE_LABEL[src] || src}
              </span>
            ))
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">相似度</span>
          <div className="flex items-center gap-1">
            <div className="w-12 h-2 bg-slate-100 rounded overflow-hidden">
              <div
                className="h-full bg-brand-500"
                style={{ width: `${Math.min(scorePercent, 100)}%` }}
              />
            </div>
            <span className="text-xs font-mono text-slate-700">
              {displayScore.toFixed(4)}
            </span>
          </div>
        </div>
      </div>

      {/* wiki 条目标题 */}
      {isWiki && item.title && (
        <div className="mb-2">
          <h3 className="text-base font-semibold text-purple-700">
            {item.title}
          </h3>
          {item.entry_type && (
            <span className="text-xs text-purple-500">
              类型：{item.entry_type}
            </span>
          )}
        </div>
      )}

      {/* 文本内容 */}
      <div className="text-sm text-slate-700 whitespace-pre-wrap break-words mb-2">
        {preview}
      </div>
      {item.text.length > 200 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-brand-600 hover:text-brand-700 mt-1"
        >
          {expanded ? "收起" : "展开全文"}
        </button>
      )}

      {/* 摘要（wiki） */}
      {isWiki && item.summary && (
        <div className="text-xs text-slate-500 italic mt-2 mb-2">
          摘要：{item.summary}
        </div>
      )}

      {/* 元数据 */}
      <div className="border-t border-slate-100 mt-3 pt-2 space-y-1">
        {/* 分类信息 */}
        {!isWiki && (
          <div className="text-xs text-slate-500 flex flex-wrap gap-x-3 gap-y-1">
            {item.category && (
              <span>分类：{item.category}</span>
            )}
            {item.college && (
              <span>学院：{item.college}</span>
            )}
            {item.subject && (
              <span>学科：{item.subject}</span>
            )}
          </div>
        )}

        {/* 原文位置 */}
        {locationText && (
          <div className="text-xs text-slate-500">{locationText}</div>
        )}

        {/* source_url */}
        {item.source_url && (
          <div className="text-xs text-slate-500 truncate">
            来源 URL：
            <a
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-600 hover:text-brand-700 underline ml-1"
            >
              {item.source_url}
            </a>
          </div>
        )}

        {/* rerank 分数（如果启用） */}
        {item.rerank_score !== null && (
          <div className="text-xs text-slate-500">
            rerank 分数：{item.rerank_score.toFixed(4)}
          </div>
        )}
      </div>
    </div>
  );
}
