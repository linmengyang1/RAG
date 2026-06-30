/** @type {import('next').NextConfig} */
const nextConfig = {
  // rewrites 代理超时（毫秒）：reranker 推理 30 文档需 50-60 秒，
  // Next.js 默认 30 秒会 ECONNRESET，这里放宽到 180 秒
  experimental: {
    proxyTimeout: 180000,
  },
  // 转发 /api/* 到 backend（避免浏览器 CORS）
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:18000'}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
