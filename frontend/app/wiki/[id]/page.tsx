"use client";


import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getWikiApi, type WikiItem } from "@/lib/api";

// 类型徽章配色
const TYPE_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  person: { bg: "bg-purple-100", text: "text-purple-700", label: "人物" },
  policy: { bg: "bg-blue-100", text: "text-blue-700", label: "政策" },
  process: { bg: "bg-emerald-100", text: "text-emerald-700", label: "流程" },
};

export default function WikiDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id);
  const [entry, setEntry] = useState<WikiItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError("");
    getWikiApi(id)
      .then((data) => setEntry(data))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  // 加载态
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-500 text-sm">加载中...</div>
      </div>
    );
  }

  // 错误态
  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4">
        <div className="text-red-600 text-sm">{error}</div>
        <button
          onClick={() => router.push("/?tab=wiki")}
          className="px-4 py-2 bg-slate-100 text-slate-700 text-sm rounded hover:bg-slate-200"
        >
          返回
        </button>
      </div>
    );
  }

  // 未找到
  if (!entry) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4">
        <div className="text-slate-500 text-sm">Wiki 条目不存在</div>
        <button
          onClick={() => router.push("/?tab=wiki")}
          className="px-4 py-2 bg-slate-100 text-slate-700 text-sm rounded hover:bg-slate-200"
        >
          返回
        </button>
      </div>
    );
  }

  const badge = TYPE_BADGE[entry.entry_type] || {
    bg: "bg-slate-100",
    text: "text-slate-700",
    label: entry.entry_type,
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 顶部渐变标题栏（紫色系，雅气） */}
      <header className="bg-gradient-to-r from-purple-600 to-indigo-600 text-white">
        <div className="max-w-4xl mx-auto px-6 py-8">
          {/* 返回按钮 */}
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-purple-100 hover:text-white text-sm mb-6 transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
            返回 Wiki
          </button>

          {/* 类型徽章 + 标题 */}
          <div className="flex items-center gap-3 mb-3">
            <span
              className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white/20 text-white backdrop-blur-sm`}
            >
              {badge.label}
            </span>
            {entry.college && (
              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white/15 text-white backdrop-blur-sm">
                {entry.college}
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{entry.title}</h1>
          {entry.content_summary && (
            <p className="mt-3 text-purple-100 text-sm leading-relaxed">
              {entry.content_summary}
            </p>
          )}
        </div>
      </header>

      {/* 元数据卡片栏 */}
      <div className="max-w-4xl mx-auto px-6 -mt-4">
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <MetaItem label="分类" value={entry.category || "—"} />
            <MetaItem label="学科" value={entry.subject || "—"} />
            <MetaItem label="版本" value={`v${entry.version}`} />
            <MetaItem label="引用次数" value={`${entry.mention_count}`} />
          </div>
          {entry.source_doc_ids && entry.source_doc_ids.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-100">
              <span className="text-xs text-slate-500">来源文档：</span>
              <span className="text-xs text-slate-700 ml-1">
                {entry.source_doc_ids.map((d) => `#${d}`).join("、")}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 正文区（markdown 渲染） */}
      <main className="max-w-4xl mx-auto px-6 py-6">
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-8">
          <article className="prose prose-slate max-w-none prose-headings:text-slate-800 prose-headings:font-semibold prose-h1:text-2xl prose-h1:border-b prose-h1:border-slate-200 prose-h1:pb-2 prose-h2:text-xl prose-h2:mt-6 prose-h3:text-lg prose-p:text-slate-600 prose-p:leading-relaxed prose-li:text-slate-600 prose-strong:text-slate-800 prose-code:text-purple-600 prose-code:bg-purple-50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-blockquote:border-purple-400 prose-blockquote:bg-purple-50/50">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {entry.content_md}
            </ReactMarkdown>
          </article>
        </div>

        {/* 底部操作 */}
        <div className="mt-6 flex justify-center">
          <button
            onClick={() => router.back()}
            className="px-6 py-2 bg-white border border-slate-200 text-slate-700 text-sm rounded-lg hover:bg-slate-50 hover:shadow-sm transition-all"
          >
            返回 Wiki 列表
          </button>
        </div>
      </main>
    </div>
  );
}

// 元数据单项组件
function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-slate-400 mb-0.5">{label}</span>
      <span className="text-sm text-slate-700 font-medium truncate">{value}</span>
    </div>
  );
}
