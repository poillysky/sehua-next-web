'use client';

import { startTransition, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Search, Tags } from 'lucide-react';
import {
  fetchLibraryRegion,
  fetchLibraryRegions,
  type MakerFsRegionCatalog,
  type MakerFsRegionSummary,
} from '@/lib/api';
import {
  formatMakerFsCount,
  groupMakerFsByMaker,
  indexesMakerFsActors,
  makerFsGroupNoun,
  makerFsPrefixMatchesQuery,
  pickMakerGroupCover,
  clearLibraryBrowseCaches,
  getLibraryCatalogCache,
  getLibraryRegionsCache,
  LIBRARY_SYNCED,
  MAKER_FS_FALLBACK_REGIONS,
  prefetchLibraryRegion,
  setLibraryCatalogCache,
  setLibraryRegionsCache,
  type MakerFsMakerGroup,
} from '@/lib/makerFsUi';
import { makerDescription, prefixNote } from '@/config/av-makers';
import { useTabNavigation } from '@/shell';
import { AppPush } from '@/components/ui/AppPush';
import { BrowsePrefToggles } from '@/components/BrowsePrefToggles';
import { PrefixCodeGrid } from '@/features/boards/PrefixCodeGrid';
import { MakerCodeSearchBody } from './MakerCodeSearchBody';
import { MakerFacetBrowseBody } from './MakerFacetBrowseBody';
import { MakerFacetCodesBody } from './MakerFacetCodesBody';
import { MakerPosterGrid } from './MakerPosterTile';

type Stack =
  | { kind: 'hub' }
  | { kind: 'region'; region: MakerFsRegionSummary; catalog: MakerFsRegionCatalog }
  | {
      kind: 'facets';
      region: MakerFsRegionSummary;
      catalog: MakerFsRegionCatalog;
    }
  | {
      kind: 'facet';
      region: MakerFsRegionSummary;
      catalog: MakerFsRegionCatalog;
      facetKind: 'tag' | 'series';
      facetValue: string;
      facetCount?: number;
    }
  | {
      kind: 'maker';
      region: MakerFsRegionSummary;
      catalog: MakerFsRegionCatalog;
      maker: string;
      group: MakerFsMakerGroup;
    }
  | {
      kind: 'prefix';
      region: MakerFsRegionSummary;
      catalog: MakerFsRegionCatalog;
      maker: string;
      prefix: string;
    }
  | {
      kind: 'code';
      region: MakerFsRegionSummary;
      catalog: MakerFsRegionCatalog;
      maker: string;
      prefix: string;
      code: string;
      /** 从索引进入时，返回索引页 */
      viaFacet?: {
        facetKind: 'tag' | 'series';
        facetValue: string;
        facetCount?: number;
      };
    };

const REGION_META: Record<string, { mark: string }> = {
  japan_censored: { mark: '码' },
  japan_gravure: { mark: '写' },
  japan_uncensored: { mark: '无' },
  japan_amateur: { mark: '素' },
  fc2: { mark: 'F' },
  china: { mark: '国' },
  western: { mark: '欧' },
};

function regionMeta(id: string) {
  return REGION_META[id] || { mark: '片' };
}

function regionRowMeta(r: MakerFsRegionSummary): string {
  const noun = makerFsGroupNoun(r.id);
  const makers = formatMakerFsCount(r.makerCount);
  const prefixes = formatMakerFsCount(r.prefixCount);
  const codes = formatMakerFsCount(r.codeCount);
  return `${makers} ${noun} · ${prefixes} 前缀 · ${codes} 条`;
}

/** 仅日本有码 / 日本写真显示中文·破解倾向；其他区不限制 */
function showBrowsePrefs(region: MakerFsRegionSummary): boolean {
  return indexesMakerFsActors(region.id);
}

function stackBodyScrollKey(s: Stack): string | null {
  switch (s.kind) {
    case 'region':
      return `region:${s.region.id}`;
    case 'maker':
      return `maker:${s.region.id}:${s.maker}`;
    case 'facets':
      return `facets:${s.region.id}`;
    default:
      return null;
  }
}

function prefixStackKey(
  regionId: string,
  maker: string,
  prefix: string,
  query: string,
): string {
  return `${regionId}|${maker}|${prefix}|${query.trim()}`;
}

/**
 * 片商：Hub → 分区 → 厂牌 → 前缀 → 番号
 * 分区页只渲染厂牌行，避免一次挂载全部前缀格导致卡顿。
 */
export function MakersScreen() {
  const tabCtx = useTabNavigation();
  const [regions, setRegions] = useState<MakerFsRegionSummary[]>(MAKER_FS_FALLBACK_REGIONS);
  const [ready, setReady] = useState(false);
  const [loadingHub, setLoadingHub] = useState(true);
  const [opening, setOpening] = useState(false);
  const [stack, setStack] = useState<Stack>({ kind: 'hub' });
  const [q, setQ] = useState('');
  const [prefixTotal, setPrefixTotal] = useState<number | null>(null);
  const [prefsTick, setPrefsTick] = useState(0);
  const pushBodyScroll = useRef(new Map<string, number>());
  const pendingBodyScrollY = useRef<number | null>(null);
  const prefixStatsRef = useRef(new Map<string, number>());

  useEffect(() => {
    const body = document.querySelector('.app-stack-root .app-push__body');
    if (!(body instanceof HTMLElement)) return;
    const key = stackBodyScrollKey(stack);
    if (!key) return;

    const save = () => {
      pushBodyScroll.current.set(key, body.scrollTop);
    };
    body.addEventListener('scroll', save, { passive: true });
    return () => {
      save();
      body.removeEventListener('scroll', save);
    };
  }, [stack]);

  useLayoutEffect(() => {
    const body = document.querySelector('.app-stack-root .app-push__body');
    if (!(body instanceof HTMLElement)) return;

    if (stack.kind === 'code' || stack.kind === 'prefix' || stack.kind === 'facet') {
      pendingBodyScrollY.current = null;
      body.scrollTop = 0;
      return;
    }

    const key = stackBodyScrollKey(stack);
    if (!key) return;
    const y = pushBodyScroll.current.get(key) ?? 0;
    if (y <= 0) {
      pendingBodyScrollY.current = null;
      body.scrollTop = 0;
      return;
    }
    pendingBodyScrollY.current = y;
    const max = body.scrollHeight - body.clientHeight;
    if (max > 0) {
      body.scrollTop = Math.min(y, max);
      if (Math.abs(body.scrollTop - Math.min(y, max)) <= 2) {
        pendingBodyScrollY.current = null;
      }
    }
  }, [stack]);

  useEffect(() => {
    if (pendingBodyScrollY.current == null) return;
    const body = document.querySelector('.app-stack-root .app-push__body');
    if (!(body instanceof HTMLElement)) return;
    const attempt = () => {
      if (pendingBodyScrollY.current == null) return;
      const y = pendingBodyScrollY.current;
      const max = body.scrollHeight - body.clientHeight;
      if (max <= 0) return;
      const target = Math.min(y, max);
      body.scrollTop = target;
      if (Math.abs(body.scrollTop - target) <= 2) {
        pendingBodyScrollY.current = null;
      }
    };
    attempt();
    const ro = new ResizeObserver(attempt);
    ro.observe(body);
    const raf = requestAnimationFrame(attempt);
    const t1 = window.setTimeout(attempt, 60);
    const t2 = window.setTimeout(attempt, 200);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [stack]);

  const refreshHub = useCallback(async () => {
    setLoadingHub(true);
    try {
      const cached = getLibraryRegionsCache();
      if (cached?.regions?.length) {
        setRegions(cached.regions);
        setReady(
          Boolean(cached.ready || cached.regions.some((r) => (r.codeCount || 0) > 0)),
        );
      }
      const overview = await fetchLibraryRegions().catch(() => null);
      const list =
        overview?.regions && overview.regions.length > 0
          ? overview.regions
          : MAKER_FS_FALLBACK_REGIONS;
      if (overview) setLibraryRegionsCache(overview);
      setRegions(list);
      setReady(
        Boolean(overview?.ready || overview?.regions?.some((r) => (r.codeCount || 0) > 0)),
      );
    } finally {
      setLoadingHub(false);
    }
  }, []);

  useEffect(() => {
    void refreshHub();
  }, [refreshHub]);

  useEffect(() => {
    const onSynced = () => {
      clearLibraryBrowseCaches();
      setStack({ kind: 'hub' });
      setQ('');
      setPrefixTotal(null);
      void refreshHub();
    };
    window.addEventListener(LIBRARY_SYNCED, onSynced);
    return () => window.removeEventListener(LIBRARY_SYNCED, onSynced);
  }, [refreshHub]);

  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/makers') return;
    if (tabCtx.tabReselect > 0) {
      setStack({ kind: 'hub' });
      setQ('');
      setPrefixTotal(null);
      void refreshHub();
    }
  }, [tabCtx?.tabReselect, tabCtx?.activeTab, refreshHub]);

  const makers = useMemo((): MakerFsMakerGroup[] => {
    if (stack.kind !== 'region' && stack.kind !== 'maker') return [];
    const list = groupMakerFsByMaker(stack.catalog.prefixes, stack.region.id);
    if (stack.kind === 'maker') return list;
    const key = q.trim().toLowerCase();
    if (!key) return list;
    return list
      .map((m) => {
        if (m.maker.toLowerCase().includes(key)) return m;
        const prefixes = m.prefixes.filter((p) =>
          makerFsPrefixMatchesQuery(p, key, m.maker),
        );
        if (prefixes.length === 0) return null;
        return {
          ...m,
          prefixes,
          prefixCount: prefixes.length,
          codeCount: prefixes.reduce((n, p) => n + (p.codeCount || 0), 0),
        };
      })
      .filter((m): m is MakerFsMakerGroup => m != null);
  }, [stack, q]);

  async function openRegion(region: MakerFsRegionSummary) {
    const cached = getLibraryCatalogCache(region.id);
    if (cached) {
      setQ('');
      setPrefixTotal(null);
      startTransition(() => {
        setStack({ kind: 'region', region, catalog: cached });
      });
      void fetchLibraryRegion(region.id)
        .then((catalog) => {
          setLibraryCatalogCache(region.id, catalog);
          setStack((s) =>
            s.kind === 'region' && s.region.id === region.id
              ? { ...s, catalog }
              : s,
          );
        })
        .catch(() => undefined);
      return;
    }
    setOpening(true);
    try {
      const catalog = await fetchLibraryRegion(region.id);
      setLibraryCatalogCache(region.id, catalog);
      setQ('');
      setPrefixTotal(null);
      startTransition(() => {
        setStack({ kind: 'region', region, catalog });
      });
    } catch {
      setStack({ kind: 'hub' });
    } finally {
      setOpening(false);
    }
  }

  function openMaker(
    region: MakerFsRegionSummary,
    catalog: MakerFsRegionCatalog,
    group: MakerFsMakerGroup,
  ) {
    setQ('');
    setPrefixTotal(null);
    startTransition(() => {
      setStack({ kind: 'maker', region, catalog, maker: group.maker, group });
    });
  }

  function openPrefix(
    region: MakerFsRegionSummary,
    catalog: MakerFsRegionCatalog,
    maker: string,
    prefix: string,
  ) {
    setQ('');
    setPrefixTotal(null);
    startTransition(() => {
      setStack({ kind: 'prefix', region, catalog, maker, prefix });
    });
  }

  /** 仅番号卡片：片商内精确库搜（不跳首页） */
  function searchCode(code: string) {
    if (stack.kind !== 'prefix') return;
    const next = code.trim();
    if (!next) return;
    setStack({
      kind: 'code',
      region: stack.region,
      catalog: stack.catalog,
      maker: stack.maker,
      prefix: stack.prefix,
      code: next,
    });
  }

  function searchCodeFromFacet(code: string, studio: string, prefix: string) {
    if (stack.kind !== 'facet') return;
    const next = code.trim();
    const st = studio.trim();
    const pref = prefix.trim();
    if (!next || !st || !pref) return;
    setStack({
      kind: 'code',
      region: stack.region,
      catalog: stack.catalog,
      maker: st,
      prefix: pref,
      code: next,
      viaFacet: {
        facetKind: stack.facetKind,
        facetValue: stack.facetValue,
        facetCount: stack.facetCount,
      },
    });
  }

  const hub = (
    <div className="app-hub" aria-hidden={stack.kind !== 'hub'}>
      <div className="app-hub__scroll mk-hub">
        <h1 className="app-hub__title">片商</h1>
        {!ready && !loadingHub ? (
          <p className="app-empty" style={{ marginTop: 8 }}>
            片商目录暂无厂牌内容（结构：分区 / 厂牌 / 前缀 / 番号）
          </p>
        ) : null}
        <div className="mk-zone-list">
          {regions.map((r, i) => {
            const meta = regionMeta(r.id);
            return (
              <button
                key={r.id}
                type="button"
                className="mk-zone-row"
                data-zone={i % 4}
                disabled={opening || loadingHub}
                onPointerDown={() => prefetchLibraryRegion(r.id)}
                onClick={() => void openRegion(r)}
              >
                <span className="mk-zone-row__mark" aria-hidden>
                  {meta.mark}
                </span>
                <span className="mk-zone-row__body">
                  <span className="mk-zone-row__name">{r.label}</span>
                  <span className="mk-zone-row__meta">{regionRowMeta(r)}</span>
                </span>
                <ChevronRight
                  className="mk-zone-row__chev"
                  size={18}
                  strokeWidth={2.25}
                  aria-hidden
                />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );

  let push = null;

  if (stack.kind === 'region') {
    const showPrefs = showBrowsePrefs(stack.region);
    const noun = makerFsGroupNoun(stack.region.id);
    push = (
      <AppPush
        title={stack.region.label}
        onBack={() => setStack({ kind: 'hub' })}
        right={
          showPrefs ? (
            <BrowsePrefToggles compact onChange={() => setPrefsTick((n) => n + 1)} />
          ) : undefined
        }
      >
        <div className="app-search-row mk-region-search" style={{ marginTop: 0, marginBottom: 10 }}>
          <div className="app-search">
            <Search className="app-search-icon" aria-hidden />
            <input
              placeholder={`本页筛选${noun} / 前缀 / 女优 / 标签`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
          </div>
          <button
            type="button"
            className="mk-region-facet-btn"
            title="标签与系列"
            onClick={() => {
              setQ('');
              startTransition(() => {
                setStack({
                  kind: 'facets',
                  region: stack.region,
                  catalog: stack.catalog,
                });
              });
            }}
          >
            <Tags size={16} strokeWidth={2.25} aria-hidden />
            <span>索引</span>
          </button>
        </div>
        {makers.length === 0 ? (
          <p className="app-empty">
            {ready ? '无匹配' : `暂无${noun}，请先同步本地片库`}
          </p>
        ) : (
          <MakerPosterGrid
            regionId={stack.region.id}
            overlay="center"
            items={makers.map((g) => {
              const desc = makerDescription(g.maker);
              const cover = pickMakerGroupCover(g);
              return {
                key: g.maker,
                label: g.maker,
                title: desc || undefined,
                posterLocal: cover.posterLocal,
                posterRev: cover.posterRev,
                coverUrl: cover.coverUrl,
                coverUrls: cover.coverUrls,
                coverCode: cover.coverCode,
                onClick: () => openMaker(stack.region, stack.catalog, g),
              };
            })}
          />
        )}
      </AppPush>
    );
  } else if (stack.kind === 'facets') {
    push = (
      <AppPush
        title="索引"
        onBack={() =>
          setStack({
            kind: 'region',
            region: stack.region,
            catalog: stack.catalog,
          })
        }
      >
        <MakerFacetBrowseBody
          regionId={stack.region.id}
          catalog={stack.catalog}
          onOpenFacet={(facetKind, facetValue, facetCount) => {
            startTransition(() => {
              setStack({
                kind: 'facet',
                region: stack.region,
                catalog: stack.catalog,
                facetKind,
                facetValue,
                facetCount,
              });
            });
          }}
        />
      </AppPush>
    );
  } else if (stack.kind === 'facet') {
    push = (
      <AppPush
        title={stack.facetValue}
        onBack={() =>
          setStack({
            kind: 'facets',
            region: stack.region,
            catalog: stack.catalog,
          })
        }
      >
        <MakerFacetCodesBody
          regionId={stack.region.id}
          kind={stack.facetKind}
          value={stack.facetValue}
          onOpenCode={searchCodeFromFacet}
        />
      </AppPush>
    );
  } else if (stack.kind === 'maker') {
    const g = stack.group;
    const showPrefs = showBrowsePrefs(stack.region);
    const key = q.trim().toLowerCase();
    const prefixes = !key
      ? g.prefixes
      : g.prefixes.filter((p) => makerFsPrefixMatchesQuery(p, key, g.maker));
    push = (
      <AppPush
        title={stack.maker}
        onBack={() =>
          setStack({
            kind: 'region',
            region: stack.region,
            catalog: stack.catalog,
          })
        }
        right={
          showPrefs ? (
            <BrowsePrefToggles compact onChange={() => setPrefsTick((n) => n + 1)} />
          ) : undefined
        }
      >
        <div className="app-search-row" style={{ marginTop: 0, marginBottom: 10 }}>
          <div className="app-search">
            <Search className="app-search-icon" aria-hidden />
            <input
              placeholder="本页筛选前缀 / 女优 / 标签"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
          </div>
        </div>
        {prefixes.length === 0 ? (
          <p className="app-empty">无匹配</p>
        ) : (
          <MakerPosterGrid
            regionId={stack.region.id}
            overlay="center"
            items={prefixes.map((p) => {
              const note = prefixNote(g.maker, p.prefix);
              return {
                key: p.prefix,
                label: p.prefix,
                title: note || undefined,
                posterLocal: p.posterLocal,
                posterRev: p.posterRev,
                coverUrl: p.coverUrl,
                coverUrls: p.coverUrls,
                coverCode: p.coverCode,
                onClick: () =>
                  openPrefix(stack.region, stack.catalog, g.maker, p.prefix),
              };
            })}
          />
        )}
      </AppPush>
    );
  } else if (stack.kind === 'prefix') {
    const prefixKey = prefixStackKey(
      stack.region.id,
      stack.maker,
      stack.prefix,
      q,
    );
    const knownTotal = prefixStatsRef.current.get(prefixKey);
    const displayTotal = prefixTotal ?? knownTotal ?? null;
    const hint =
      displayTotal == null
        ? '读取本地片库…'
        : displayTotal > 0
          ? q.trim()
            ? `匹配 ${formatMakerFsCount(displayTotal)} 个`
            : `片库 ${formatMakerFsCount(displayTotal)} 个番号`
          : q.trim()
            ? '无匹配'
            : '本地片库暂无番号';
    const showPrefs = showBrowsePrefs(stack.region);
    push = (
      <AppPush
        title={stack.prefix}
        onBack={() => {
          const list = groupMakerFsByMaker(stack.catalog.prefixes, stack.region.id);
          const group = list.find((m) => m.maker === stack.maker);
          if (group) {
            setStack({
              kind: 'maker',
              region: stack.region,
              catalog: stack.catalog,
              maker: stack.maker,
              group,
            });
            return;
          }
          setStack({
            kind: 'region',
            region: stack.region,
            catalog: stack.catalog,
          });
        }}
        right={
          showPrefs ? (
            <BrowsePrefToggles compact onChange={() => setPrefsTick((n) => n + 1)} />
          ) : undefined
        }
      >
        <div className="mk-prefix-page">
          <div className="mk-prefix-page__top">
            <div className="app-search-row" style={{ marginTop: 0, marginBottom: 8 }}>
              <div className="app-search">
                <Search className="app-search-icon" aria-hidden />
                <input
                  placeholder={`本页筛选 ${stack.prefix} 番号 / 标题 / 女优 / 标签`}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  enterKeyHint="search"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                />
              </div>
            </div>
            <p className="app-hint" style={{ marginTop: 0, marginBottom: 8 }}>
              {hint}
            </p>
          </div>
          <div className="mk-prefix-codes">
            <PrefixCodeGrid
              prefix={stack.prefix}
              region={stack.region.id}
              studio={stack.maker}
              query={q}
              onOpenCode={searchCode}
              onStatusChange={(st) => {
                if (!st || st.loading) return;
                prefixStatsRef.current.set(prefixKey, st.total);
                setPrefixTotal(st.total);
              }}
            />
          </div>
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'code') {
    const showPrefs = showBrowsePrefs(stack.region);
    const via = stack.viaFacet;
    push = (
      <AppPush
        title={stack.code}
        onBack={() => {
          if (via) {
            setStack({
              kind: 'facet',
              region: stack.region,
              catalog: stack.catalog,
              facetKind: via.facetKind,
              facetValue: via.facetValue,
              facetCount: via.facetCount,
            });
            return;
          }
          setStack({
            kind: 'prefix',
            region: stack.region,
            catalog: stack.catalog,
            maker: stack.maker,
            prefix: stack.prefix,
          });
        }}
        right={
          showPrefs ? (
            <BrowsePrefToggles compact onChange={() => setPrefsTick((n) => n + 1)} />
          ) : undefined
        }
      >
        <MakerCodeSearchBody
          code={stack.code}
          cropRegion={stack.region.id}
          prefsTick={prefsTick}
          applyBrowsePrefs={showPrefs}
        />
      </AppPush>
    );
  }

  return (
    <div className="app-stack-root">
      {hub}
      {push}
    </div>
  );
}
