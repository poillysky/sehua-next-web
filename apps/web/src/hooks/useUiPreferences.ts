import { useCallback, useEffect, useState } from 'react';

export type UiPreferences = {
  /** 返回上一层时恢复滚动位置（避免回到顶部） */
  restoreScrollOnBack: boolean;
};

const STORAGE_KEY = 'nextweb-ui-preferences';
export const UI_PREFS_EVENT = 'nextweb-ui-preferences';

export const DEFAULT_UI_PREFERENCES: UiPreferences = {
  restoreScrollOnBack: true,
};

function normalizePrefs(raw: unknown): UiPreferences {
  void raw;
  // 设置页已去掉开关：始终恢复滚动位置
  return { ...DEFAULT_UI_PREFERENCES };
}

export function getUiPreferences(): UiPreferences {
  if (typeof window === 'undefined') {
    return { ...DEFAULT_UI_PREFERENCES };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return normalizePrefs(JSON.parse(raw));
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_UI_PREFERENCES };
}

export function saveUiPreferences(
  preferences: Partial<UiPreferences>,
): UiPreferences {
  const next = {
    ...getUiPreferences(),
    ...preferences,
  };
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    window.dispatchEvent(
      new CustomEvent(UI_PREFS_EVENT, { detail: next }),
    );
  }
  return next;
}

/** 订阅全局 UI 偏好（设置页开关即时生效） */
export function useUiPreferences(): [
  UiPreferences,
  (patch: Partial<UiPreferences>) => void,
] {
  const [prefs, setPrefs] = useState<UiPreferences>(DEFAULT_UI_PREFERENCES);

  useEffect(() => {
    setPrefs(getUiPreferences());
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<UiPreferences>).detail;
      if (detail) setPrefs(detail);
      else setPrefs(getUiPreferences());
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setPrefs(getUiPreferences());
    };
    window.addEventListener(UI_PREFS_EVENT, onCustom);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(UI_PREFS_EVENT, onCustom);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const update = useCallback((patch: Partial<UiPreferences>) => {
    setPrefs(saveUiPreferences(patch));
  }, []);

  return [prefs, update];
}
