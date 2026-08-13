'use client';

import { useState } from 'react';
import type { ResourceItem } from '@/types/resource';
import {
  getExtractPassword,
  hasArchiveEd2k,
  isArchiveDownloadLink,
  linkKindOf,
  linksForResource,
  normalizeLinkKind,
} from '@/lib/detailResource';
import { runP115Save } from '@/lib/p115SaveClient';
import { useTabNavigation } from '@/shell';

type ItemPick = Pick<
  ResourceItem,
  | 'hash'
  | 'ed2k_link'
  | 'ed2k_links'
  | 'extract_password'
  | 'description'
  | 'name'
  | 'title'
  | 'link_kind'
>;

export function P115SaveButton({
  item,
  compact = false,
  onToast,
}: {
  item: ItemPick;
  compact?: boolean;
  onToast?: (msg: string) => void;
}) {
  const tabCtx = useTabNavigation();
  const [loading, setLoading] = useState(false);

  const urls = linksForResource(item);
  const password = getExtractPassword(item);
  const titleHint = (item.title || item.name || '').trim();
  const shareUrls = urls.filter((u) => linkKindOf(u) === '115share');
  const offlineUrls = urls.filter((u) => linkKindOf(u) !== '115share');
  const isShareOnly = shareUrls.length > 0 && offlineUrls.length === 0;
  const isArchive = hasArchiveEd2k(item)
    ? true
    : offlineUrls.some((u) => isArchiveDownloadLink(u));
  const wantExtract = !isShareOnly && (Boolean(password) || isArchive);
  const kind = normalizeLinkKind(item.link_kind || linkKindOf(urls[0]));

  if (!urls.length) return null;

  const onSave = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const result = await runP115Save({
        urls,
        password,
        titleHint,
      });
      if (!result.ok) {
        onToast?.(result.message);
        if (result.needConfig) {
          window.setTimeout(() => tabCtx?.scrollToTab('/settings'), 600);
        }
        return;
      }
      const tip = wantExtract
        ? result.extractScheduled
          ? '已转存，云解压已安排'
          : result.message || '已转存'
        : kind === '115share'
          ? '115 分享已接收'
          : '已加入离线下载';
      onToast?.(tip);
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : '转存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      className={compact ? 'detail-compact-btn' : 'app-btn-primary'}
      disabled={loading}
      onClick={() => void onSave()}
    >
      {loading ? '转存中…' : '转存 115'}
    </button>
  );
}
