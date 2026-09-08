'use client';

import { useEffect, useRef, useState, type MouseEvent } from 'react';
import type { ResourceItem } from '@/types/resource';
import { formatByteSize, formatDate, parseHighlight } from '@/lib/format';
import { normalizeResourceView } from '@/lib/resourceView';
import { copyText } from '@/lib/clipboard';
import { COVER_LIST_THUMB_W, proxiedCoverUrl } from '@/lib/api';
import { AppMsg } from '@/components/ui/AppMsg';
import { ContextMenu } from '@/components/ui/ContextMenu';
import { useLongPress } from '@/hooks/useLongPress';
import { useHaptics } from '@/shell';
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
const PREVIEW_PRELOAD_MAX = 6;
/** 过小图视为占位/防盗链页；与详情 PreviewGrid 一致 */
const MIN_PREVIEW_PX = 48;
/** 单卡并行预载上限（手机弱网少打并发） */
const PREVIEW_PARALLEL = 2;

type PreviewOrient = 'landscape' | 'portrait';

type PreviewSlot = {
  src: string;
  index: number;
  orient: PreviewOrient;
  pending?: boolean;
};

/**
 * 只展示「已加载成功」的前缀，失败跳过；遇到尚未加载的停住并最多留 1 个尾部骨架。
 * 避免：默认竖图多占位 → 横图 onload 后重排；或两侧已出图、中间仍空槽。
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
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [inView, setInView] = useState(false);
  const [failed, setFailed] = useState<Record<number, true>>({});
  const [orientations, setOrientations] = useState<
    Record<number, PreviewOrient>
  >({});
  const proxied = images
    .map((u) => proxiedCoverUrl(u, { w: COVER_LIST_THUMB_W }))
    .filter(Boolean);
  const proxiedKey = proxied.join('\0');

  const markFailed = (index: number) => {
    setFailed((prev) => (prev[index] ? prev : { ...prev, [index]: true }));
  };

  // 进视口附近再拉图；root 用滚动容器，避免设备框内误判
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }
    const scrollRoot =
      el.closest('.app-body') instanceof HTMLElement
        ? (el.closest('.app-body') as HTMLElement)
        : null;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          io.disconnect();
        }
      },
      { root: scrollRoot, rootMargin: '240px 0px', threshold: 0.01 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // 与详情页一致：并行预探方向；限并发，避免串行超时误杀后续图
  useEffect(() => {
    setFailed({});
    setOrientations({});
    if (!inView || !proxied.length) return;

    let cancelled = false;
    const loaders: HTMLImageElement[] = [];
    const targets = proxied.slice(0, PREVIEW_PRELOAD_MAX);
    let cursor = 0;
    let inflight = 0;

    const pump = () => {
      while (!cancelled && inflight < PREVIEW_PARALLEL && cursor < targets.length) {
        const index = cursor;
        const src = targets[index];
        cursor += 1;
        inflight += 1;
        const img = new Image();
        loaders.push(img);
        const done = () => {
          inflight -= 1;
          pump();
        };
        const applyOk = () => {
          if (cancelled) return;
          if (
            !img.naturalWidth ||
            !img.naturalHeight ||
            img.naturalWidth < MIN_PREVIEW_PX ||
            img.naturalHeight < MIN_PREVIEW_PX
          ) {
            markFailed(index);
            done();
            return;
          }
          const next: PreviewOrient =
            img.naturalWidth > img.naturalHeight ? 'landscape' : 'portrait';
          setOrientations((prev) =>
            prev[index] === next ? prev : { ...prev, [index]: next },
          );
          done();
        };
        const applyErr = () => {
          if (cancelled) return;
          markFailed(index);
          done();
        };
        img.onload = applyOk;
        img.onerror = applyErr;
        img.src = src;
        if (img.complete && img.naturalWidth > 0) applyOk();
      }
    };

    pump();

    return () => {
      cancelled = true;
      for (const img of loaders) {
        img.onload = null;
        img.onerror = null;
        img.src = '';
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView, proxiedKey]);

  const visible = packPreviewImages(proxied, failed, orientations);
  if (!proxied.length) return null;
  const preloadCount = Math.min(proxied.length, PREVIEW_PRELOAD_MAX);
  const stillLoading =
    inView &&
    targetsStillLoading(preloadCount, failed, orientations);
  if (
    !visible.length &&
    !stillLoading &&
    Array.from({ length: preloadCount }, (_, i) => i).every((i) => failed[i])
  ) {
    return null;
  }

  return (
    <div ref={rootRef} className="bm-card__body bm-card__body--preview">
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
              {!pending ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={src}
                  alt=""
                  className="bm-card__preview-img"
                  loading="eager"
                  decoding="async"
                  onError={() => markFailed(index)}
                />
              ) : null}
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

function targetsStillLoading(
  count: number,
  failed: Record<number, true>,
  orientations: Record<number, PreviewOrient>,
) {
  for (let i = 0; i < count; i += 1) {
    if (!failed[i] && !orientations[i]) return true;
  }
  return false;
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
  const [menuOpen, setMenuOpen] = useState(false);
  const haptics = useHaptics();
  const view = normalizeResourceView(item);
  const title = view.title || view.name || view.hash;
  const kind = normalizeLinkKind(view.link_kind);
  const kindLabel = LINK_KIND_LABEL[view.link_kind] || LINK_KIND_LABEL[kind] || '链接';
  const count = view.files_count || view.files?.length || 0;
  const copyTextAll = getEd2kCopyText(view);
  const previews = view.preview_images || [];

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
