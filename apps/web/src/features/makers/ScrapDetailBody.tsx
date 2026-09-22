'use client';

import {
  Bookmark,
  BookmarkCheck,
  Captions,
  Languages,
  RefreshCw,
  Search,
} from 'lucide-react';
import type { ScrapLibraryEmbedItem } from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import { isCensoredRightCropRegion } from './makersUi';
import { ScrapPosterCard } from './ScrapPosterCard';
import { MkdActressAvatar } from './scrapDetailHelpers';
import { useScrapDetail } from './useScrapDetail';

export function ScrapDetailBody({
  item,
  region: regionProp,
  onFavoriteChange,
  onOpenActress,
  onOpenGenre,
  onOpenStudio,
  onOpenRelated,
  onItemPatch,
}: {
  item: ScrapLibraryEmbedItem;
  region?: string;
  onFavoriteChange?: (favorited: boolean) => void;
  onOpenActress?: (name: string, posterApi?: string) => void;
  onOpenGenre?: (name: string) => void;
  onOpenStudio?: (name: string) => void;
  onOpenRelated?: (next: ScrapLibraryEmbedItem) => void;
  onItemPatch?: (patch: Partial<ScrapLibraryEmbedItem>) => void;
}) {
  const d = useScrapDetail({
    item,
    region: regionProp,
    onFavoriteChange,
    onOpenActress,
    onOpenGenre,
    onOpenStudio,
    onOpenRelated,
    onItemPatch,
  });

  const favFactBtn = (
    <button
      type="button"
      className={
        d.favorited
          ? 'mkd-fav mkd-fav--beside mkd-fav--on'
          : 'mkd-fav mkd-fav--beside'
      }
      onClick={() => void d.onToggleFavorite()}
      aria-pressed={d.favorited}
      aria-label={d.favorited ? '取消收藏' : '收藏'}
      disabled={d.favBusy || d.enrichBusy}
      title={d.favorited ? '取消收藏' : '收藏'}
    >
      {d.favorited ? (
        <BookmarkCheck size={15} strokeWidth={2.25} aria-hidden />
      ) : (
        <Bookmark size={15} strokeWidth={2.25} aria-hidden />
      )}
    </button>
  );

  return (
    <div className="mkd">
      <header className="mkd-head">
        {d.washSrc && !d.imgGone ? (
          <div className="mkd-head__wash" aria-hidden>
            <SoftImg
              src={d.washSrc}
              loading="eager"
              fetchPriority="high"
              onError={() => d.setImgGone(true)}
            />
          </div>
        ) : null}

        <div className="mkd-head__row">
          <div className="media-detail__poster mkd-head__poster" aria-hidden>
            <span className="media-detail__poster-ph">
              {(d.code || d.title || '?').slice(0, 1)}
            </span>
            {d.poster ? (
              <SoftImg
                src={d.poster}
                loading="eager"
                fetchPriority="high"
                onError={d.onPosterError}
              />
            ) : null}
          </div>

          <div className="mkd-head__id">
            <div className="mkd-head__code-row">
              <p className="mkd-head__code allow-select">{d.code || '—'}</p>
              <div className="mkd-head__tools">
                <button
                  type="button"
                  className="mkd-enrich"
                  onClick={() => void d.onCheckQualityGate()}
                  disabled={d.enrichBusy}
                  title="按 E2E 门禁检查本条标题/海报/剧情等"
                >
                  门禁
                </button>
                <button
                  type="button"
                  className={
                    d.enrichBusy ? 'mkd-enrich mkd-enrich--busy' : 'mkd-enrich'
                  }
                  onClick={() => void d.onRefreshMeta()}
                  disabled={d.enrichBusy}
                  title="清空本条向量后全量重刮，覆盖 NFO 与向量库全部字段"
                >
                  <RefreshCw
                    size={15}
                    strokeWidth={2.25}
                    aria-hidden
                    className={d.enrichBusy ? 'mkd-enrich__spin' : undefined}
                  />
                  {d.enrichBusy ? '…' : '刷新'}
                </button>
              </div>
            </div>
            {d.displayTitle ? (
              <h2 className="mkd-head__title allow-select">{d.displayTitle}</h2>
            ) : null}
            {d.outlineShow !== 'zh' && d.secondaryTitle ? (
              <p className="mkd-head__subtitle allow-select">{d.secondaryTitle}</p>
            ) : null}

            <div className="mkd-facts-row">
              {d.facts.length > 0 ? (
                <dl className="mkd-facts">
                  {d.facts.map((f) => (
                    <div
                      key={f.k}
                      className={
                        f.k === '年份' ? 'mkd-fact mkd-fact--year' : 'mkd-fact'
                      }
                    >
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
              {favFactBtn}
            </div>
            {d.badgeChips.length > 0 ? (
              <div className="mkd-badges" aria-label="角标">
                {d.badgeChips.map((b) => (
                  <span key={b} className="mkd-badge">
                    {b}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {d.meta.actresses.length > 0 ? (
        <section className="mkd-section">
          <h3 className="media-detail__h mkd-section__h">女优</h3>
          <div className="mkd-actress-rail">
            {d.meta.actresses.map((name) => (
              <MkdActressAvatar
                key={name}
                name={name}
                posterApi={d.actressAvatars[name]}
                onOpen={d.onOpenActress}
              />
            ))}
          </div>
        </section>
      ) : null}

      {d.meta.genres.length > 0 ? (
        <section className="mkd-section">
          <h3 className="media-detail__h mkd-section__h">标签</h3>
          <div className="mkd-chips">
            {d.meta.genres.map((g) => (
              <button
                key={g}
                type="button"
                className="mkd-chip mkd-chip--btn"
                onClick={() => d.onOpenGenre?.(g)}
              >
                {g}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {d.meta.plot || d.plotZh || d.meta.originalPlot ? (
        <section className="mkd-section">
          <div className="mkd-section__head">
            <h3 className="media-detail__h mkd-section__h">剧情</h3>
            {!d.plotLooksChinese && !d.plotSaved ? (
              <button
                type="button"
                className="mkd-translate-btn"
                onClick={() => void d.onTranslatePlot()}
                disabled={d.plotBusy}
                title="翻译为中文并保存"
              >
                <Languages size={14} strokeWidth={2.25} aria-hidden />
                {d.plotBusy ? '翻译中…' : '翻译'}
              </button>
            ) : (
              <span className="mkd-translate-btn is-active" aria-hidden>
                <Languages size={14} strokeWidth={2.25} />
                中文
              </span>
            )}
          </div>
          {d.bilingualPlots.primary ? (
            <p className="media-detail__overview allow-select">
              {d.bilingualPlots.primary}
            </p>
          ) : null}
          {d.bilingualPlots.secondary ? (
            <p className="media-detail__overview media-detail__overview--alt allow-select">
              {d.bilingualPlots.secondary}
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="mkd-actions">
        <button
          type="button"
          className={d.subReady ? 'mkd-sub mkd-sub--on' : 'mkd-sub'}
          onClick={() => void d.onFetchSubtitle()}
          disabled={d.subBusy || d.enrichBusy}
          title={
            d.subReady
              ? '本地已有字幕；再点可强制重下并上传 115'
              : '搜索中文字幕并立即上传到 115 字幕目录'
          }
        >
          <Captions size={17} strokeWidth={2.25} aria-hidden />
          {d.subBusy ? '处理中…' : d.subReady ? '已有字幕' : '搜字幕'}
        </button>
        <button
          type="button"
          className="media-detail__cta mkd-cta"
          onClick={d.onSearch}
          disabled={d.enrichBusy}
        >
          <Search size={17} strokeWidth={2.25} aria-hidden />
          在资源库搜索
        </button>
      </div>

      {d.relatedLoading || d.related.length > 0 ? (
        <section className="mkd-section mkd-related">
          <h3 className="media-detail__h mkd-section__h">推荐番号</h3>
          {d.relatedLoading && d.related.length === 0 ? (
            <div className="media-shelf__rail media-shelf__rail--skel" aria-hidden>
              {Array.from({ length: 4 }).map((_, i) => (
                <span key={i} className="makers-poster-skel" />
              ))}
            </div>
          ) : d.related.length > 0 ? (
            <div className="media-shelf__rail makers-shelf__rail">
              {d.related.map((row) => (
                <ScrapPosterCard
                  key={String(row.itemId || row.code)}
                  item={row}
                  rightCrop={isCensoredRightCropRegion(
                    row.region ||
                      row.relPath ||
                      d.item.region ||
                      d.item.relPath,
                  )}
                  onClick={() => d.onOpenRelated?.(row)}
                />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
