'use client';

import { startTransition, useCallback, useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import {
  fetchMediaDetail,
  fetchMediaMeta,
  proxiedCoverUrl,
  type MediaCastPerson,
  type MediaCategoryId,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { useStackCover } from '@/hooks/useStackCover';
import { MediaChartBody } from './MediaChartBody';
import { MediaDetailBody } from './MediaDetailBody';
import { MediaExploreBody } from './MediaExploreBody';
import { MediaPersonBody } from './MediaPersonBody';
import { MediaSearchBody } from './MediaSearchBody';
import { MediaShelf } from './MediaShelf';
import { hubShelvesFor, mediaCategoryLabel } from './mediaUi';

type HubTab = MediaSourceId | 'explore';

type DetailFrom = 'hub' | 'chart' | 'search' | 'person' | 'explore';

type DetailBack = {
  category: MediaCategoryId;
  item: MediaItem;
  detail: MediaItem | null;
  from: Exclude<DetailFrom, 'person'>;
  chart?: string;
};

type Stack =
  | { kind: 'hub' }
  | { kind: 'search' }
  | { kind: 'chart'; category: MediaCategoryId; chart?: string }
  | {
      kind: 'detail';
      category: MediaCategoryId;
      item: MediaItem;
      detail: MediaItem | null;
      from: DetailFrom;
      chart?: string;
      /** 从影人作品页点进详情时，返回用 */
      person?: MediaCastPerson;
      detailBack?: DetailBack;
    }
  | {
      kind: 'person';
      person: MediaCastPerson;
      detailBack: DetailBack;
    };

export function MediaScreen() {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [hubTab, setHubTab] = useState<HubTab>('tmdb');
  const [tmdbOk, setTmdbOk] = useState(true);
  const [msg, setMsg] = useState('');
  const [loadingDetail, setLoadingDetail] = useState(false);
  const hubCover = useStackCover(
    stack.kind !== 'hub',
    'media-hub',
    'app-hub media-hub-root',
  );

  const source: MediaSourceId = hubTab === 'explore' ? 'tmdb' : hubTab;
  const exploring = hubTab === 'explore';

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/media') return;
    if (tabCtx.tabReselect > 0) setStack({ kind: 'hub' });
  }, [tabCtx?.tabReselect, tabCtx?.activeTab]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const meta = await fetchMediaMeta();
        if (cancelled) return;
        setTmdbOk(Boolean(meta.tmdbConfigured));
        if (!meta.tmdbConfigured && (hubTab === 'tmdb' || hubTab === 'explore')) {
          setHubTab('douban');
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = useCallback(
    async (
      category: MediaCategoryId,
      item: MediaItem,
      from: DetailFrom,
      opts?: {
        chart?: string;
        person?: MediaCastPerson;
        detailBack?: DetailBack;
      },
    ) => {
      setLoadingDetail(true);
      setMsg('');
      const base = {
        kind: 'detail' as const,
        category,
        item,
        from,
        chart: opts?.chart,
        person: opts?.person,
        detailBack: opts?.detailBack,
      };
      startTransition(() => {
        setStack({ ...base, detail: null });
      });
      const cover = proxiedCoverUrl(item.posterUrl);
      if (cover && typeof window !== 'undefined') {
        const warm = new window.Image();
        warm.decoding = 'async';
        warm.src = cover;
      }
      try {
        const detail = await fetchMediaDetail({
          source: item.source,
          id: item.id,
          mediaType: item.mediaType,
        });
        setStack({ ...base, detail });
      } catch (e) {
        const text = e instanceof Error ? e.message : '详情加载失败';
        setMsg(text);
        toast(text, 'error');
        setStack({ ...base, detail: item });
      } finally {
        setLoadingDetail(false);
      }
    },
    [toast],
  );

  const shelves = hubShelvesFor(source);

  const hub = (
    <div {...hubCover}>
      <div className="media-hub__top">
        <div className="media-hub__top-row">
          <button
            type="button"
            className="media-hub__search-btn"
            aria-label="搜索影视"
            onClick={() => startTransition(() => setStack({ kind: 'search' }))}
          >
            <Search size={17} strokeWidth={2.4} aria-hidden />
          </button>
          <h1 className="app-hub__title">影视</h1>
        </div>
        <div className="media-source-switch" role="tablist" aria-label="数据源">
          {(
            [
              { id: 'tmdb', label: 'TMDB' },
              { id: 'douban', label: '豆瓣' },
              { id: 'bangumi', label: 'Bangumi' },
              { id: 'anilist', label: 'AniList' },
              { id: 'explore', label: '探索' },
            ] as const
          ).map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={hubTab === s.id}
              className={
                hubTab === s.id
                  ? 'media-source-switch__btn is-active'
                  : 'media-source-switch__btn'
              }
              onClick={() => {
                if ((s.id === 'tmdb' || s.id === 'explore') && !tmdbOk) {
                  toast('请先在 更多 → TMDB 配置 API Key', 'info');
                  return;
                }
                setHubTab(s.id);
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="app-hub__scroll media-hub">
        {exploring ? (
          <MediaExploreBody
            onOpen={(item) =>
              void openDetail(
                item.mediaType === 'tv' ? 'tv' : 'movie',
                item,
                'explore',
              )
            }
          />
        ) : (
          <div className="media-hub__shelves">
            {shelves.map((s) => (
              <MediaShelf
                key={`${source}-${s.category}-${s.chart}`}
                source={source}
                category={s.category}
                chart={s.chart}
                title={s.title}
                onOpenAll={() =>
                  startTransition(() =>
                    setStack({
                      kind: 'chart',
                      category: s.category,
                      chart: s.chart,
                    }),
                  )
                }
                onOpenItem={(item) =>
                  void openDetail(s.category, item, 'hub', { chart: s.chart })
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );

  let push = null;

  if (stack.kind === 'search') {
    push = (
      <AppPush
        title="搜索影视"
        scrollKey={`media-search-${source}`}
        onBack={() => setStack({ kind: 'hub' })}
      >
        <MediaSearchBody
          source={source}
          onOpen={(item) =>
            void openDetail(
              item.mediaType === 'tv' ? 'tv' : 'movie',
              item,
              'search',
            )
          }
        />
      </AppPush>
    );
  } else if (stack.kind === 'chart') {
    push = (
      <AppPush
        title={mediaCategoryLabel(stack.category)}
        scrollKey={`media-chart-${source}-${stack.category}-${stack.chart || ''}`}
        onBack={() => setStack({ kind: 'hub' })}
      >
        <MediaChartBody
          source={source}
          category={stack.category}
          initialChart={stack.chart}
          onOpen={(item) =>
            void openDetail(stack.category, item, 'chart', {
              chart: stack.chart,
            })
          }
        />
      </AppPush>
    );
  } else if (stack.kind === 'person') {
    push = (
      <AppPush
        title={stack.person.name}
        scrollKey={`media-person-${stack.person.id}`}
        onBack={() =>
          setStack({
            kind: 'detail',
            ...stack.detailBack,
          })
        }
      >
        <MediaPersonBody
          source={source}
          person={stack.person}
          onOpen={(item) =>
            void openDetail(
              item.mediaType === 'tv' ? 'tv' : 'movie',
              item,
              'person',
              {
                person: stack.person,
                detailBack: stack.detailBack,
              },
            )
          }
        />
      </AppPush>
    );
  } else if (stack.kind === 'detail') {
    const show = stack.detail || stack.item;
    const onBack = () => {
      if (stack.from === 'person' && stack.person && stack.detailBack) {
        setStack({
          kind: 'person',
          person: stack.person,
          detailBack: stack.detailBack,
        });
        return;
      }
      if (stack.from === 'search') setStack({ kind: 'search' });
      else if (stack.from === 'chart') {
        setStack({
          kind: 'chart',
          category: stack.category,
          chart: stack.chart,
        });
      } else setStack({ kind: 'hub' });
    };
    push = (
      <AppPush
        title={show.title}
        scrollKey={`media-detail-${show.source}-${show.id}`}
        scrollMode="top"
        onBack={onBack}
      >
        <MediaDetailBody
          item={show}
          enriching={loadingDetail && !stack.detail}
          onOpenRelated={(next) =>
            void openDetail(
              next.mediaType === 'tv' ? 'tv' : stack.category,
              next,
              stack.from === 'person' ? 'person' : stack.from,
              {
                chart: stack.chart,
                person: stack.person,
                detailBack: stack.detailBack,
              },
            )
          }
          onOpenPerson={(person) => {
            const from =
              stack.from === 'person'
                ? stack.detailBack?.from || 'hub'
                : stack.from;
            startTransition(() =>
              setStack({
                kind: 'person',
                person,
                detailBack: {
                  category: stack.category,
                  item: stack.item,
                  detail: stack.detail,
                  from,
                  chart: stack.chart,
                },
              }),
            );
          }}
        />
        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </AppPush>
    );
  }

  return (
    <div className="app-stack-root media-stack">
      {hub}
      {push}
    </div>
  );
}
