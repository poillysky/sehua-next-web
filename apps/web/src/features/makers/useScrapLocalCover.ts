'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ensureScrapLibraryPoster,
  scrapLibraryCoverUrl,
  SCRAP_COLLAGE_THUMB_W,
  SCRAP_LIST_THUMB_W,
} from '@/lib/api';

export type ScrapLocalCoverOpts = {
  posterApi?: string;
  thumbApi?: string;
  posterApis?: string[];
  /** 仅作下载源，绝不作为 img src */
  coverUrl?: string;
  itemId?: string;
  w?: number;
  rp?: boolean;
  /** 列表/货架用 thumb（右裁竖图）；详情用 poster 高清 */
  prefer?: 'thumb' | 'poster';
  maxPosters?: number;
};

function localUrl(
  posterApi: string | undefined,
  thumbApi: string | undefined,
  opts: { w: number; prefer: 'thumb' | 'poster'; rp?: boolean },
) {
  const preferThumb = opts.prefer === 'thumb';
  let api = '';
  let rp = opts.rp;
  if (preferThumb) {
    if (thumbApi) {
      api = thumbApi;
      rp = true; // 横 thumb → 右裁竖图
    } else if (posterApi) {
      api = posterApi;
      rp = false; // 已是竖版 poster，勿再裁
    }
  } else if (posterApi) {
    api = posterApi;
    rp = false;
  } else if (thumbApi) {
    api = thumbApi;
    rp = opts.rp ?? true;
  }
  if (!api) return '';
  return (
    scrapLibraryCoverUrl(
      preferThumb
        ? { posterApi: '', thumbApi: api, coverUrl: '' }
        : { posterApi: api, thumbApi: '', coverUrl: '' },
      {
        w: opts.w,
        prefer: preferThumb ? 'thumb' : 'poster',
        rp: Boolean(rp),
      },
    ) || ''
  );
}

/**
 * 片商封面统一：
 * - 列表/货架：prefer=thumb + 右裁竖图
 * - 详情：prefer=poster 高清竖图
 * - 只读本地；缺图则落盘后再显示
 */
export function useScrapLocalCover(opts: ScrapLocalCoverOpts) {
  const prefer = opts.prefer ?? 'thumb';
  const w =
    opts.w ??
    (prefer === 'poster' ? 720 : SCRAP_COLLAGE_THUMB_W);
  const maxPosters = opts.maxPosters ?? 4;
  const coverOpts = useMemo(
    () => ({ w, prefer, rp: opts.rp }),
    [w, prefer, opts.rp],
  );

  const locals = useMemo(() => {
    // 拼贴多图：路径已由后端按 thumb 优先选出；thumb/fanart 右裁竖图
    const fromList = (opts.posterApis || [])
      .map((p) => {
        const looksWide = /thumb|fanart|landscape/i.test(String(p));
        return (
          scrapLibraryCoverUrl(
            { posterApi: p, coverUrl: '' },
            {
              w: coverOpts.w,
              prefer: 'poster',
              rp: prefer === 'thumb' && looksWide,
            },
          ) || ''
        );
      })
      .filter(Boolean);
    if (fromList.length) return fromList.slice(0, maxPosters);
    const one = localUrl(opts.posterApi, opts.thumbApi, coverOpts);
    return one ? [one] : [];
  }, [
    opts.posterApi,
    opts.thumbApi,
    opts.posterApis,
    coverOpts,
    maxPosters,
    prefer,
  ]);

  const [posters, setPosters] = useState<string[]>(locals);
  const [src, setSrc] = useState(locals[0] || '');
  const [ensuring, setEnsuring] = useState(false);
  const ensuredKey = useRef('');

  const localKey = `${locals.length}:${locals[0] || ''}`;

  useEffect(() => {
    setPosters(locals);
    setSrc(locals[0] || '');
  }, [localKey, locals]);

  useEffect(() => {
    const id = String(opts.itemId || '').trim();
    const cover = String(opts.coverUrl || '').trim();
    if (locals[0]) return;
    if (!id && !cover) return;
    const key = `${id}|${cover}|${prefer}`;
    if (ensuredKey.current === key) return;
    ensuredKey.current = key;
    let cancelled = false;
    setEnsuring(true);
    void (async () => {
      try {
        const data = await ensureScrapLibraryPoster({
          itemId: id,
          coverUrl: cover,
        });
        if (cancelled) return;
        // 落盘的是 poster.jpg；列表无 thumb 时用 poster 竖图兜底
        const api = String(data?.posterApi || '').trim();
        if (!api) return;
        const url = localUrl(api, undefined, coverOpts);
        if (!url) return;
        setSrc(url);
        setPosters([url]);
      } finally {
        if (!cancelled) setEnsuring(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.itemId, opts.coverUrl, localKey, coverOpts, prefer]);

  const onError = () => {
    const id = String(opts.itemId || '').trim();
    const cover = String(opts.coverUrl || '').trim();
    if (!id && !cover) {
      setSrc('');
      return;
    }
    void (async () => {
      const data = await ensureScrapLibraryPoster({
        itemId: id,
        coverUrl: cover,
      });
      const api = String(data?.posterApi || '').trim();
      const url = api ? localUrl(api, undefined, coverOpts) : '';
      if (url && url !== src) {
        setSrc(url);
        setPosters([url]);
        return;
      }
      setSrc('');
    })();
  };

  return { src, posters, onError, ensuring };
}

/** 列表 / 货架 / 厂牌墙：thumb 右裁竖图 */
export const SCRAP_POSTER_COVER_OPTS = {
  w: SCRAP_LIST_THUMB_W,
  prefer: 'thumb' as const,
  rp: true as const,
};

export const SCRAP_COLLAGE_COVER_OPTS = {
  w: SCRAP_COLLAGE_THUMB_W,
  prefer: 'thumb' as const,
  rp: true as const,
};

/** 详情主图：poster 高清 */
export const SCRAP_DETAIL_COVER_OPTS = {
  w: 720,
  prefer: 'poster' as const,
  rp: false as const,
};
