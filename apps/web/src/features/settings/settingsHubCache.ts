/** 设置 Hub 条目状态缓存：避免每次打开「更多」都全量打接口 */

export type SettingsHubTone = 'ok' | 'warn' | 'mute';

export type SettingsHubEntryId =
  | 'users'
  | 'db'
  | 'bitmagnet'
  | 'p115'
  | 'network'
  | 'tmdb'
  | 'pansou'
  | 'cloudsaver'
  | 'ai'
  | 'forum'
  | 'makers';

export type SettingsHubMeta = Record<
  SettingsHubEntryId,
  { text: string; tone: SettingsHubTone }
>;

const TTL_MS = 90_000;

let cachedMeta: SettingsHubMeta | null = null;
let cachedAt = 0;

export function getCachedSettingsHubMeta(): SettingsHubMeta | null {
  return cachedMeta;
}

export function setCachedSettingsHubMeta(meta: SettingsHubMeta): void {
  cachedMeta = meta;
  cachedAt = Date.now();
}

export function patchCachedSettingsHubMeta(
  id: SettingsHubEntryId,
  text: string,
  tone: SettingsHubTone,
): void {
  if (!cachedMeta) return;
  cachedMeta = { ...cachedMeta, [id]: { text, tone } };
  cachedAt = Date.now();
}

export function isSettingsHubMetaFresh(ttlMs = TTL_MS): boolean {
  return cachedMeta != null && Date.now() - cachedAt < ttlMs;
}

export function clearSettingsHubMetaCache(): void {
  cachedMeta = null;
  cachedAt = 0;
}
