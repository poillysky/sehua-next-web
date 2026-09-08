'use client';

import { useEffect, useMemo, useState } from 'react';
import { Bookmark, BookmarkCheck, Captions, Search } from 'lucide-react';
import {
  fetchScrapLibrarySubtitles,
  listScrapLibraryEmbedItems,
  listScrapLibrarySubtitles,
  searchScrapLibraryEmbed,
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { writeP115AttachSubs } from '@/lib/p115AttachSubs';
import { openMakerHomeSearch } from './makersUi';
import { isScrapFavorite, toggleScrapFavorite, ensureScrapFavoritesLoaded } from './scrapFavorites';
import { parseScrapSourceText } from './scrapSourceMeta';
import { ScrapPosterCard } from './ScrapPosterCard';

export function ScrapDetailBody({
  item,
  region: regionProp,
  onFavoriteChange,
  onOpenActress,
  onOpenGenre,
  onOpenStudio,
  onOpenRelated,
}: {
  item: ScrapLibraryEmbedItem;
  /** 当前片商分区，优先于 item.region */
  region?: string;
  onFavoriteChange?: (favorited: boolean) => void;
  onOpenActress?: (name: string) => void;
  onOpenGenre?: (name: string) => void;
  onOpenStudio?: (name: string) => void;
  onOpenRelated?: (next: ScrapLibraryEmbedItem) => void;
}) {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const meta = useMemo(
    () => parseScrapSourceText(item.sourceText),
    [item.sourceText],
  );
  const code = String(item.code || meta.code || '').trim();
  const title = String(item.title || meta.title || '').trim();
  const originalTitle = String(meta.originalTitle || '').trim();
  const stripCodePrefix = (raw: string) => {
    const s = raw.trim();
    if (!s || !code) return s;
    return s
      .replace(
        new RegExp(`^${code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*`, 'i'),
        '',
      )
      .trim();
  };
  const titleZhOrJa = (() => {
    const a = stripCodePrefix(title);
    const b = stripCodePrefix(originalTitle);
    const hasCjk = (s: string) => /[\u4e00-\u9fff]/.test(s);
    if (a && hasCjk(a)) return a;
    if (b && hasCjk(b)) return b;
    return a || b;
  })();
  const displayTitle = titleZhOrJa;  const poster = scrapLibraryCoverUrl(item, { prefer: 'poster', w: 480 });
  const fanart = item.fanartApi
    ? scrapLibraryCoverUrl(
        { posterApi: item.fanartApi, coverUrl: '' },
        { prefer: 'poster', w: 720, rp: false },
      )
    : '';
  const thumbWide = item.thumbApi
    ? scrapLibraryCoverUrl(
        { posterApi: item.thumbApi, coverUrl: '' },
        { prefer: 'poster', w: 720, rp: false },
      )
    : '';
  const washSrc = fanart || thumbWide || poster;

  const [imgGone, setImgGone] = useState(false);
  const [favorited, setFavorited] = useState(false);
  const [favBusy, setFavBusy] = useState(false);
  const [subBusy, setSubBusy] = useState(false);
  const [subReady, setSubReady] = useState(false);
  const [related, setRelated] = useState<ScrapLibraryEmbedItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    setImgGone(false);
    setSubReady(false);
    let cancelled = false;
    const id = String(item.itemId || '');
    // 收藏真相在服务端：先确保缓存就绪再据其点亮状态
    void (async () => {
      await ensureScrapFavoritesLoaded();
      if (cancelled) return;
      setFavorited(isScrapFavorite(id));
    })();
    void (async () => {
      try {
        const st = await listScrapLibrarySubtitles({
          itemId: id,
          code,
        });
        if (!cancelled) setSubReady((st.files || []).length > 0);
      } catch {
        if (!cancelled) setSubReady(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.itemId, code]);

  useEffect(() => {
    let cancelled = false;
    const selfId = String(item.itemId || '');
    const selfCode = code.toUpperCase();
    const region = String(regionProp || item.region || '').trim();
    const prefix = String(item.prefix || meta.prefix || '').trim();
    const actress = meta.actresses[0] || '';
    const studio = meta.studio || '';

    const take = (
      rows: ScrapLibraryEmbedItem[],
      seen: Set<string>,
      out: ScrapLibraryEmbedItem[],
    ) => {
      for (const row of rows) {
        const id = String(row.itemId || '');
        const c = String(row.code || '').toUpperCase();
        const key = id || c;
        if (!key || key === selfId || c === selfCode || seen.has(key)) continue;
        seen.add(key);
        out.push(row);
        if (out.length >= 12) break;
      }
    };

    void (async () => {
      setRelatedLoading(true);
      setRelated([]);
      const seen = new Set<string>();
      const out: ScrapLibraryEmbedItem[] = [];

      const tryList = async (
        opts: Parameters<typeof listScrapLibraryEmbedItems>[0],
      ) => {
        if (cancelled || out.length >= 12) return;
        try {
          const page = await listScrapLibraryEmbedItems({
            ...opts,
            region: opts?.region || region || undefined,
            sort: 'recent',
            limit: 18,
          });
          if (!cancelled) take(page.items || [], seen, out);
        } catch {
          /* 单路失败继续 */
        }
      };

      // 同女优 → 同片商 → 同前缀；语义搜索最后且可失败
      if (actress) await tryList({ tag: actress });
      if (studio && out.length < 8) await tryList({ studio });
      if (prefix && out.length < 8) await tryList({ prefix });

      if (!cancelled && out.length < 6) {
        const q = [actress, studio, ...meta.genres.slice(0, 2)]
          .filter(Boolean)
          .join(' ');
        if (q) {
          try {
            const hits = await searchScrapLibraryEmbed({
              query: q,
              limit: 16,
              region,
            });
            if (!cancelled) take(hits, seen, out);
          } catch {
            /* 语义可选 */
          }
        }
      }

      if (!cancelled) {
        setRelated(out.slice(0, 12));
        setRelatedLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // 仅随条目变化拉取；勿依赖父组件 inline 回调
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.itemId, item.region, item.prefix, regionProp, code, meta.actresses[0], meta.studio, meta.prefix]);

  async function onToggleFavorite() {
    if (!item.itemId) {
      toast('无法收藏：缺少条目 ID', 'error');
      return;
    }
    if (favBusy) return;
    setFavBusy(true);
    try {
      await ensureScrapFavoritesLoaded();
      const prev = isScrapFavorite(item.itemId);
      const next = await toggleScrapFavorite(item, regionProp);
      setFavorited(next);
      onFavoriteChange?.(next);
      toast(next ? '已加入收藏' : '已取消收藏', 'success');
    } catch (e) {
      // 落库失败：按已加载缓存回滚提示
      const prev = isScrapFavorite(item.itemId);
      setFavorited(prev);
      onFavoriteChange?.(prev);
      toast(e instanceof Error ? `操作失败：${e.message}` : '操作失败', 'error');
    } finally {
      setFavBusy(false);
    }
  }

  function onSearch() {
    const region = String(regionProp || item.region || '').trim();
    const ok = openMakerHomeSearch(
      { code, title, id: item.itemId, region },
      tabCtx?.scrollToTab,
    );
    if (!ok) toast('没有可用的番号用于搜索', 'error');
    else toast('已跳转资源库搜索', 'success');
  }

  async function onFetchSubtitle() {
    if (subBusy) return;
    if (!code && !item.itemId) {
      toast('没有可用的番号', 'error');
      return;
    }
    setSubBusy(true);
    const region = String(regionProp || item.region || '').trim();
    try {
      const data = await fetchScrapLibrarySubtitles({
        itemId: String(item.itemId || ''),
        code,
        force: subReady,
        upload115: true,
        region,
      });
      writeP115AttachSubs({
        code,
        itemId: String(item.itemId || ''),
        region,
      });
      const n = (data.files || []).length;
      const up = data.upload115;
      if (!(data.ok && n > 0)) {
        setSubReady(false);
        toast(
          data.reason === 'not_found'
            ? data.message || '未找到对应中文字幕'
            : data.reason === 'network'
              ? data.message || '无法连接字幕站，请检查代理'
              : data.message || data.reason || '搜字幕失败',
          'error',
        );
        return;
      }
      setSubReady(true);
      if (up?.ok && (up.count || 0) > 0) {
        toast(data.message || up.message || '字幕已上传到 115', 'success');
      } else if (up && !up.ok) {
        toast(
          up.message
            ? `字幕已保存本地；115：${up.message}`
            : '字幕已保存本地，但上传 115 失败',
          'error',
        );
      } else {
        toast(
          data.message || `字幕已保存（${n}），但未返回上传结果`,
          'error',
        );
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : '搜字幕失败', 'error');
    } finally {
      setSubBusy(false);
    }
  }

  const facts: Array<{ k: string; v: string; onClick?: () => void }> = [];
  if (meta.year) facts.push({ k: '年份', v: meta.year });
  if (meta.studio) {
    facts.push({
      k: '片商',
      v: meta.studio,
      onClick: onOpenStudio ? () => onOpenStudio(meta.studio) : undefined,
    });
  }
  if (meta.label && meta.label !== meta.studio) {
    facts.push({ k: '发行', v: meta.label });
  }

  return (
    <div className="mkd">
      <header className="mkd-head">
        {washSrc && !imgGone ? (
          <div className="mkd-head__wash" aria-hidden>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={washSrc}
              alt=""
              loading="eager"
              decoding="async"
              fetchPriority="high"
              referrerPolicy="no-referrer"
            />
          </div>
        ) : null}

        <div className="mkd-head__row">
          <div className="media-detail__poster mkd-head__poster" aria-hidden>
            {poster && !imgGone ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={poster}
                alt=""
                loading="eager"
                decoding="async"
                fetchPriority="high"
                referrerPolicy="no-referrer"
                onError={() => setImgGone(true)}
              />
            ) : (
              <span className="media-detail__poster-ph">
                {(code || title || '?').slice(0, 1)}
              </span>
            )}
          </div>

          <div className="mkd-head__id">
            <p className="mkd-head__code allow-select">{code || '—'}</p>
            {displayTitle ? (
              <h2 className="mkd-head__title allow-select">{displayTitle}</h2>
            ) : null}

            {facts.length > 0 ? (
              <dl className="mkd-facts">
                {facts.map((f) => (
                  <div key={f.k} className="mkd-fact">
                    <dt className="mkd-fact__k">{f.k}</dt>
                    <dd className="mkd-fact__v">
                      {f.onClick ? (
                        <button
                          type="button"
                          className="mkd-fact__link allow-select"
                          onClick={f.onClick}
                        >
                          {f.v}
                        </button>
                      ) : (
                        <span className="allow-select">{f.v}</span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        </div>
      </header>

      {meta.actresses.length > 0 ? (
        <section className="mkd-section">
          <h3 className="media-detail__h mkd-section__h">女优</h3>
          <div className="mkd-chips">
            {meta.actresses.map((name) => (
              <button
                key={name}
                type="button"
                className="mkd-chip mkd-chip--btn"
                onClick={() => onOpenActress?.(name)}
              >
                {name}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {meta.genres.length > 0 ? (
        <section className="mkd-section">
          <h3 className="media-detail__h mkd-section__h">标签</h3>
          <div className="mkd-chips">
            {meta.genres.map((g) => (
              <button
                key={g}
                type="button"
                className="mkd-chip mkd-chip--btn"
                onClick={() => onOpenGenre?.(g)}
              >
                {g}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {meta.plot ? (
        <section className="mkd-section">
          <h3 className="media-detail__h mkd-section__h">剧情</h3>
          <p className="media-detail__overview allow-select">{meta.plot}</p>
        </section>
      ) : null}

      <div className="mkd-actions">
        <button
          type="button"
          className={favorited ? 'mkd-fav mkd-fav--on' : 'mkd-fav'}
          onClick={() => void onToggleFavorite()}
          aria-pressed={favorited}
          disabled={favBusy}
        >
          {favorited ? (
            <BookmarkCheck size={17} strokeWidth={2.25} aria-hidden />
          ) : (
            <Bookmark size={17} strokeWidth={2.25} aria-hidden />
          )}
          {favBusy ? '…' : favorited ? '已收藏' : '收藏'}
        </button>
        <button
          type="button"
          className={
            subReady ? 'mkd-sub mkd-sub--on' : 'mkd-sub'
          }
          onClick={() => void onFetchSubtitle()}
          disabled={subBusy}
          title={
            subReady
              ? '本地已有字幕；再点可强制重下并上传 115'
              : '搜索中文字幕并立即上传到 115 字幕目录'
          }
        >
          <Captions size={17} strokeWidth={2.25} aria-hidden />
          {subBusy ? '处理中…' : subReady ? '已有字幕' : '搜字幕'}
        </button>
        <button
          type="button"
          className="media-detail__cta mkd-cta"
          onClick={onSearch}
        >
          <Search size={17} strokeWidth={2.25} aria-hidden />
          在资源库搜索
        </button>
      </div>

      {relatedLoading || related.length > 0 ? (
        <section className="mkd-section mkd-related">
          <h3 className="media-detail__h mkd-section__h">推荐番号</h3>
          {relatedLoading && related.length === 0 ? (
            <div className="media-shelf__rail media-shelf__rail--skel" aria-hidden>
              {Array.from({ length: 4 }).map((_, i) => (
                <span key={i} className="makers-poster-skel" />
              ))}
            </div>
          ) : related.length > 0 ? (
            <div className="media-shelf__rail makers-shelf__rail">
              {related.map((row) => (
                <ScrapPosterCard
                  key={String(row.itemId || row.code)}
                  item={row}
                  onClick={() => onOpenRelated?.(row)}
                />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
