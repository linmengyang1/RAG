"use client";

/**
 * 鉴权 Context：全局管理 user 状态 + login/logout/register
 *
 * 用法：
 *   - 在 app/layout.tsx 包 <AuthProvider>
 *   - 在任意客户端组件 const { user, login, logout } = useAuth()
 *
 * 启动时自动从 localStorage 恢复 token，调 /auth/me 验证有效性：
 *   - 有效：设置 user，loading=false
 *   - 无效/无 token：清除 token，user=null，loading=false
 *   - loading 期间页面可显示加载态，避免闪烁
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  type User,
  type TokenOut,
  getToken,
  setToken,
  removeToken,
  loginApi,
  registerApi,
  getMeApi,
} from "./auth";

interface AuthContextValue {
  user: User | null;
  // 启动时验证 token 中（true=正在验证，页面应显示加载态）
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    email?: string
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 启动时从 localStorage 恢复 token，调 /auth/me 验证
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    getMeApi()
      .then((u) => setUser(u))
      .catch(() => {
        // token 无效或过期，清除
        removeToken();
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const data: TokenOut = await loginApi(username, password);
    setToken(data.access_token);
    setUser(data.user);
  };

  const register = async (
    username: string,
    password: string,
    email?: string
  ) => {
    const data: TokenOut = await registerApi(username, password, email);
    setToken(data.access_token);
    setUser(data.user);
  };

  const logout = () => {
    removeToken();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return ctx;
}
