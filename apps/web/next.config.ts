import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';

const webDir = path.dirname(fileURLToPath(import.meta.url));
const apiProxy =
  process.env.API_INTERNAL_BASE?.replace(/\/$/, '') || 'http://127.0.0.1:8020';

const nextConfig: NextConfig = {
  output: 'standalone',
  // 热更新用默认 Turbopack。root 锁在 apps/web，避免监听仓库根的 data/library。
  // 共享 maps：由 scripts/sync-maps.mjs 复制进 apps/web/maps（实体文件，非联接）。
  // resolveAlias：root 收窄后 CSS 解析上下文会落到上级 apps/，必须指向本包 node_modules。
  turbopack: {
    root: webDir,
    resolveAlias: {
      tailwindcss: path.join(webDir, 'node_modules/tailwindcss'),
      'tw-animate-css': path.join(webDir, 'node_modules/tw-animate-css'),
      shadcn: path.join(webDir, 'node_modules/shadcn'),
      '@maps': path.join(webDir, 'maps'),
      'app-ui.css': path.join(webDir, 'src/app/app-ui.css'),
    },
  },
  devIndicators: false,
  experimental: {
    // 资源库 zip 导入可达数 GB，放宽代理超时
    proxyTimeout: 3_600_000,
  },
  webpack: (config, { dev }) => {
    config.resolve = config.resolve || {};
    config.resolve.alias = {
      ...(config.resolve.alias || {}),
      '@maps': path.join(webDir, 'maps'),
      'app-ui.css': path.join(webDir, 'src/app/app-ui.css'),
    };
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
