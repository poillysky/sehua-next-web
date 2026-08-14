export function registerServiceWorker() {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;

  const kickUpdate = () => {
    void navigator.serviceWorker.getRegistration().then((reg) => {
      void reg?.update();
    });
  };

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => {
        console.log('SW registered:', reg.scope);
        void reg.update();
      })
      .catch((err) => {
        console.log('SW registration failed:', err);
      });
  });

  // 回前台时检查新 SW（iOS PWA 否则会一直钉旧缓存策略）
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') kickUpdate();
  });
  window.addEventListener('pageshow', kickUpdate);
}
