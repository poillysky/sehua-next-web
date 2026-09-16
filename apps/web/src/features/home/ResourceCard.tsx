'use client';

import { useState, type MouseEvent } from 'react';
import type { ResourceItem } from '@/types/resource';
import { formatByteSize, formatDate, parseHighlight } from '@/lib/format';
import {
  normalizeResourceView,
  parseEd2kLink,
} from '@/lib/resourceView';
import { copyText } from '@/lib/clipboard';
import { AppMsg } from '@/components/ui/AppMsg';
import { ContextMenu } from '@/components/ui/ContextMenu';
import { useLongPress } from '@/hooks/useLongPress';
import { useHaptics } from '@/shell';
import {
  getEd2kCopyText,
  linkKindOf,
  linksForResource,
  normalizeLinkKind,
} from '@/lib/detailResource';
import { SEARCH_DISPLAY_FILES_MAX } from '@/config/search';

const LINK_KIND_LABEL: Record<string, string> = {
  magnet: '磁力',
  ed2k: 'ed2k',
  share115: '115',
  '115share': '115',
  unavailable: '占位',
  stub: '占位',
};

function shortHash(hash: string): string {
  const h = hash.trim().toUpperCase();
  if (h.length <= 16) return h;
  return `${h.slice(0, 8)}…${h.slice(-6)}`;
}

function decodeEd2kName(raw: string): string {
  try {
    return decodeURIComponent(raw.replace(/\+/g, ' '));
  } catch {
    return raw;
  }
}

function summarizeLink(link: string): {
  kind: ReturnType<typeof normalizeLinkKind>;
  kindLabel: string;
  primary: string;
  secondary: string;
} {
  const kind = normalizeLinkKind(linkKindOf(link));
  if (kind === 'magnet') {
    return {
      kind,
      kindLabel: '磁力',
      primary: link.trim(),
      secondary: '',
    };
  }
  if (kind === 'ed2k') {
    const parsed = parseEd2kLink(link);
    const name = parsed?.filename ? decodeEd2kName(parsed.filename) : '';
    const size = parsed?.size ? formatByteSize(Number(parsed.size)) : '';
    const hash = parsed?.hash || '';
    return {
      kind,
      kindLabel: 'ed2k',
      primary: name || link.trim(),
      secondary: [size, hash ? shortHash(hash) : ''].filter(Boolean).join(' · '),
    };
  }
  if (kind === '115share') {
    let host = '115 分享';
    try {
      host = new URL(link).hostname.replace(/^www\./, '');
    } catch {
      /* ignore */
    }
    return {
      kind,
      kindLabel: '115',
      primary: host,
      secondary: link.replace(/^https?:\/\//i, ''),
    };
  }
  return {
    kind,
    kindLabel: kind === 'stub' ? '占位' : '链接',
    primary: link.slice(0, 48) || '不可用',
    secondary: kind === 'stub' ? '暂无可用下载' : link.slice(0, 64),
  };
}

function CardLinksBody({
  links,
  kind,
  onOpen,
}: {
  links: string[];
  kind: ReturnType<typeof normalizeLinkKind>;
  onOpen: () => void;
}) {
  const shown = links.slice(0, SEARCH_DISPLAY_FILES_MAX);
  const hidden = Math.max(0, links.length - shown.length);

  if (!links.length) {
    return (
      <div className="bm-card__body">
        <p className="bm-card__links-empty">
          {kind === 'stub' ? '暂无可用下载链接' : '暂无链接'}
        </p>
      </div>
    );
  }

  return (
    <div className="bm-card__body bm-card__body--links">
      <ul className="bm-card__links">
        {shown.map((link, index) => {
          const row = summarizeLink(link);
          return (
            <li
              key={`${link}-${index}`}
              className={`bm-card__link-row bm-card__link-row--${row.kind}`}
            >
              <button
                type="button"
                className="bm-card__link-main"
                onClick={onOpen}
                title={link}
              >
                <span className="bm-card__link-text">
                  <span
                    className={`bm-card__link-primary allow-select${
                      row.kind === 'magnet' ? ' bm-card__link-primary--uri' : ''
                    }`}
                  >
                    {row.primary}
                  </span>
                  {row.secondary ? (
                    <span className="bm-card__link-secondary allow-select">
                      {row.secondary}
                    </span>
                  ) : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {hidden > 0 ? (
        <button
          type="button"
          className="bm-card__links-more"
          onClick={onOpen}
        >
          另有 {hidden} 条，进详情查看
        </button>
      ) : null}
    </div>
  );
}

/** 色花卡片：标题 / ed2k·磁力链接 / 底栏 */
export function ResourceCard({
  item,
  keywords = [],
  onOpen,
  badge,
  cropRegion: _cropRegion,
}: {
  item: ResourceItem;
  keywords?: string[];
  onOpen: (hash: string) => void;
  badge?: string;
  /** 保留兼容；列表不再展示预览图 */
  cropRegion?: string;
}) {
  const [msg, setMsg] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const haptics = useHaptics();
  const view = normalizeResourceView(item);
  const title = view.title || view.name || view.hash;
  const kind = normalizeLinkKind(view.link_kind);
  const kindLabel = LINK_KIND_LABEL[view.link_kind] || LINK_KIND_LABEL[kind] || '链接';
  const count = view.files_count || view.files?.length || 0;
  const links = linksForResource(view);
  const copyTextAll = getEd2kCopyText(view);

  const cardRef = useLongPress<HTMLElement>(() => {
    haptics.trigger('nudge');
    setMenuOpen(true);
  }, {
    onHaptic: () => haptics.trigger('nudge'),
  });

  async function onCopyLink(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!copyTextAll?.trim()) {
      setMsg(kind === 'stub' ? '暂无可用链接' : '无链接可复制');
      return;
    }
    const ok = await copyText(copyTextAll);
    setMsg(
      ok
        ? kind === 'magnet'
          ? '已复制磁力'
          : kind === '115share'
            ? '已复制分享'
            : '已复制链接'
        : '复制失败',
    );
  }

  async function copyFromMenu() {
    if (!copyTextAll?.trim()) {
      setMsg(kind === 'stub' ? '暂无可用链接' : '无链接可复制');
      return;
    }
    const ok = await copyText(copyTextAll);
    setMsg(ok ? '已复制链接' : '复制失败');
  }

  return (
    <article className="bm-card" ref={cardRef}>
      <ContextMenu
        open={menuOpen}
        title={title}
        onClose={() => setMenuOpen(false)}
        actions={[
          {
            label: '打开详情',
            onSelect: () => onOpen(view.hash),
          },
          {
            label: copyTextAll?.trim() ? '复制链接' : '无链接可复制',
            onSelect: () => void copyFromMenu(),
          },
        ]}
      />
      {badge ? <span className="bm-card__badge">{badge}</span> : null}
      <header className={`bm-card__head${badge ? ' bm-card__head--badged' : ''}`}>
        <button
          type="button"
          className="bm-card__title allow-select"
          title={title}
          onClick={() => onOpen(view.hash)}
        >
          <span
            className="bm-card__title-text"
            dangerouslySetInnerHTML={{
              __html: parseHighlight(title, keywords),
            }}
          />
        </button>
      </header>
      <CardLinksBody
        links={links}
        kind={kind}
        onOpen={() => onOpen(view.hash)}
      />
      <footer className="bm-card__foot">
        <button
          type="button"
          className="bm-card__magnet"
          onClick={(e) => void onCopyLink(e)}
        >
          <span aria-hidden="true">{kind === 'magnet' ? '🧲' : '🔗'}</span>
          {kindLabel}
        </button>
        <div className="bm-card__meta">
          {view.size ? (
            <span className="bm-card__chip">大小 {formatByteSize(view.size)}</span>
          ) : null}
          {count > 0 ? (
            <span className="bm-card__chip">文件 {count}</span>
          ) : null}
          {view.board_name ? (
            <span className="bm-card__chip">{view.board_name}</span>
          ) : null}
          {view.created_at ? (
            <span className="bm-card__chip">创建 {formatDate(view.created_at)}</span>
          ) : null}
        </div>
      </footer>
      <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg>
    </article>
  );
}
