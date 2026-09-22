import { Switch } from '@/components/ui/switch';
import { FIELD_PRIORITY_RESTORE } from './defaults';
import { PriorityChainPicker } from './PriorityChainPicker';
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
  const visibleFields = fpHideEmpty
    ? fields.filter((f) => ((cfg.fieldPriority || {})[f.id] || []).length > 0)
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
          return (
            <PriorityChainPicker
              key={field.id}
              rowId={field.id}
              label={field.label}
              chain={chain}
              open={fpOpen === field.id}
              busy={busy}
              sources={sources}
              dataAttr="data-enrich-fp-box"
              emptyLabel="默认"
              menuHint="↑↓ 调序；总开关关闭的源会灰显且不参与合并"
              onToggleOpen={() =>
                setFpOpen((cur) => (cur === field.id ? null : field.id))
              }
              onToggle={(sid) => toggleFieldPrioritySite(field.id, sid)}
              onMove={(sid, dir) => moveFieldPrioritySite(field.id, sid, dir)}
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
