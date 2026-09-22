import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  REGION_SOURCE_RESTORE,
  UNCENSORED_OFFICIAL_FALLBACK,
} from './shared';
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
    const labelOf = (sid: string) =>
      sources.find((s) => s.id === sid)?.label || sid;
    const isOn = (sid: string) =>
      sources.find((s) => s.id === sid)?.enabled !== false;
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
            const open = rsOpen === region.id;
            return (
              <li key={region.id} className="enrich-strategy__rs-row">
                <span className="enrich-strategy__rs-label">{region.label}</span>
                <div
                  className={cn(
                    'enrich-strategy__rs-box',
                    open && 'enrich-strategy__rs-box--open',
                  )}
                  data-enrich-rs-box={region.id}
                >
                  <button
                    type="button"
                    className="enrich-strategy__rs-trigger"
                    disabled={busy}
                    aria-expanded={open}
                    aria-haspopup="listbox"
                    aria-label={`${region.label} 源优先级`}
                    onClick={() =>
                      setRsOpen((cur) =>
                        cur === region.id ? null : region.id,
                      )
                    }
                  >
                    <span className="enrich-strategy__rs-tags">
                      {chain.length === 0 ? (
                        <span className="enrich-strategy__rs-empty">点选添加源</span>
                      ) : (
                        chain.map((sid, idx) => (
                          <span
                            key={`${region.id}-tag-${sid}`}
                            className={cn(
                              'enrich-strategy__rs-tag',
                              !isOn(sid) && 'enrich-strategy__rs-tag--off',
                            )}
                            title={
                              isOn(sid)
                                ? `${idx + 1}. ${labelOf(sid)}`
                                : `${labelOf(sid)} · 已关总开关，不参与`
                            }
                          >
                            <span className="enrich-strategy__rs-tag-text">
                              {labelOf(sid)}
                            </span>
                            <span
                              role="button"
                              tabIndex={-1}
                              className="enrich-strategy__rs-tag-x"
                              aria-label={`移除 ${labelOf(sid)}`}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                toggleRegionSource(region.id, sid);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  toggleRegionSource(region.id, sid);
                                }
                              }}
                            >
                              <X size={12} strokeWidth={2.4} aria-hidden />
                            </span>
                          </span>
                        ))
                      )}
                    </span>
                    <ChevronDown
                      className={cn(
                        'enrich-strategy__rs-chev',
                        open && 'enrich-strategy__rs-chev--open',
                      )}
                      size={16}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                  {open ? (
                    <div
                      className="enrich-strategy__rs-menu"
                      role="listbox"
                      aria-multiselectable
                      aria-label={`${region.label} 可选源`}
                    >
                      {chain.length > 1 ? (
                        <div className="enrich-strategy__rs-menu-hint">
                          ↑↓ 调序；总开关关闭的源会灰显且不参与刮削
                        </div>
                      ) : null}
                      {chain.map((sid, idx) => (
                        <div
                          key={`${region.id}-sel-${sid}`}
                          className={cn(
                            'enrich-strategy__rs-menu-row enrich-strategy__rs-menu-row--on',
                            !isOn(sid) && 'enrich-strategy__rs-menu-row--off',
                          )}
                        >
                          <button
                            type="button"
                            className="enrich-strategy__rs-menu-main"
                            disabled={busy}
                            onClick={() => toggleRegionSource(region.id, sid)}
                          >
                            <Check
                              className="enrich-strategy__rs-menu-check"
                              size={15}
                              strokeWidth={2.6}
                              aria-hidden
                            />
                            <span>
                              {idx + 1}. {labelOf(sid)}
                              {!isOn(sid) ? ' · 已关' : ''}
                            </span>
                          </button>
                          <span className="enrich-strategy__rs-menu-move">
                            <button
                              type="button"
                              disabled={busy || idx === 0}
                              aria-label="前移"
                              onClick={() =>
                                moveRegionSource(region.id, sid, -1)
                              }
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={busy || idx >= chain.length - 1}
                              aria-label="后移"
                              onClick={() =>
                                moveRegionSource(region.id, sid, 1)
                              }
                            >
                              ↓
                            </button>
                          </span>
                        </div>
                      ))}
                      {sources
                        .filter(
                          (s) =>
                            !chain.includes(s.id) &&
                            !(
                              region.id === 'japan_uncensored' &&
                              officialSet.has(s.id)
                            ),
                        )
                        .map((src) => (
                          <button
                            key={`${region.id}-opt-${src.id}`}
                            type="button"
                            className={cn(
                              'enrich-strategy__rs-menu-row',
                              src.enabled === false &&
                                'enrich-strategy__rs-menu-row--off',
                            )}
                            role="option"
                            aria-selected={false}
                            disabled={busy}
                            onClick={() =>
                              toggleRegionSource(region.id, src.id)
                            }
                          >
                            <span className="enrich-strategy__rs-menu-check enrich-strategy__rs-menu-check--off" />
                            <span>
                              {src.label}
                              {src.enabled === false ? ' · 已关' : ''}
                            </span>
                          </button>
                        ))}
                    </div>
                  ) : null}
                </div>
              </li>
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
