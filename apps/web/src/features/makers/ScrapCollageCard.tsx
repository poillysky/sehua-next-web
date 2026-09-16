'use client';

import { useEffect, useState } from 'react';
import { CircleUserRound, Folder } from 'lucide-react';
import {
  lookupScrapActressAvatarUrls,
  peekActressAvatarPosterApi,
  rememberActressAvatarPosterApis,
} from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import {
  SCRAP_COLLAGE_COVER_OPTS,
  useScrapLocalCover,
} from './useScrapLocalCover';

function isUnlabeledActress(name: string): boolean {
  const t = String(name || '').trim();
  return t === '未标注女优' || t === '未标注' || t === '(unknown)';
}

function isActressAvatarApi(api?: string): boolean {
  const s = String(api || '');
  return (
    s.includes('/_actress/') ||
    s.includes('%2F_actress%2F') ||
    s.includes('%2f_actress%2f')
  );
}

/** 女优墙只允许真人头像；作品 poster 一律丢弃。 */
function resolveActressCardPosterApi(
  name: string,
  posterApi?: string,
  posterApis?: string[],
): string {
  if (isUnlabeledActress(name)) return '';
  if (isActressAvatarApi(posterApi)) return String(posterApi);
  for (const p of posterApis || []) {
    if (isActressAvatarApi(p)) return String(p);
  }
  return peekActressAvatarPosterApi(name);
}

/** Emby 式 2×2 拼贴封面（厂牌 / 标签） */
export function ScrapCollageCard({
  title,
  count,
  blurb,
  posterApi,
  posterApis,
  coverUrl,
  itemId,
  overlay,
  onClick,
  /** 推荐货架默认单图，显著减少首屏请求；文件夹全页可开 mosaic */
  mosaic = false,
}: {
  title: string;
  count?: number;
  /** 厂牌/前缀短介绍（中日英名等） */
  blurb?: string;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  itemId?: string;
  /** 标题叠在封面上（标签） */
  overlay?: boolean;
  onClick: () => void;
  mosaic?: boolean;
}) {
  const { src, posters, onError } = useScrapLocalCover({
    posterApi,
    posterApis,
    coverUrl,
    itemId,
    maxPosters: mosaic ? 4 : 1,
    ...SCRAP_COLLAGE_COVER_OPTS,
  });
  const [gone, setGone] = useState<Record<number, boolean>>({});
  const intro = String(blurb || '').trim();

  return (
    <button
      type="button"
      className={
        overlay
          ? 'makers-collage makers-collage--overlay'
          : 'makers-collage'
      }
      onClick={onClick}
    >
      <span className="makers-collage__frame">
        {!mosaic || posters.length <= 1 ? (
          <>
            <span className="makers-collage__ph" aria-hidden>
              {title.slice(0, 1)}
            </span>
            {src ? (
              <SoftImg
                className="makers-collage__full"
                src={src}
                loading="eager"
                onError={onError}
              />
            ) : null}
          </>
        ) : (
          <span className="makers-collage__mosaic" aria-hidden>
            {Array.from({ length: 4 }).map((_, i) => {
              const cell = posters[i] || posters[i % posters.length];
              if (!cell || gone[i]) {
                return (
                  <span
                    key={i}
                    className="makers-collage__cell makers-collage__ph"
                  />
                );
              }
              return (
                <SoftImg
                  key={i}
                  className="makers-collage__cell"
                  src={cell}
                  loading="eager"
                  onError={() => setGone((g) => ({ ...g, [i]: true }))}
                />
              );
            })}
          </span>
        )}
        {count != null ? (
          <span className="makers-collage__count" aria-label={`${count} 项`}>
            {count.toLocaleString()}
          </span>
        ) : null}
        {overlay ? (
          <span className="makers-collage__label allow-select">{title}</span>
        ) : null}
      </span>
      {/* 标签也保留封面下说明，避免叠加层被图盖住时看不到字 */}
      <span className="makers-collage__caption">
        <span className="makers-collage__title allow-select">{title}</span>
        {intro ? (
          <span className="makers-collage__blurb">{intro}</span>
        ) : null}
      </span>
    </button>
  );
}

/** 标签一级：纯文字卡片（无封面） */
export function ScrapTagCard({
  title,
  count,
  onClick,
}: {
  title: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button type="button" className="makers-tag-card" onClick={onClick}>
      <span className="makers-tag-card__name allow-select">{title}</span>
      {count != null ? (
        <span className="makers-tag-card__count">
          <span className="makers-tag-card__count-num">
            {count.toLocaleString()}
          </span>
          <span className="makers-tag-card__count-unit">部</span>
        </span>
      ) : null}
    </button>
  );
}

/** 女优：竖版封面墙 */
export function ScrapActressCard({
  title,
  count,
  posterApi,
  posterApis,
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  itemId?: string;
  onClick: () => void;
}) {
  const unlabeled = isUnlabeledActress(title);
  const [avatarApi, setAvatarApi] = useState(() =>
    resolveActressCardPosterApi(title, posterApi, posterApis),
  );

  useEffect(() => {
    if (unlabeled) {
      setAvatarApi('');
      return;
    }
    // 分面已给头像路径则直接用
    if (isActressAvatarApi(posterApi)) {
      setAvatarApi(String(posterApi));
      return;
    }
    const guess = resolveActressCardPosterApi(title, posterApi, posterApis);
    setAvatarApi(guess);
    let cancelled = false;
    // 异写名（松本芽衣→芽依）必须问后端，前端乐观拼路径会 404
    void lookupScrapActressAvatarUrls([title])
      .then((m) => {
        if (cancelled) return;
        rememberActressAvatarPosterApis(m || {});
        const hit = String((m || {})[title] || '').trim();
        if (hit) setAvatarApi(hit);
        else if (!guess) setAvatarApi('');
      })
      .catch(() => {
        /* 保持乐观路径 */
      });
    return () => {
      cancelled = true;
    };
  }, [title, posterApi, posterApis, unlabeled]);

  const { src, onError } = useScrapLocalCover({
    posterApi: avatarApi || undefined,
    // 女优墙禁止拼贴作品封面（否则会吃到 UMD-557/poster.jpg）
    posterApis: undefined,
    coverUrl: undefined,
    itemId: undefined,
    w: 320,
    prefer: 'poster',
    rp: false,
  });

  return (
    <button
      type="button"
      className="makers-actress"
      data-avatar={avatarApi ? '1' : undefined}
      data-unlabeled={unlabeled ? '1' : undefined}
      onClick={onClick}
    >
      <span className="makers-actress__frame">
        <span className="makers-actress__ph" aria-hidden>
          {unlabeled ? (
            <CircleUserRound size={28} strokeWidth={1.55} />
          ) : (
            title.slice(0, 1)
          )}
        </span>
        {!unlabeled && src ? (
          <SoftImg
            src={src}
            loading="eager"
            fetchPriority="high"
            onError={onError}
          />
        ) : null}
      </span>
      <span className="makers-actress__caption">
        <span className="makers-actress__name allow-select">{title}</span>
        <span className="makers-actress__count">{count} 部</span>
      </span>
    </button>
  );
}

/** Emby 式文件夹卡片 */
export function ScrapFolderCard({
  title,
  count,
  posterApi,
  posterApis,
  coverUrl,
  itemId,
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  itemId?: string;
  onClick: () => void;
}) {
  const { src, onError } = useScrapLocalCover({
    posterApi,
    posterApis,
    coverUrl,
    itemId,
    ...SCRAP_COLLAGE_COVER_OPTS,
  });

  return (
    <button type="button" className="makers-folder" onClick={onClick}>
      <span className="makers-folder__frame">
        <span className="makers-folder__ph" aria-hidden>
          <Folder size={28} strokeWidth={1.6} />
        </span>
        {src ? (
          <SoftImg
            src={src}
            loading="eager"
            fetchPriority="high"
            onError={onError}
          />
        ) : null}
        <span className="makers-folder__badge" aria-hidden>
          <Folder size={14} strokeWidth={2.2} />
        </span>
      </span>
      <span className="makers-folder__caption">
        <span className="makers-folder__title allow-select">{title}</span>
        <span className="makers-folder__count">{count} 项</span>
      </span>
    </button>
  );
}
