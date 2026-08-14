import type { NextConfig } from 'next';

const apiProxy =
  process.env.API_INTERNAL_BASE?.replace(/\/$/, '') || 'http://127.0.0.1:8020';

const nextConfig: NextConfig = {
  output: 'standalone',
  devIndicators: false,
  // 刮削 / 长请求可能超过默认代理超时
  experimental: {
    proxyTimeout: 180_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${apiProxy}/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
    ];
  },
};

export default nextConfig;
