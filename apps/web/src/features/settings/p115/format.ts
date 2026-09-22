import type {
  P115Config,
  P115SaveSource,
  P115TargetFolder,
  P115Task,
} from '@/lib/api';
import type { P115PanelTab } from '../p115PanelCache';

export type Tab = P115PanelTab;
export type BrowseTarget = P115SaveSource | 'subs';

export const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'overview', label: '概览' },
  { key: 'config', label: '配置' },
  { key: 'tasks', label: '任务' },
];

export const SAVE_SOURCES: Array<{
  key: P115SaveSource;
  label: string;
  desc: string;
}> = [
  { key: 'warehouse', label: '仓库', desc: '先最近接收 → 再进本目录' },
  { key: 'movie', label: '电影', desc: '影视·电影 · 先最近接收 → 再进本目录' },
  { key: 'tv', label: '电视剧', desc: '影视·剧集 · 先最近接收 → 再进本目录' },
  { key: 'makers', label: '片商', desc: '片商 · 先最近接收 → 再进本目录' },
];

export function emptyTargets(): Record<P115SaveSource, P115TargetFolder> {
  return {
    warehouse: { folderCid: '0', folderName: '' },
    movie: { folderCid: '0', folderName: '' },
    tv: { folderCid: '0', folderName: '' },
    makers: { folderCid: '0', folderName: '' },
  };
}

export function normalizeTargets(
  data: Partial<P115Config> | null | undefined,
): Record<P115SaveSource, P115TargetFolder> {
  const base = emptyTargets();
  const legacyCid = String(data?.folderCid || '0') || '0';
  const legacyName = String(data?.folderName || '');
  const legacyMedia = data?.targets?.media as P115TargetFolder | undefined;
  for (const row of SAVE_SOURCES) {
    const t = data?.targets?.[row.key];
    if (t?.folderCid != null || t?.folderName != null) {
      base[row.key] = {
        folderCid: String(t.folderCid || legacyCid || '0') || '0',
        folderName: String(t.folderName || ''),
      };
      continue;
    }
    if (
      (row.key === 'movie' || row.key === 'tv') &&
      (legacyMedia?.folderCid != null || legacyMedia?.folderName != null)
    ) {
      base[row.key] = {
        folderCid: String(legacyMedia.folderCid || legacyCid || '0') || '0',
        folderName: String(legacyMedia.folderName || ''),
      };
      continue;
    }
    base[row.key] = {
      folderCid: legacyCid,
      folderName: legacyName,
    };
  }
  return base;
}

export function folderDisplayName(t: P115TargetFolder) {
  return t.folderName || (t.folderCid === '0' ? '根目录' : '自定义目录');
}

export function formatQuota(
  remain: number | null | undefined,
  total: number | null | undefined,
) {
  if (remain == null && total == null) return null;
  if (remain != null && total != null) return `${remain} / ${total}`;
  if (remain != null) return String(remain);
  return String(total);
}

export function formatBytes(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n) || n < 0) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  const digits = v >= 100 || i < 2 ? 0 : v >= 10 ? 1 : 2;
  const text =
    Number.isInteger(v) || digits === 0 ? String(Math.round(v)) : v.toFixed(digits);
  return `${text} ${units[i]}`;
}

export function formatTaskTime(ts: number | null | undefined) {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return '';
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '';
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} ${weekdays[d.getDay()]} ${hh}:${mm}`;
}

export function taskTone(status: number): 'ok' | 'warn' | 'run' | 'mute' {
  if (status === 2) return 'ok';
  if (status === -1) return 'warn';
  if (status === 1 || status === 0) return 'run';
  return 'mute';
}

export type TaskFilter = 'run' | 'failed' | 'done';

export const TASK_FILTERS: Array<{ key: TaskFilter; label: string }> = [
  { key: 'run', label: '下载中' },
  { key: 'failed', label: '已失败' },
  { key: 'done', label: '已完成' },
];

export function taskFilterOf(status: number): TaskFilter {
  if (status === 2) return 'done';
  if (status === -1) return 'failed';
  return 'run';
}

export function isHashLikeName(name: string, infoHash?: string) {
  const n = String(name || '').trim();
  const h = String(infoHash || '').trim();
  if (!n) return false;
  if (h && n.toLowerCase() === h.toLowerCase()) return true;
  return /^[a-f0-9]{40}$/i.test(n);
}

export function formatHashShort(raw: string) {
  const s = String(raw || '').trim();
  if (s.length <= 12) return s;
  return `${s.slice(0, 6)}…${s.slice(-4)}`;
}

export function taskDisplay(t: P115Task) {
  const raw = String(t.name || '').trim() || '未命名任务';
  const hash = String(t.infoHash || '').trim();
  if (isHashLikeName(raw, hash)) {
    const full = hash || raw;
    return {
      title: formatHashShort(full),
      subtitle: '磁力哈希',
      hashFull: full,
      isHash: true,
    };
  }
  return { title: raw, subtitle: null, hashFull: null, isHash: false };
}
