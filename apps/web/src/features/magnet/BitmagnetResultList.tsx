'use client';

import { useState, type MouseEvent } from 'react';
import type { MagnetHit } from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import { formatByteSize, formatDate, parseHighlight } from '@/lib/format';
import { SEARCH_DISPLAY_FILES_MAX } from '@/config/search';
import { AppMsg } from '@/components/ui/AppMsg';
import { BitmagnetFileList } from './BitmagnetFileList';
import { magnetHash } from '@/lib/mixedSearch';

function magnetOf(item: MagnetHit) {
  return (item.magnet_uri || item.magnet || item.magnets?.[0] || '').trim();
}

function createdTs(item: MagnetHit) {
  if (item.created_at) return item.created_at;
  if (item.createdAt) {
    const n = Date.parse(item.createdAt);
    return Number.isFinite(n) ? Math.floor(n / 1000) : 0;
  }
  return 0;
}

/** 单条 Bitmagnet 卡片（混合列表复用） */
export function MagnetCard({
  item,
  keywords = [],
  badge,
  onOpen,
}: {
  item: MagnetHit;
  keywords?: string[];
  badge?: string;
  onOpen: (hash: string) => void;
}) {
  const [msg, setMsg] = useState('');
  const hash = magnetHash(item);
  const name = item.name || item.title || hash;
  const count = item.files_count ?? item.fileCount ?? item.files?.length ?? 0;

  async function onCopyMagnet(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const magnet = magnetOf(item);
    if (!magnet.startsWith('magnet:')) {
      setMsg('无磁力链接');
      return;
    }
    const ok = await copyText(magnet);
    setMsg(ok ? '已复制磁力' : '复制失败');
  }

  return (
    <article className="bm-card">
      {badge ? <span className="bm-card__badge">{badge}</span> : null}
      <header className={`bm-card__head${badge ? ' bm-card__head--badged' : ''}`}>
        <button
          type="button"
          className="bm-card__title allow-select"
          title={name}
          onClick={() => onOpen(hash)}
        >
          <span
            className="bm-card__title-text"
            dangerouslySetInnerHTML={{
              __html: parseHighlight(name, keywords),
            }}
          />
        </button>
      </header>
      <div className="bm-card__body">
        <BitmagnetFileList
          torrent={item}
          highlight={keywords}
          max={SEARCH_DISPLAY_FILES_MAX}
          coreOnly
          onMore={() => onOpen(hash)}
        />
      </div>
      <footer className="bm-card__foot">
        <button
          type="button"
          className="bm-card__magnet"
          onClick={(e) => void onCopyMagnet(e)}
        >
          <span aria-hidden>🧲</span>
          磁力
        </button>
        <div className="bm-card__meta">
          <span>大小 {formatByteSize(item.size || 0)}</span>
          <span>文件 {count}</span>
          <span>创建 {formatDate(createdTs(item))}</span>
        </div>
      </footer>
      <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg>
    </article>
  );
}

export function BitmagnetResultList({
  keyword,
  items,
  onOpen,
}: {
  keyword: string;
  items: MagnetHit[];
  onOpen: (hash: string) => void;
}) {
  const tokens = keyword.trim() ? [keyword.trim()] : [];
  return (
    <div className="bm-result-list">
      {items.map((item) => (
        <MagnetCard
          key={magnetHash(item)}
          item={item}
          keywords={tokens}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}
