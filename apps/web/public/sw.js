// Service worker for offline shell only — never cache API / media
const CACHE_NAME = 'app-v3';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

function shouldBypassCache(url) {
  try {
    const u = new URL(url);
    const p = u.pathname || '';
    // API / 封面 / 代理图：始终走网络，避免 iOS PWA 钉死旧 poster
    if (p.startsWith('/api/')) return true;
    if (p.includes('/scrape/export/file')) return true;
    if (p.includes('/scrape/export/img')) return true;
    if (p.includes('/cover-proxy')) return true;
    if (p.includes('/maker-fs/file/')) return true;
  } catch {
    /* ignore */
  }
  return false;
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  if (!event.request.url.startsWith(self.location.origin)) return;
  if (shouldBypassCache(event.request.url)) return;

  // Navigation: network-first, fall back to cache
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request).then((c) => c || caches.match('/')))
    );
    return;
  }

  // Static assets: stale-while-revalidate
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      });
      return cached || fetchPromise;
    })
  );
});
