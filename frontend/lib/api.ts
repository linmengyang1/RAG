/**
 * Backend API 封装
 *
 * 通过 next.config.js 的 rewrites 把 /api/* 转发到 backend，
 * 所以前端直接 fetch /api/v1/... 即可，无需处理 CORS。
 *
 * AUTH_DISABLED=true 时无需 token，否则需在 header 加 Authorization。
 */

// 检索方式选项
export interface SearchOptions {
  q: string;
  top_k?: number;
  category?: string;
  enable_rerank?: boolean;
  enable_wiki?: boolean;
}

// 检索单条结果
export interface SearchResultItem {
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
}

// 检索响应
export interface SearchResponse {
  query: string;
  total: number;
  results: SearchResultItem[];
}

// 问答请求
export interface ChatRequest {
  question: string;
  top_k?: number;
  conversation_id?: number;
  enable_rerank?: boolean;
  enable_wiki?: boolean;
}

// 问答引用来源
export interface ChatSource {
  text: string;
  score: number;
  doc_id: number | null;
  category: string | null;
  college: string | null;
  subject: string | null;
  source_url: string | null;
  retrieval_sources: string[];
  rerank_score: number | null;
  page_num: number | null;
  char_start: number | null;
  char_end: number | null;
}

// 问答响应
export interface ChatResponse {
  question: string;
  rewritten_query: string;
  intent: string;
  conversation_id: number;
  answer: string;
  sources: ChatSource[];
}

// Wiki 条目
export interface WikiItem {
  id: number;
  title: string;
  entry_type: string;
  content_md: string;
  content_summary: string | null;
  source_doc_ids: number[] | null;
  mention_count: number;
  version: number;
}

export interface WikiListResponse {
  total: number;
  page: number;
  page_size: number;
  items: WikiItem[];
}

export interface WikiSearchResultItem {
  id: number;
  title: string;
  entry_type: string;
  text: string;
  summary: string;
  score: number;
  retrieval_sources: string[];
}

export interface WikiSearchResponse {
  query: string;
  total: number;
  results: WikiSearchResultItem[];
}

/**
 * 调用检索 API
 */
export async function searchApi(opts: SearchOptions): Promise<SearchResponse> {
  const params = new URLSearchParams();
  params.set("q", opts.q);
  if (opts.top_k) params.set("top_k", String(opts.top_k));
  if (opts.category) params.set("category", opts.category);
  if (opts.enable_rerank !== undefined)
    params.set("enable_rerank", String(opts.enable_rerank));
  if (opts.enable_wiki !== undefined)
    params.set("enable_wiki", String(opts.enable_wiki));

  const resp = await fetch(`/api/v1/search?${params.toString()}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  if (!resp.ok) {
    throw new Error(`检索失败: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * 调用问答 API
 */
export async function chatApi(req: ChatRequest): Promise<ChatResponse> {
  const resp = await fetch("/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    throw new Error(`问答失败: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

// ───── SSE 流式问答回调 ─────
export interface ChatStreamCallbacks {
  onIntent: (intent: string, rewrittenQuery: string) => void;
  onRetrieving: () => void;
  onRetrieved: (count: number) => void;
  onGenerating: () => void;
  onToken: (delta: string) => void;
  onDone: (data: {
    conversation_id: number;
    intent: string;
    rewritten_query: string;
    answer: string;
    sources: ChatSource[];
  }) => void;
  onError: (msg: string) => void;
}

/**
 * 流式问答：SSE 分阶段推送，实时显示思考过程
 *
 * 事件流：intent_done → retrieving → retrieved → generating → token(多次) → done
 */
export async function chatStreamApi(
  req: ChatRequest,
  callbacks: ChatStreamCallbacks
): Promise<void> {
  const resp = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`问答失败: ${resp.status} ${await resp.text()}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 事件帧以空行（\n\n）分隔
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || ""; // 最后一个可能不完整，留到下次

    for (const frame of frames) {
      const lines = frame.split("\n");
      let event = "";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (!event) continue;

      let parsed: any = {};
      try {
        parsed = data ? JSON.parse(data) : {};
      } catch {
        continue;
      }

      switch (event) {
        case "intent_done":
          callbacks.onIntent(parsed.intent, parsed.rewritten_query);
          break;
        case "retrieving":
          callbacks.onRetrieving();
          break;
        case "retrieved":
          callbacks.onRetrieved(parsed.sources_count);
          break;
        case "generating":
          callbacks.onGenerating();
          break;
        case "token":
          callbacks.onToken(parsed.delta);
          break;
        case "done":
          callbacks.onDone(parsed);
          break;
        case "error":
          callbacks.onError(parsed.detail || "未知错误");
          break;
      }
    }
  }
}

/**
 * Wiki 列表
 */
export async function listWikiApi(
  entryType?: string,
  page = 1,
  pageSize = 20
): Promise<WikiListResponse> {
  const params = new URLSearchParams();
  if (entryType) params.set("entry_type", entryType);
  params.set("page", String(page));
  params.set("page_size", String(pageSize));

  const resp = await fetch(`/api/v1/wiki?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`Wiki 列表失败: ${resp.status}`);
  }
  return resp.json();
}

/**
 * Wiki 详情
 */
export async function getWikiApi(id: number): Promise<WikiItem> {
  const resp = await fetch(`/api/v1/wiki/${id}`);
  if (!resp.ok) {
    throw new Error(`Wiki 详情失败: ${resp.status}`);
  }
  return resp.json();
}

/**
 * Wiki 检索
 */
export async function searchWikiApi(
  q: string,
  topK = 5
): Promise<WikiSearchResponse> {
  const params = new URLSearchParams();
  params.set("q", q);
  params.set("top_k", String(topK));

  const resp = await fetch(`/api/v1/wiki/search?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`Wiki 检索失败: ${resp.status}`);
  }
  return resp.json();
}

/**
 * 触发 Wiki 生成（admin）
 */
export async function generateWikiApi(
  docIds?: number[],
  limit = 50
): Promise<{ generated: number; skipped: number; errors: number }> {
  const resp = await fetch("/api/v1/wiki/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_ids: docIds, limit }),
  });
  if (!resp.ok) {
    throw new Error(`Wiki 生成失败: ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}
