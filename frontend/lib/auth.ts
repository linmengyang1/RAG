/**
 * 鉴权工具：token 存取 + authApi（登录/注册/当前用户）
 *
 * token 存 localStorage，所有需要鉴权的请求通过 lib/api.ts 的 authFetch 自动注入
 * Authorization: Bearer <token>。本文件的 getMeApi 也需带 token（用于启动时恢复会话）。
 *
 * 后端接口（已就绪，见 backend/app/api/v1/auth.py）：
 *   POST /api/v1/auth/register  {username, password, email?}  -> TokenOut
 *   POST /api/v1/auth/login     {username, password}           -> TokenOut
 *   GET  /api/v1/auth/me        (需 Bearer)                    -> UserOut
 */

// localStorage 键名
const TOKEN_KEY = "grad_rag_token";

// 用户信息（对应后端 UserOut）
export interface User {
  id: number;
  username: string;
  email: string | null;
  role: string; // admin / user
  is_active: boolean;
  created_at: string;
}

// 登录/注册响应（对应后端 TokenOut）
export interface TokenOut {
  access_token: string;
  token_type: string;
  user: User;
}

// ───── token 存取（localStorage，SSR 安全）─────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

// ───── authApi ─────

/**
 * 注册（第一个用户自动成为 admin）
 * 公开接口，无需 token
 */
export async function registerApi(
  username: string,
  password: string,
  email?: string
): Promise<TokenOut> {
  const resp = await fetch("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, email: email || undefined }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `注册失败: ${resp.status}`);
  }
  return resp.json();
}

/**
 * 登录
 * 公开接口，无需 token
 */
export async function loginApi(
  username: string,
  password: string
): Promise<TokenOut> {
  const resp = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `登录失败: ${resp.status}`);
  }
  return resp.json();
}

/**
 * 获取当前用户信息（需 token）
 * 用于启动时从 localStorage 恢复 token 后验证有效性
 */
export async function getMeApi(): Promise<User> {
  const token = getToken();
  const resp = await fetch("/api/v1/auth/me", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    throw new Error(`获取用户信息失败: ${resp.status}`);
  }
  return resp.json();
}
