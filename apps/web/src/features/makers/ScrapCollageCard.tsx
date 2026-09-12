'use client';

import { useState } from 'react';
import { Folder } from 'lucide-react';
import {
  SCRAP_COLLAGE_COVER_OPTS,
  useScrapLocalCover,
} from './useScrapLocalCover';

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
          src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              className="makers-collage__full"
              src={src}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              onError={onError}
            />
          ) : (
            <span className="makers-collage__ph" aria-hidden>
              {title.slice(0, 1)}
            </span>
          )
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
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={i}
                  className="makers-collage__cell"
                  src={cell}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
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
    <button
      type="button"
      className="makers-actress"
      data-avatar={posterApi?.includes('/_actress/') ? '1' : undefined}
      onClick={onClick}
    >
      <span className="makers-actress__frame">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={onError}
          />
        ) : (
          <span className="makers-actress__ph">{title.slice(0, 1)}</span>
        )}
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
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={onError}
          />
        ) : (
          <span className="makers-folder__ph">
            <Folder size={28} strokeWidth={1.6} aria-hidden />
          </span>
        )}
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
