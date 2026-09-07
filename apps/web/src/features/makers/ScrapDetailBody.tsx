'use client';

import { useEffect, useMemo, useState } from 'react';
import { Bookmark, BookmarkCheck, Search } from 'lucide-react';
import {
  listScrapLibraryEmbedItems,
  searchScrapLibraryEmbed,
  scrapLibraryCoverUrl,
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { openMakerHomeSearch } from './makersUi';
import { isScrapFavorite, toggleScrapFavorite } from './scrapFavorites';
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
  const displayTitle = title
    .replace(new RegExp(`^${code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*`, 'i'), '')
    .trim();
  const poster = scrapLibraryCoverUrl(item, { prefer: 'poster', w: 480 });
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
  const [related, setRelated] = useState<ScrapLibraryEmbedItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    setImgGone(false);
    setFavorited(isScrapFavorite(item.itemId));
  }, [item.itemId]);

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

  function onToggleFavorite() {
    if (!item.itemId) {
      toast('无法收藏：缺少条目 ID', 'error');
      return;
    }
    const next = toggleScrapFavorite(item, regionProp);
    setFavorited(next);
    onFavoriteChange?.(next);
    toast(next ? '已加入收藏' : '已取消收藏', 'success');
  }

  function onSearch() {
    const ok = openMakerHomeSearch(
      { code, title, id: item.itemId },
      tabCtx?.scrollToTab,
    );
    if (!ok) toast('没有可用的番号用于搜索', 'error');
    else toast('已跳转资源库搜索', 'success');
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
            {meta.originalTitle && meta.originalTitle !== title ? (
              <p className="mkd-head__title allow-select" style={{ opacity: 0.85 }}>
                {meta.originalTitle
                  .replace(
                    new RegExp(
                      `^${code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*`,
                      'i',
                    ),
                    '',
                  )
                  .trim()}
              </p>
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
          onClick={onToggleFavorite}
          aria-pressed={favorited}
        >
          {favorited ? (
            <BookmarkCheck size={17} strokeWidth={2.25} aria-hidden />
          ) : (
            <Bookmark size={17} strokeWidth={2.25} aria-hidden />
          )}
          {favorited ? '已收藏' : '收藏'}
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
