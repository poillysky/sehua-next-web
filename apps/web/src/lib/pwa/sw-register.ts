/** 注册 PWA Service Worker（仅正式壳；开发 / iframe 跳过以免 InvalidStateError）。 */
export function registerServiceWorker() {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  // Next/Turbopack HMR、Cursor 预览 iframe 下 getRegistration 常抛 InvalidStateError
  if (process.env.NODE_ENV !== 'production') return;
  if (window.top !== window) return;
  if (!window.isSecureContext) return;

  const ignore = () => undefined;

  const kickUpdate = () => {
    try {
      if (document.visibilityState !== 'visible') return;
      if (document.readyState === 'loading') return;
      void navigator.serviceWorker.getRegistration().then((reg) => {
        void reg?.update().catch(ignore);
      }, ignore);
    } catch {
      /* document 卸载/无效态 */
    }
  };

  const doRegister = () => {
    try {
      void navigator.serviceWorker
        .register('/sw.js')
        .then((reg) => {
          console.log('SW registered:', reg.scope);
          void reg.update().catch(ignore);
        }, ignore);
    } catch {
      /* ignore */
    }
  };

  if (document.readyState === 'complete') {
    doRegister();
  } else {
    window.addEventListener('load', doRegister, { once: true });
  }

  // 回前台时检查新 SW（iOS PWA 否则会一直钉旧缓存策略）
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') kickUpdate();
  });
  window.addEventListener('pageshow', kickUpdate);
}
