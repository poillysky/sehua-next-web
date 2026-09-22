import {
  REGION_SOURCE_RESTORE,
  UNCENSORED_OFFICIAL_FALLBACK,
} from './defaults';
import { PriorityChainPicker } from './PriorityChainPicker';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function RegionsSection({
  autoSaving,
  busy,
  cfg,
  moveRegionSource,
  patchAndPersist,
  regions,
  rsOpen,
  setRsOpen,
  toggleRegionSource,
}: EnrichStrategyForm) {
  if (!cfg) return null;
  const sources = cfg.sourceOptions?.length ? cfg.sourceOptions : [];
  const officialSet = new Set(
    (cfg.uncensoredOfficialSources?.length
      ? cfg.uncensoredOfficialSources
      : UNCENSORED_OFFICIAL_FALLBACK
    ).map((s) => s),
  );
  const visibleChain = (regionId: string, chain: string[]) =>
    regionId === 'japan_uncensored'
      ? chain.filter((sid) => !officialSet.has(sid))
      : chain;

  return (
    <div className="enrich-strategy__rs">
      <p className="enrich-strategy__rs-note">
        {cfg.uncensoredOfficialHint ||
          '无码：专用站按番号前缀自动启用（含 Tokyo Hot / Nyoshin）；此处只排通用兜底站。'}
      </p>
      <ul className="enrich-strategy__rs-list">
        {regions.map((region) => {
          const chain = visibleChain(
            region.id,
            (cfg.regionSources || {})[region.id] || region.sources || [],
          );
          return (
            <PriorityChainPicker
              key={region.id}
              rowId={region.id}
              label={region.label}
              chain={chain}
              open={rsOpen === region.id}
              busy={busy}
              sources={sources}
              dataAttr="data-enrich-rs-box"
              emptyLabel="点选添加源"
              menuHint="↑↓ 调序；总开关关闭的源会灰显且不参与刮削"
              excludeIds={
                region.id === 'japan_uncensored' ? officialSet : undefined
              }
              onToggleOpen={() =>
                setRsOpen((cur) => (cur === region.id ? null : region.id))
              }
              onToggle={(sid) => toggleRegionSource(region.id, sid)}
              onMove={(sid, dir) => moveRegionSource(region.id, sid, dir)}
            />
          );
        })}
      </ul>
      <div className="enrich-strategy__rs-foot">
        <button
          type="button"
          className="enrich-strategy__rs-reset"
          disabled={busy || autoSaving}
          onClick={() => {
            const nextMap: Record<string, string[]> = {};
            for (const r of regions) {
              nextMap[r.id] = [
                ...(REGION_SOURCE_RESTORE[r.id] ||
                  cfg.regionSourceDefaults?.[r.id] ||
                  []),
              ];
            }
            patchAndPersist((prev) => ({
              ...prev,
              regionSources: nextMap,
              regionSourceDefaults: Object.fromEntries(
                Object.entries(REGION_SOURCE_RESTORE).map(([k, v]) => [
                  k,
                  [...v],
                ]),
              ),
              regions: (prev.regions || []).map((r) => ({
                ...r,
                sources: [...(nextMap[r.id] || [])],
              })),
            }));
            setRsOpen(null);
          }}
        >
          恢复默认
        </button>
      </div>
    </div>
  );
}
