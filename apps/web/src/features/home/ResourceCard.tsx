'use client';

import { useEffect, useState, type MouseEvent } from 'react';
import type { ResourceItem } from '@/types/resource';
import { formatByteSize, formatDate, parseHighlight } from '@/lib/format';
import { normalizeResourceView } from '@/lib/resourceView';
import { copyText } from '@/lib/clipboard';
import { proxiedCoverUrl } from '@/lib/api';
import { AppMsg } from '@/components/ui/AppMsg';
import { getEd2kCopyText, normalizeLinkKind } from '@/lib/detailResource';

const LINK_KIND_LABEL: Record<string, string> = {
  magnet: '磁力',
  ed2k: 'ed2k',
  share115: '115',
  '115share': '115',
  unavailable: '占位',
  stub: '占位',
};

const PREVIEW_SLOT_MAX = 5;
/** 预加载上限：够填满 5 格即可，避免一次打太多图 */
const PREVIEW_PRELOAD_MAX = 8;
/** 过小图视为占位/防盗链页；与详情 PreviewGrid 一致 */
const MIN_PREVIEW_PX = 48;
/** 单张预加载超时，避免 cover-proxy 挂起时骨架永远 pending */
const PREVIEW_LOAD_TIMEOUT_MS = 20_000;

type PreviewOrient = 'landscape' | 'portrait';

type PreviewSlot = {
  src: string;
  index: number;
  orient: PreviewOrient;
  pending?: boolean;
};

/**
 * 只展示「已加载成功」的前缀，失败跳过；遇到尚未加载的停住并最多留 1 个尾部骨架。
 * 避免：默认竖图多占位 → 横图onload 后重排；或两侧已出图、中间仍空槽。
 */
function packPreviewImages(
  proxied: string[],
  failed: Record<number, true>,
  orientations: Record<number, PreviewOrient>,
): PreviewSlot[] {
  const picked: PreviewSlot[] = [];
  let slots = 0;
  for (let index = 0; index < proxied.length; index++) {
    if (failed[index]) continue;
    const orient = orientations[index];
    if (!orient) {
      // 尾部最多 1 个等待槽（按横图 2 格预留，减少随后跳动）
      if (slots + 2 <= PREVIEW_SLOT_MAX) {
        picked.push({
          src: proxied[index],
          index,
          orient: 'landscape',
          pending: true,
        });
      }
      break;
    }
    const cost = orient === 'landscape' ? 2 : 1;
    if (slots + cost > PREVIEW_SLOT_MAX) break;
    picked.push({ src: proxied[index], index, orient });
    slots += cost;
  }
  return picked;
}

function CardPreviewBody({
  images,
  onOpen,
}: {
  images: string[];
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState<Record<number, true>>({});
  const [orientations, setOrientations] = useState<
    Record<number, PreviewOrient>
  >({});
  const proxied = images.map((u) => proxiedCoverUrl(u)).filter(Boolean);
  const proxiedKey = proxied.join('\0');

  const markFailed = (index: number) => {
    setFailed((prev) => (prev[index] ? prev : { ...prev, [index]: true }));
  };

  const handleLoad = (index: number, img: HTMLImageElement) => {
    if (
      !img.naturalWidth ||
      !img.naturalHeight ||
      img.naturalWidth < MIN_PREVIEW_PX ||
      img.naturalHeight < MIN_PREVIEW_PX
    ) {
      markFailed(index);
      return;
    }
    const next: PreviewOrient =
      img.naturalWidth > img.naturalHeight ? 'landscape' : 'portrait';
    setOrientations((prev) =>
      prev[index] === next ? prev : { ...prev, [index]: next },
    );
  };

  /** 逐张走 proxy，避免列表多卡同时打满图床/代理导致 502 */
  const canLoad = (index: number) => {
    for (let i = 0; i < index; i++) {
      if (!orientations[i] && !failed[i]) return false;
    }
    return true;
  };

  // 超时兜底：proxy 502 / 挂起时跳过该张，继续试下一张
  useEffect(() => {
    setFailed({});
    setOrientations({});
    if (!proxied.length) return;

    let cancelled = false;
    const timers = proxied.slice(0, PREVIEW_PRELOAD_MAX).map((_, index) =>
      window.setTimeout(() => {
        if (cancelled) return;
        setOrientations((prev) => {
          if (prev[index]) return prev;
          markFailed(index);
          return prev;
        });
      }, PREVIEW_LOAD_TIMEOUT_MS),
    );

    return () => {
      cancelled = true;
      for (const id of timers) window.clearTimeout(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proxiedKey]);

  const visible = packPreviewImages(proxied, failed, orientations);
  if (!proxied.length) return null;
  const preloadCount = Math.min(proxied.length, PREVIEW_PRELOAD_MAX);
  if (
    !visible.length &&
    Array.from({ length: preloadCount }, (_, i) => i).every((i) => failed[i])
  ) {
    return null;
  }

  return (
    <div className="bm-card__body bm-card__body--preview">
      {visible.length > 0 ? (
        <button
          type="button"
          className="bm-card__preview-hit bm-card__preview-strip"
          onClick={onOpen}
          aria-label="查看详情"
        >
          {visible.map(({ src, index, orient, pending }) => (
            <span
              key={`${src}-${index}`}
              className={`bm-card__preview-slot bm-card__preview-slot--${orient}${
                pending ? ' bm-card__preview-slot--pending' : ''
              }`}
            >
              {/* 槽内直接走 cover-proxy 加载；pending 时也发请求，勿用隐藏 Image() 预探 */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={canLoad(index) ? src : undefined}
                alt=""
                className={`bm-card__preview-img${
                  pending ? ' bm-card__preview-img--loading' : ''
                }`}
                onLoad={(e) => handleLoad(index, e.currentTarget)}
                onError={() => markFailed(index)}
              />
            </span>
          ))}
        </button>
      ) : (
        <button
          type="button"
          className="bm-card__preview-hit bm-card__preview-strip"
          onClick={onOpen}
          aria-label="查看详情"
        >
          <span className="bm-card__preview-slot bm-card__preview-slot--landscape bm-card__preview-slot--pending" />
        </button>
      )}
    </div>
  );
}

/** 对齐 Bitmagnet 卡片：标题 / 预览图 / 链接底栏 */
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
  /** 保留兼容；列表预览图不裁剪，裁剪下钻到详情 */
  cropRegion?: string;
}) {
  const [msg, setMsg] = useState('');
  const view = normalizeResourceView(item);
  const title = view.title || view.name || view.hash;
  const kind = normalizeLinkKind(view.link_kind);
  const kindLabel = LINK_KIND_LABEL[view.link_kind] || LINK_KIND_LABEL[kind] || '链接';
  const count = view.files_count || view.files?.length || 0;
  const copyTextAll = getEd2kCopyText(view);
  const previews = view.preview_images || [];

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

  return (
    <article className="bm-card">
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
      <CardPreviewBody
        images={previews}
        onOpen={() => onOpen(view.hash)}
      />
      <footer className="bm-card__foot">
        <button
          type="button"
          className="bm-card__magnet"
          onClick={(e) => void onCopyLink(e)}
        >
          <span aria-hidden>{kind === 'magnet' ? '🧲' : '🔗'}</span>
          {kindLabel}
        </button>
        <div className="bm-card__meta">
          {view.size ? <span>大小 {formatByteSize(view.size)}</span> : null}
          {count > 0 ? <span>文件 {count}</span> : null}
          {view.board_name ? <span>{view.board_name}</span> : null}
          {view.created_at ? (
            <span>创建 {formatDate(view.created_at)}</span>
          ) : null}
        </div>
      </footer>
      <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg>
    </article>
  );
}
