'use client';

import { useState } from 'react';
import { Folder } from 'lucide-react';
import { scrapLibraryCoverUrl } from '@/lib/api';

function resolvePosters(posterApi?: string, posterApis?: string[]) {
  const list = (posterApis || [])
    .map((p) => scrapLibraryCoverUrl({ posterApi: p }))
    .filter(Boolean);
  if (list.length) return list.slice(0, 4);
  const one = scrapLibraryCoverUrl({ posterApi });
  return one ? [one] : [];
}

/** Emby 式 2×2 拼贴封面（厂牌 / 标签） */
export function ScrapCollageCard({
  title,
  count,
  posterApi,
  posterApis,
  overlay,
  onClick,
}: {
  title: string;
  count?: number;
  posterApi?: string;
  posterApis?: string[];
  /** 标题叠在封面上（标签） */
  overlay?: boolean;
  onClick: () => void;
}) {
  const posters = resolvePosters(posterApi, posterApis);
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
      <span className="makers-collage__frame" aria-hidden>
        {posters.length === 0 ? (
          <span className="makers-collage__ph">{title.slice(0, 1)}</span>
        ) : posters.length === 1 ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            className="makers-collage__full"
            src={posters[0]}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setGone({ 0: true })}
          />
        ) : (
          <span className="makers-collage__mosaic">
            {Array.from({ length: 4 }).map((_, i) => {
              const src = posters[i] || posters[i % posters.length];
              if (!src || gone[i]) {
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
                  src={src}
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
      {!overlay ? (
        <span className="makers-collage__caption">
          <span className="makers-collage__title allow-select">{title}</span>
          {count != null ? (
            <span className="makers-collage__count">{count} 项</span>
          ) : null}
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
  onClick: () => void;
}) {
  const posters = resolvePosters(posterApi, posterApis);
  const [gone, setGone] = useState(false);
  const cover = posters[0];

  return (
    <button type="button" className="makers-actress" onClick={onClick}>
      <span className="makers-actress__frame">
        {cover && !gone ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setGone(true)}
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
  onClick,
}: {
  title: string;
  count: number;
  posterApi?: string;
  posterApis?: string[];
  onClick: () => void;
}) {
  const posters = resolvePosters(posterApi, posterApis);
  const [gone, setGone] = useState(false);
  const cover = posters[0];

  return (
    <button type="button" className="makers-folder" onClick={onClick}>
      <span className="makers-folder__frame">
        {cover && !gone ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setGone(true)}
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
