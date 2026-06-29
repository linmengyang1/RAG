import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "研究生院 RAG 知识库",
  description: "Graduate RAG 检索/问答/Wiki 一体化界面",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
