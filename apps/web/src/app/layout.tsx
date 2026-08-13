import type { Metadata, Viewport } from 'next';
import { DM_Sans, DM_Serif_Text, Geist_Mono } from 'next/font/google';
import { Providers } from './providers';
import { ShellBoot } from '@/components/layout/ShellBoot';
import './globals.css';
import './search-ui.css';

const dmSans = DM_Sans({
  variable: '--font-sans',
  subsets: ['latin'],
  display: 'swap',
});

const dmSerif = DM_Serif_Text({
  variable: '--font-display',
  weight: '400',
  subsets: ['latin'],
  display: 'swap',
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'NextWeb',
  description: '模版壳 iOS PWA + FastAPI 资源检索',
  manifest: '/manifest.json',
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '32x32' },
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: '资源仓库',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover',
  // 键盘覆盖内容，不挤缩布局视口（Chrome / Android；iOS 常忽略但仍声明）
  interactiveWidget: 'overlays-content',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f2f2f7' },
    { media: '(prefers-color-scheme: dark)', color: '#000000' },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <ShellBoot />
        {/* Apply theme synchronously to prevent flash of wrong theme */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('theme');var d=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme:dark)').matches);var h=document.documentElement;h.classList.toggle('dark',d);h.style.colorScheme=d?'dark':'light';h.style.backgroundColor=d?'#000000':'#f2f2f7'}catch(e){}})()`,
          }}
        />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
      </head>
      <body
        className={`${dmSans.variable} ${dmSerif.variable} ${geistMono.variable} font-sans antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
