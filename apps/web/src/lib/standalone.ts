/** Detect iOS / PWA standalone shell mode */

export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const mq = window.matchMedia('(display-mode: standalone)').matches;
  const ios = Boolean(
    (navigator as Navigator & { standalone?: boolean }).standalone,
  );
  return mq || ios;
}

export function isNarrowPhone(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(max-width: 480px)').matches;
}

export function shouldUseNativeShell(): boolean {
  return isStandalone() || isNarrowPhone();
}
