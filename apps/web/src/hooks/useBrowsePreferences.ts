export type BrowsePreferences = {
  preferChinese: boolean;
  preferCrack: boolean;
};

const STORAGE_KEY = 'nextweb-browse-preferences';
export const BROWSE_PREFS_COOKIE = 'nw-browse-prefs';

export const DEFAULT_BROWSE_PREFERENCES: BrowsePreferences = {
  preferChinese: false,
  preferCrack: false,
};

function normalizePrefs(raw: unknown): BrowsePreferences {
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_BROWSE_PREFERENCES };
  }
  const obj = raw as Record<string, unknown>;
  return {
    preferChinese: Boolean(obj.preferChinese),
    preferCrack: Boolean(obj.preferCrack),
  };
}

export function parseBrowsePrefsCookie(value?: string | null): BrowsePreferences {
  if (!value) return { ...DEFAULT_BROWSE_PREFERENCES };
  try {
    return normalizePrefs(JSON.parse(value));
  } catch {
    return { ...DEFAULT_BROWSE_PREFERENCES };
  }
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  for (const part of document.cookie.split('; ')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i) === name) {
      return decodeURIComponent(part.slice(i + 1));
    }
  }
  return null;
}

function writeCookie(name: string, value: string, days: number) {
  if (typeof document === 'undefined') return;
  const maxAge = Math.max(0, Math.floor(days * 86400));
  document.cookie = `${name}=${encodeURIComponent(value)};path=/;max-age=${maxAge};SameSite=Lax`;
}

export function getBrowsePreferences(): BrowsePreferences {
  if (typeof window === 'undefined') {
    return { ...DEFAULT_BROWSE_PREFERENCES };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return normalizePrefs(JSON.parse(raw));
  } catch {
    /* fall through */
  }
  return parseBrowsePrefsCookie(readCookie(BROWSE_PREFS_COOKIE));
}

export function saveBrowsePreferences(
  preferences: Partial<BrowsePreferences>,
): BrowsePreferences {
  const next = {
    ...getBrowsePreferences(),
    ...preferences,
  };
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    writeCookie(BROWSE_PREFS_COOKIE, JSON.stringify(next), 365);
  }
  return next;
}
