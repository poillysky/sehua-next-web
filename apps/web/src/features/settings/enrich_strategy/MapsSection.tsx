import { Switch } from '@/components/ui/switch';
import type { ScrapEnrichStrategy } from '@/lib/api';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function MapsSection({
  autoSaving,
  busy,
  cfg,
  patchAndPersist,
}: EnrichStrategyForm) {
    const titleOn = cfg?.localMaps?.title !== 'off';
    const actorsOn = cfg?.localMaps?.actors !== 'off';
    const tagsOn = cfg?.localMaps?.tags !== 'off';
    const nlOn = cfg?.localMaps?.compactOutlineNewlines !== false;

    function patchLocalMaps(
      partial: Partial<NonNullable<ScrapEnrichStrategy['localMaps']>>,
    ) {
      patchAndPersist((prev) => ({
        ...prev,
        localMaps: {
          title: prev.localMaps?.title === 'off' ? 'off' : prev.localMaps?.title === 'force' ? 'force' : 'prefer',
          actors: prev.localMaps?.actors === 'off' ? 'off' : 'fallback',
          tags: prev.localMaps?.tags === 'off' ? 'off' : 'fallback',
          compactOutlineNewlines:
            prev.localMaps?.compactOutlineNewlines !== false,
          ...partial,
        },
      }));
    }

    const rows: Array<{
      key: 'title' | 'actors' | 'tags' | 'nl';
      label: string;
      desc: string;
      checked: boolean;
      onChange: (on: boolean) => void;
    }> = [
      {
        key: 'title',
        label: '色花堂中文标题',
        desc: '源站先出标题，再与映射比分优选（非强制、非兜底）',
        checked: titleOn,
        onChange: (on) =>
          patchLocalMaps({ title: on ? 'prefer' : 'off' }),
      },
      {
        key: 'actors',
        label: '演员数据映射',
        desc: '用内置表规范化演员名（对齐 MDCX）',
        checked: actorsOn,
        onChange: (on) =>
          patchLocalMaps({ actors: on ? 'fallback' : 'off' }),
      },
      {
        key: 'tags',
        label: '标签数据映射',
        desc: '用内置表规范化标签（对齐 MDCX）',
        checked: tagsOn,
        onChange: (on) =>
          patchLocalMaps({ tags: on ? 'fallback' : 'off' }),
      },
      {
        key: 'nl',
        label: '精简多余的换行符',
        desc: '简介中连续换行精简为单个',
        checked: nlOn,
        onChange: (on) =>
          patchLocalMaps({ compactOutlineNewlines: on }),
      },
    ];

    return (
      <>
        <p className="settings-group-label">映射与清洗</p>
        <ul className="settings-group enrich-strategy__fill-group">
          {rows.map((row) => (
            <li key={row.key}>
              <div className="settings-kv enrich-strategy__fill-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">{row.label}</span>
                  <span className="settings-nav__desc enrich-strategy__mode-desc">
                    {row.desc}
                  </span>
                </span>
                <Switch
                  checked={row.checked}
                  disabled={busy || autoSaving}
                  onCheckedChange={row.onChange}
                  aria-label={row.label}
                />
              </div>
            </li>
          ))}
        </ul>
      </>
    );
  }
