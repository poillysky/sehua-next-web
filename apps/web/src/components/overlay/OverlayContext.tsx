'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, AlertTriangle, Check, Info } from 'lucide-react';

export type ToastKind = 'success' | 'error' | 'info' | 'warn';

type ToastItem = {
  id: number;
  message: string;
  kind: ToastKind;
  leaving?: boolean;
  allowSelect?: boolean;
};

type ToastOptions = {
  duration?: number;
  onDismiss?: () => void;
  allowSelect?: boolean;
};

type OverlayApi = {
  toast: (message: string, kind?: ToastKind, options?: ToastOptions) => void;
};

const OverlayCtx = createContext<OverlayApi | null>(null);

let toastSeq = 0;

const TOAST_HOLD_MS: Record<ToastKind, number> = {
  error: 3600,
  warn: 3000,
  success: 2200,
  info: 2200,
};

const TOAST_EXIT_MS = 220;

export function getOverlayRoot(): HTMLElement | null {
  if (typeof document === 'undefined') return null;
  return (
    document.getElementById('app-overlay-root') ||
    (document.querySelector('.device-content') as HTMLElement | null) ||
    document.body
  );
}

function ToastIcon({ kind }: { kind: ToastKind }) {
  if (kind === 'success') {
    return <Check className="toast__icon" size={15} strokeWidth={2.6} aria-hidden />;
  }
  if (kind === 'error') {
    return (
      <AlertCircle className="toast__icon" size={15} strokeWidth={2.4} aria-hidden />
    );
  }
  if (kind === 'warn') {
    return (
      <AlertTriangle className="toast__icon" size={15} strokeWidth={2.4} aria-hidden />
    );
  }
  return <Info className="toast__icon" size={15} strokeWidth={2.4} aria-hidden />;
}

export function OverlayProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [root, setRoot] = useState<HTMLElement | null>(null);
  const timersRef = useRef<Map<number, number>>(new Map());
  const dismissCbRef = useRef<Map<number, (() => void) | undefined>>(new Map());

  useEffect(() => {
    const sync = () => setRoot(getOverlayRoot());
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);

  useEffect(() => {
    const timers = timersRef.current;
    const cbs = dismissCbRef.current;
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
      cbs.clear();
    };
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)),
    );
    const exitTimer = window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      timersRef.current.delete(id);
      const cb = dismissCbRef.current.get(id);
      dismissCbRef.current.delete(id);
      cb?.();
    }, TOAST_EXIT_MS);
    timersRef.current.set(id, exitTimer);
  }, []);

  const toast = useCallback(
    (message: string, kind: ToastKind = 'info', options?: ToastOptions) => {
      const text = String(message || '').trim();
      if (!text) return;

      timersRef.current.forEach((t) => window.clearTimeout(t));
      timersRef.current.clear();
      // 替换时也触发旧回调，避免父级 msg 卡住
      dismissCbRef.current.forEach((cb) => cb?.());
      dismissCbRef.current.clear();

      const id = ++toastSeq;
      dismissCbRef.current.set(id, options?.onDismiss);
      setToasts([
        {
          id,
          message: text,
          kind,
          allowSelect: options?.allowSelect,
        },
      ]);

      const holdMs =
        options?.duration === 0
          ? 0
          : options?.duration && options.duration > 0
            ? options.duration
            : TOAST_HOLD_MS[kind];

      if (holdMs > 0) {
        const hold = window.setTimeout(() => dismiss(id), holdMs);
        timersRef.current.set(id, hold);
      }
    },
    [dismiss],
  );

  const api = useMemo(() => ({ toast }), [toast]);

  return (
    <OverlayCtx.Provider value={api}>
      {children}
      {root
        ? createPortal(
            <div className="toast-stack" aria-live="polite" aria-relevant="additions">
              {toasts.map((t) => (
                <div
                  key={t.id}
                  role="status"
                  className={`toast toast--${t.kind}${t.leaving ? ' toast--leaving' : ''}${
                    t.allowSelect ? ' allow-select' : ''
                  }`}
                >
                  <span className="toast__glyph" aria-hidden>
                    <ToastIcon kind={t.kind} />
                  </span>
                  <p className="toast__text">{t.message}</p>
                </div>
              ))}
            </div>,
            root,
          )
        : null}
    </OverlayCtx.Provider>
  );
}

export function useOverlay(): OverlayApi {
  const ctx = useContext(OverlayCtx);
  if (!ctx) {
    return {
      toast: (message) => {
        if (typeof window !== 'undefined') console.info('[toast]', message);
      },
    };
  }
  return ctx;
}
