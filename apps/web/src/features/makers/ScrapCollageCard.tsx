'use client';

import { useEffect, useState } from 'react';
import { Folder } from 'lucide-react';
import { scrapLibraryCoverUrl, SCRAP_COLLAGE_THUMB_W } from '@/lib/api';

const COVER_OPTS = { w: SCRAP_COLLAGE_THUMB_W, rp: true as const };

function resolvePosters(
  posterApi: string | undefined,
  posterApis: string[] | undefined,
  maxPosters: number,
  coverUrl?: string,
) {
  const list = (posterApis || [])
    .map((p) =>
      scrapLibraryCoverUrl(
        { posterApi: p },
        // 横图 → 右裁竖幅，统一竖封面
        COVER_OPTS,
      ),
    )
    .filter(Boolean);
  if (list.length) return list.slice(0, maxPosters);
  const one = scrapLibraryCoverUrl(
    { posterApi, coverUrl },
    COVER_OPTS,
  );
  return one ? [one] : [];
}

function useCoverSrc(
  posterApi: string | undefined,
  posterApis: string[] | undefined,
  coverUrl: string | undefined,
) {
  const primary = resolvePosters(posterApi, posterApis, 1, coverUrl)[0] || '';
  const remoteOnly =
    scrapLibraryCoverUrl({ coverUrl }, COVER_OPTS) || '';
  const [src, setSrc] = useState(primary);

  useEffect(() => {
    setSrc(primary);
  }, [primary]);

  const onError = () => {
    if (remoteOnly && src !== remoteOnly) {
      setSrc(remoteOnly);
      return;
    }
    setSrc('');
  };

  return { src, onError };
}

/** Emby 式 2×2 拼贴封面（厂牌 / 标签） */
export function ScrapCollageCard({
  title,
  count,
  posterApi,
  posterApis,
  coverUrl,
  overlay,
  onClick,
  /** 推荐货架默认单图，显著减少首屏请求；文件夹全页可开 mosaic */
  mosaic = false,
}: {
  title: string;
  count?: number;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  /** 标题叠在封面上（标签） */
  overlay?: boolean;
  onClick: () => void;
  mosaic?: boolean;
}) {
  const posters = resolvePosters(posterApi, posterApis, mosaic ? 4 : 1, coverUrl);
  const { src, onError } = useCoverSrc(posterApi, posterApis, coverUrl);
  const [gone, setGone] = useState<Record<number, boolean>>({});

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
        {overlay ? (
          <span className="makers-collage__label allow-select">{title}</span>
        ) : null}
      </span>
      {/* 标签也保留封面下说明，避免叠加层被图盖住时看不到字 */}
      <span className="makers-collage__caption">
        <span className="makers-collage__title allow-select">{title}</span>
        {count != null ? (
          <span className="makers-collage__count">{count} 项</span>
        ) : null}
      </span>
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
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  onClick: () => void;
}) {
  const { src, onError } = useCoverSrc(posterApi, posterApis, coverUrl);

  return (
    <button type="button" className="makers-actress" onClick={onClick}>
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
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  posterApis?: string[];
  coverUrl?: string;
  onClick: () => void;
}) {
  const { src, onError } = useCoverSrc(posterApi, posterApis, coverUrl);

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
