'use client';

import { startTransition, useCallback, useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import {
  fetchMediaDetail,
  fetchMediaMeta,
  type MediaCategoryId,
  type MediaItem,
  type MediaSourceId,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { useTabNavigation } from '@/shell';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { MediaChartBody } from './MediaChartBody';
import { MediaDetailBody } from './MediaDetailBody';
import { MediaSearchBody } from './MediaSearchBody';
import { MediaShelf } from './MediaShelf';
import { hubShelvesFor, mediaCategoryLabel } from './mediaUi';

type DetailFrom = 'hub' | 'chart' | 'search';

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
    };

export function MediaScreen() {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [source, setSource] = useState<MediaSourceId>('tmdb');
  const [tmdbOk, setTmdbOk] = useState(true);
  const [msg, setMsg] = useState('');
  const [loadingDetail, setLoadingDetail] = useState(false);

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
        if (!meta.tmdbConfigured && source === 'tmdb') {
          setSource('douban');
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
      chart?: string,
    ) => {
      setLoadingDetail(true);
      setMsg('');
      startTransition(() => {
        setStack({ kind: 'detail', category, item, detail: null, from, chart });
      });
      try {
        const detail = await fetchMediaDetail({
          source: item.source,
          id: item.id,
          mediaType: item.mediaType,
        });
        setStack({ kind: 'detail', category, item, detail, from, chart });
      } catch (e) {
        const text = e instanceof Error ? e.message : '详情加载失败';
        setMsg(text);
        toast(text, 'error');
        setStack({ kind: 'detail', category, item, detail: item, from, chart });
      } finally {
        setLoadingDetail(false);
      }
    },
    [toast],
  );

  const shelves = hubShelvesFor(source);

  const hub = (
    <div className="app-hub media-hub-root" aria-hidden={stack.kind !== 'hub'}>
      <div className="media-hub__top">
        <h1 className="app-hub__title">影视</h1>
        <div className="media-hub__top-actions">
          <button
            type="button"
            className="media-hub__search-btn"
            aria-label="搜索影视"
            onClick={() => startTransition(() => setStack({ kind: 'search' }))}
          >
            <Search size={18} strokeWidth={2.25} aria-hidden />
          </button>
          <div className="media-source-switch" role="tablist" aria-label="数据源">
            <button
              type="button"
              role="tab"
              aria-selected={source === 'tmdb'}
              className={
                source === 'tmdb'
                  ? 'media-source-switch__btn is-active'
                  : 'media-source-switch__btn'
              }
              onClick={() => {
                if (!tmdbOk) {
                  toast('请先在 设置 → TMDB 配置 API Key', 'info');
                  return;
                }
                setSource('tmdb');
              }}
            >
              TMDB
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={source === 'douban'}
              className={
                source === 'douban'
                  ? 'media-source-switch__btn is-active'
                  : 'media-source-switch__btn'
              }
              onClick={() => setSource('douban')}
            >
              豆瓣
            </button>
          </div>
        </div>
      </div>

      {!tmdbOk && source === 'douban' ? (
        <p className="media-hub__tip">TMDB 未配置，当前使用豆瓣</p>
      ) : null}

      <div className="app-hub__scroll media-hub">
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
              onOpenItem={(item) => void openDetail(s.category, item, 'hub', s.chart)}
            />
          ))}
        </div>
      </div>
    </div>
  );

  let push = null;

  if (stack.kind === 'search') {
    push = (
      <AppPush title="搜索影视" onBack={() => setStack({ kind: 'hub' })}>
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
        onBack={() => setStack({ kind: 'hub' })}
      >
        <MediaChartBody
          source={source}
          category={stack.category}
          initialChart={stack.chart}
          onOpen={(item) =>
            void openDetail(stack.category, item, 'chart', stack.chart)
          }
        />
      </AppPush>
    );
  } else if (stack.kind === 'detail') {
    const show = stack.detail || stack.item;
    const onBack = () => {
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
      <AppPush title={show.title} onBack={onBack}>
        {loadingDetail && !stack.detail ? (
          <p className="media-empty">加载详情…</p>
        ) : (
          <MediaDetailBody
            item={show}
            onOpenRelated={(next) =>
              void openDetail(
                next.mediaType === 'tv' ? 'tv' : stack.category,
                next,
                stack.from,
                stack.chart,
              )
            }
          />
        )}
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
