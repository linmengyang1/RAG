/** @type {import('next').NextConfig} */
const nextConfig = {
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
