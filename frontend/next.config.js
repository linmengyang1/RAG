/** @type {import('next').NextConfig} */
const nextConfig = {
  // 禁用 gzip 压缩：Next.js 默认对响应做 gzip，会破坏 SSE 流式
  // （浏览器 reader.read() 需等足够数据才能解压 gzip，导致卡在"意图识别中"）
  compress: false,
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
