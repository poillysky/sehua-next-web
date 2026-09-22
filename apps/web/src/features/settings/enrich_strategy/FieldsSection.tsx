import { Check, ChevronDown, X } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { FIELD_PRIORITY_RESTORE } from './shared';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function FieldsSection({
  autoSaving,
  busy,
  cfg,
  fpHideEmpty,
  fpOpen,
  moveFieldPrioritySite,
  patchAndPersist,
  setFpHideEmpty,
  setFpOpen,
  toggleFieldPrioritySite,
}: EnrichStrategyForm) {
    if (!cfg) return null;
    const fields = cfg.fieldPriorityFields?.length
      ? cfg.fieldPriorityFields
      : [
          { id: 'title', label: '标题' },
          { id: 'overview', label: '简介' },
          { id: 'poster', label: '海报' },
          { id: 'actors', label: '女优' },
          { id: 'studio', label: '片商' },
          { id: 'maker', label: '制作商' },
          { id: 'date', label: '发行日' },
          { id: 'year', label: '年份' },
          { id: 'tags', label: '标签' },
        ];
    const sources = cfg.sourceOptions?.length ? cfg.sourceOptions : [];
    const labelOf = (sid: string) =>
      sources.find((s) => s.id === sid)?.label || sid;
    const isOn = (sid: string) =>
      sources.find((s) => s.id === sid)?.enabled !== false;
    const visibleFields = fpHideEmpty
      ? fields.filter(
          (f) => ((cfg.fieldPriority || {})[f.id] || []).length > 0,
        )
      : fields;
    const configuredCount = fields.filter(
      (f) => ((cfg.fieldPriority || {})[f.id] || []).length > 0,
    ).length;

    return (
      <div className="enrich-strategy__rs">
        <p className="enrich-strategy__rs-note settings-nav__desc">
          仅对有码区生效；无码 / 素人 / FC2 等只看「优先级设置(全局)」分区源。
        </p>
        <div className="enrich-strategy__rs-toolbar enrich-strategy__rs-toolbar--split">
          <label className="enrich-strategy__rs-hide">
            <span>隐藏未配置</span>
            <Switch
              checked={fpHideEmpty}
              disabled={busy || autoSaving}
              onCheckedChange={(v) => {
                const on = Boolean(v);
                setFpHideEmpty(on);
                patchAndPersist((prev) => ({
                  ...prev,
                  fieldPriorityHideEmpty: on,
                }));
              }}
            />
          </label>
          <span className="enrich-strategy__rs-count">
            {configuredCount}/{fields.length} 已配
          </span>
        </div>
        <ul className="enrich-strategy__rs-list">
          {visibleFields.map((field) => {
            const chain = (cfg.fieldPriority || {})[field.id] || [];
            const open = fpOpen === field.id;
            return (
              <li key={field.id} className="enrich-strategy__rs-row">
                <span className="enrich-strategy__rs-label">{field.label}</span>
                <div
                  className={cn(
                    'enrich-strategy__rs-box',
                    open && 'enrich-strategy__rs-box--open',
                  )}
                  data-enrich-fp-box={field.id}
                >
                  <button
                    type="button"
                    className="enrich-strategy__rs-trigger"
                    disabled={busy}
                    aria-expanded={open}
                    aria-haspopup="listbox"
                    aria-label={`${field.label} 优先级`}
                    onClick={() =>
                      setFpOpen((cur) => (cur === field.id ? null : field.id))
                    }
                  >
                    <span className="enrich-strategy__rs-tags">
                      {chain.length === 0 ? (
                        <span className="enrich-strategy__rs-empty">默认</span>
                      ) : (
                        chain.map((sid, idx) => (
                          <span
                            key={`${field.id}-tag-${sid}`}
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
                                toggleFieldPrioritySite(field.id, sid);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  toggleFieldPrioritySite(field.id, sid);
                                }
                              }}
                            >
                              <X size={11} strokeWidth={2.6} aria-hidden />
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
                      aria-label={`${field.label} 可选源`}
                    >
                      {chain.length > 1 ? (
                        <div className="enrich-strategy__rs-menu-hint">
                          ↑↓ 调序；总开关关闭的源会灰显且不参与合并
                        </div>
                      ) : null}
                      {chain.map((sid, idx) => (
                        <div
                          key={`${field.id}-sel-${sid}`}
                          className={cn(
                            'enrich-strategy__rs-menu-row enrich-strategy__rs-menu-row--on',
                            !isOn(sid) && 'enrich-strategy__rs-menu-row--off',
                          )}
                        >
                          <button
                            type="button"
                            className="enrich-strategy__rs-menu-main"
                            disabled={busy}
                            onClick={() =>
                              toggleFieldPrioritySite(field.id, sid)
                            }
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
                                moveFieldPrioritySite(field.id, sid, -1)
                              }
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              disabled={busy || idx >= chain.length - 1}
                              aria-label="后移"
                              onClick={() =>
                                moveFieldPrioritySite(field.id, sid, 1)
                              }
                            >
                              ↓
                            </button>
                          </span>
                        </div>
                      ))}
                      {sources
                        .filter((s) => !chain.includes(s.id))
                        .map((src) => (
                          <button
                            key={`${field.id}-opt-${src.id}`}
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
                              toggleFieldPrioritySite(field.id, src.id)
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
              const defaults = FIELD_PRIORITY_RESTORE;
              patchAndPersist((prev) => ({
                ...prev,
                fieldPriority: Object.fromEntries(
                  Object.entries(defaults).map(([k, v]) => [k, [...v]]),
                ),
                fieldPriorityDefaults: Object.fromEntries(
                  Object.entries(defaults).map(([k, v]) => [k, [...v]]),
                ),
              }));
              setFpOpen(null);
            }}
          >
            恢复默认
          </button>
        </div>
      </div>
    );
  }
