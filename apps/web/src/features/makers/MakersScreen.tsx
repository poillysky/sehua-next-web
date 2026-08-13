'use client';

import { startTransition, useCallback, useEffect, useMemo, useState } from 'react';
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
  LIBRARY_SYNCED,
  MAKER_FS_FALLBACK_REGIONS,
  type MakerFsMakerGroup,
} from '@/lib/makerFsUi';
import { makerDescription, makerKind, prefixNote } from '@/config/av-makers';
import { useTabNavigation } from '@/shell';
import { AppPush } from '@/components/ui/AppPush';
import { BrowsePrefToggles } from '@/components/BrowsePrefToggles';
import { PrefixCodeGrid } from '@/features/boards/PrefixCodeGrid';
import { MakerCodeSearchBody } from './MakerCodeSearchBody';
import { MakerFacetBrowseBody } from './MakerFacetBrowseBody';
import { MakerFacetCodesBody } from './MakerFacetCodesBody';

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
      /** 从标签/系列进入时，返回该分类页 */
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

  const refreshHub = useCallback(async () => {
    setLoadingHub(true);
    try {
      const overview = await fetchLibraryRegions().catch(() => null);
      const list =
        overview?.regions && overview.regions.length > 0
          ? overview.regions
          : MAKER_FS_FALLBACK_REGIONS;
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

  useEffect(() => {
    if (tabCtx?.activeTab === '/makers') {
      void refreshHub();
    }
  }, [tabCtx?.activeTab, refreshHub]);

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
    setOpening(true);
    try {
      const catalog = await fetchLibraryRegion(region.id);
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
            暂无片库，请到设置 → 本地索引 → 扫库后「同步本地片库」
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
            <span>分类</span>
          </button>
        </div>
        {makers.length === 0 ? (
          <p className="app-empty">
            {ready ? '无匹配' : `暂无${noun}，请先同步本地片库`}
          </p>
        ) : (
          <ul className="settings-group">
            {makers.map((g) => {
              const desc = makerDescription(g.maker);
              const kind = makerKind(g.maker);
              return (
                <li key={g.maker}>
                  <button
                    type="button"
                    className="settings-nav"
                    onClick={() => openMaker(stack.region, stack.catalog, g)}
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{g.maker}</span>
                      <span className="settings-nav__desc">
                        {kind ? `${kind} · ` : ''}
                        {g.prefixCount} 前缀 · {formatMakerFsCount(g.codeCount)} 条
                        {desc ? ` · ${desc}` : ''}
                      </span>
                    </span>
                    <ChevronRight
                      className="settings-nav__chev"
                      size={18}
                      strokeWidth={2.25}
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </AppPush>
    );
  } else if (stack.kind === 'facets') {
    push = (
      <AppPush
        title="标签与系列"
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
          <div className="mk-maker-card__grid" style={{ paddingBottom: 12 }}>
            {prefixes.map((p) => {
              const note = prefixNote(g.maker, p.prefix);
              const codes = p.codeCount ?? 0;
              return (
                <button
                  key={p.prefix}
                  type="button"
                  className="mk-maker-tile"
                  title={note || p.prefix}
                  onClick={() =>
                    openPrefix(stack.region, stack.catalog, g.maker, p.prefix)
                  }
                >
                  <span className="mk-maker-tile__code allow-select">{p.prefix}</span>
                  {note ? (
                    <span className="mk-maker-tile__note">{note}</span>
                  ) : codes > 0 ? (
                    <span className="mk-maker-tile__note">
                      {formatMakerFsCount(codes)} 条
                    </span>
                  ) : (
                    <span
                      className="mk-maker-tile__note mk-maker-tile__note--empty"
                      aria-hidden
                    />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </AppPush>
    );
  } else if (stack.kind === 'prefix') {
    const hint =
      prefixTotal == null
        ? '读取本地片库…'
        : prefixTotal > 0
          ? q.trim()
            ? `匹配 ${formatMakerFsCount(prefixTotal)} 个`
            : `片库 ${formatMakerFsCount(prefixTotal)} 个番号`
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
                if (!st) {
                  setPrefixTotal(null);
                  return;
                }
                if (!st.loading) setPrefixTotal(st.total);
              }}
            />
          </div>
        </div>
      </AppPush>
    );
  } else if (stack.kind === 'code') {
    const dbRegion = String(stack.region.dbRegion || stack.region.id || '').trim();
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
          region={dbRegion || undefined}
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
