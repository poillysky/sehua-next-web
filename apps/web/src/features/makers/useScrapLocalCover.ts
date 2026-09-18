'use client';

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from 'react';
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
  /** 列表缩略 / 详情高清；选图一律 poster 优先，无 poster 才用 thumb 右裁 */
  prefer?: 'thumb' | 'poster';
  maxPosters?: number;
};

function localUrl(
  posterApi: string | undefined,
  thumbApi: string | undefined,
  opts: { w: number; prefer: 'thumb' | 'poster'; rp?: boolean },
) {
  let api = '';
  let rp = false;
  let useThumb = false;
  if (posterApi) {
    // 默认 poster 原样。有码列表显式 rp：横图右裁，竖图服务端不裁。
    api = posterApi;
    rp = Boolean(opts.rp);
  } else if (thumbApi) {
    // 无 poster 才用横 thumb，服务端 rp 右裁竖幅
    api = thumbApi;
    useThumb = true;
    rp = true;
  }
  if (!api) return '';
  return (
    scrapLibraryCoverUrl(
      useThumb
        ? { posterApi: '', thumbApi: api, coverUrl: '' }
        : { posterApi: api, thumbApi: '', coverUrl: '' },
      {
        w: opts.w,
        prefer: useThumb ? 'thumb' : 'poster',
        rp: Boolean(rp),
      },
    ) || ''
  );
}

/**
 * 片商封面统一：
 * - 有 poster 用 poster；无 poster 才用 thumb + 右裁
 * - prefer 只影响默认宽度（列表缩略 / 详情高清）
 * - 只读本地；缺图则落盘后再显示
 */
export function useScrapLocalCover(opts: ScrapLocalCoverOpts) {
  const prefer = opts.prefer ?? 'poster';
  const w =
    opts.w ??
    (prefer === 'poster' ? 720 : SCRAP_COLLAGE_THUMB_W);
  const maxPosters = opts.maxPosters ?? 4;
  const coverOpts = useMemo(
    () => ({ w, prefer, rp: opts.rp }),
    [w, prefer, opts.rp],
  );

  // 调用方常写 posterApis={[api]}，引用每帧都变；用序列化键稳定 memo
  const posterApisKey = (opts.posterApis || []).join('\0');

  const locals = useMemo(() => {
    const apis = posterApisKey ? posterApisKey.split('\0') : [];
    // 拼贴多图：仅 thumb/fanart/landscape 路径才右裁；poster 原样缩略
    const fromList = apis
      .map((p) => {
        const looksWide = /thumb|fanart|landscape/i.test(String(p));
        return (
          scrapLibraryCoverUrl(
            { posterApi: p, coverUrl: '' },
            {
              w: coverOpts.w,
              prefer: 'poster',
              rp: looksWide,
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
    posterApisKey,
    coverOpts,
    maxPosters,
    prefer,
  ]);

  const [posters, setPosters] = useState<string[]>(locals);
  const [src, setSrc] = useState(locals[0] || '');
  const [ensuring, setEnsuring] = useState(false);
  const ensuredKey = useRef('');
  /** 换图世代：忽略旧 img 的 onError，避免清空新 src */
  const srcGen = useRef(0);
  const retriedGen = useRef(-1);

  const localKey = locals.join('|');

  useEffect(() => {
    srcGen.current += 1;
    retriedGen.current = -1;
    setPosters(locals);
    setSrc(locals[0] || '');
    if (locals[0]) setEnsuring(false);
    // localKey 已覆盖 locals 内容；避免数组引用进依赖导致死循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localKey]);

  useEffect(() => {
    const id = String(opts.itemId || '').trim();
    const cover = String(opts.coverUrl || '').trim();
    if (locals[0]) {
      setEnsuring(false);
      return;
    }
    if (!id && !cover) {
      setEnsuring(false);
      return;
    }
    const key = `${id}|${cover}|${prefer}`;
    if (ensuredKey.current === key) {
      // 同 key 已发起过：若仍无本地图，勿一直转圈
      setEnsuring(false);
      return;
    }
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
        // ensure 落盘的是 poster.jpg
        const api = String(data?.posterApi || '').trim();
        if (!api) return;
        const url = localUrl(api, undefined, coverOpts);
        if (!url) return;
        srcGen.current += 1;
        setSrc(url);
        setPosters([url]);
      } catch {
        /* ignore — 由调用方用 coverUrl 远程预览兜底 */
      } finally {
        if (!cancelled) setEnsuring(false);
      }
    })();
    return () => {
      cancelled = true;
      // 取消时清掉转圈，避免下一轮 early-return 卡死「落盘中」
      setEnsuring(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.itemId, opts.coverUrl, localKey, coverOpts, prefer]);

  const onError = (ev?: SyntheticEvent<HTMLImageElement>) => {
    const el = ev?.currentTarget;
    // 已解码成功却误报 error（合成层/transform）：忽略
    if (el && el.naturalWidth > 0) return;

    const gen = srcGen.current;
    const id = String(opts.itemId || '').trim();
    const cover = String(opts.coverUrl || '').trim();

    // AppPush / Tab transform 下首帧常假失败：短延迟后再 bust，避免慢网双请求打架
    if (retriedGen.current !== gen) {
      retriedGen.current = gen;
      window.setTimeout(() => {
        if (gen !== srcGen.current) return;
        setSrc((cur) => {
          if (gen !== srcGen.current || !cur) return cur;
          const base = cur
            .replace(/([?&])_cb=\d+/g, '$1')
            .replace(/[?&]$/, '');
          const sep = base.includes('?') ? '&' : '?';
          return `${base}${sep}_cb=${Date.now()}`;
        });
      }, 120);
      return;
    }

    if (!id && !cover) {
      if (gen === srcGen.current) setSrc('');
      return;
    }

    void (async () => {
      try {
        const data = await ensureScrapLibraryPoster({
          itemId: id,
          coverUrl: cover,
        });
        if (gen !== srcGen.current) return;
        const api = String(data?.posterApi || '').trim();
        const url = api ? localUrl(api, undefined, coverOpts) : '';
        if (!url) {
          if (gen === srcGen.current) setSrc('');
          return;
        }
        // 即使 ensure 回到同一路径，也换世代 + bust，避免「url === src → 直接清空」
        srcGen.current += 1;
        retriedGen.current = -1;
        const sep = url.includes('?') ? '&' : '?';
        setSrc(`${url}${sep}_cb=${Date.now()}`);
        setPosters([url]);
      } catch {
        if (gen === srcGen.current) setSrc('');
      }
    })();
  };

  return { src, posters, onError, ensuring };
}

/** 列表 / 货架 / 厂牌墙：优先 poster。有码另传 rp 做横图右裁。 */
export const SCRAP_POSTER_COVER_OPTS = {
  w: SCRAP_LIST_THUMB_W,
  prefer: 'poster' as const,
  rp: false as const,
};

export const SCRAP_COLLAGE_COVER_OPTS = {
  w: SCRAP_COLLAGE_THUMB_W,
  prefer: 'poster' as const,
  rp: false as const,
};

/** 详情主图：poster 高清 */
export const SCRAP_DETAIL_COVER_OPTS = {
  w: 720,
  prefer: 'poster' as const,
  rp: false as const,
};
