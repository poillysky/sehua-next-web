import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';

const webDir = path.dirname(fileURLToPath(import.meta.url));
const apiProxy =
  process.env.API_INTERNAL_BASE?.replace(/\/$/, '') || 'http://127.0.0.1:8020';

const nextConfig: NextConfig = {
  output: 'standalone',
  // 热更新用默认 Turbopack。root 锁在 apps/web，避免监听仓库根的 data/library。
  // resolveAlias：root 收窄后 CSS 解析上下文会落到上级 apps/，必须指向本包 node_modules。
  turbopack: {
    root: webDir,
    resolveAlias: {
      tailwindcss: path.join(webDir, 'node_modules/tailwindcss'),
      'tw-animate-css': path.join(webDir, 'node_modules/tw-animate-css'),
      shadcn: path.join(webDir, 'node_modules/shadcn'),
    },
  },
  devIndicators: false,
  experimental: {
    proxyTimeout: 180_000,
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
        followSymlinks: false,
        ignored: [
          '**/node_modules/**',
          '**/.git/**',
          '**/.next/**',
          '**/data/**',
          '**/library/**',
          '**/maker-fs/**',
          '**/.venv/**',
          '**/apps/api/**',
          '**/System Volume Information/**',
          '**/$Recycle.Bin/**',
        ],
      };
    }
    return config;
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
