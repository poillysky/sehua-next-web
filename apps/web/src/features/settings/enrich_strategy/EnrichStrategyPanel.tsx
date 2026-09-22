'use client';

import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { ChevronRight } from 'lucide-react';
import type { ScrapEnrichStrategy } from '@/lib/api';
import type { StatusReporter } from '@/hooks/usePanelAction';
import { useEnrichStrategyForm } from './useEnrichStrategyForm';
import type { SectionId } from './types';
import { FillSection } from './FillSection';
import { ScheduleSection } from './ScheduleSection';
import { RegionsSection } from './RegionsSection';
import { FieldsSection } from './FieldsSection';
import { MapsSection } from './MapsSection';
import { CoverSection } from './CoverSection';

export function EnrichStrategyPanel({
  onBack,
  onStatus,
  onSaved,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
  onSaved?: (cfg: ScrapEnrichStrategy) => void;
}) {
  const form = useEnrichStrategyForm(onStatus, onSaved);
  const {
    section,
    setSection,
    setFpOpen,
    setRsOpen,
    cfg,
    msg,
    setMsg,
    busy,
    hubRows,
    flushPendingPersist,
    onSave,
  } = form;

  const sectionTitle: Record<SectionId, string> = {
    fill: '补齐与女优',
    schedule: '调度与并发',
    regions: '优先级设置(全局)',
    fields: '字段优先级',
    maps: '元数据优化',
    cover: '刮削封面',
  };

  if (section) {
    return (
      <AppPush
        title={sectionTitle[section]}
        onBack={() => {
          flushPendingPersist();
          setSection(null);
          setFpOpen(null);
          setRsOpen(null);
        }}
        skipEnterAnimation
        scrollKey={`enrich-strategy-${section}`}
      >
        <div className="makers-manage makers-manage--detail enrich-strategy">
          {msg ? (
            <AppMsg
              allowSelect
              tone={
                msg === '已保存' || msg === '已自动保存' ? 'ok' : 'warn'
              }
              onDismiss={() => setMsg('')}
            >
              {msg}
            </AppMsg>
          ) : null}
          {!cfg ? (
            <p className="settings-group-label">加载中…</p>
          ) : (
            <>
              {section === 'fill'
                ? <FillSection {...form} />
                : section === 'schedule'
                  ? <ScheduleSection {...form} />
                  : section === 'regions'
                    ? <RegionsSection {...form} />
                    : section === 'fields'
                      ? <FieldsSection {...form} />
                      : section === 'maps'
                        ? <MapsSection {...form} />
                        : <CoverSection {...form} />}
              <div className="app-actions">
                <button
                  type="button"
                  className="app-btn-primary"
                  disabled={busy}
                  onClick={() => void onSave()}
                >
                  {busy ? '保存中…' : '保存'}
                </button>
              </div>
            </>
          )}
        </div>
      </AppPush>
    );
  }

  return (
    <AppPush title="刮削策略" onBack={onBack}>
      <div className="makers-manage makers-manage--detail enrich-strategy">
        {msg ? (
          <AppMsg
            allowSelect
            tone={
              msg === '已保存' || msg === '已自动保存' ? 'ok' : 'warn'
            }
            onDismiss={() => setMsg('')}
          >
            {msg}
          </AppMsg>
        ) : null}

        {!cfg ? (
          <p className="settings-group-label">加载中…</p>
        ) : (
          <>
            <p className="settings-group-label">策略分组</p>
            <ul className="settings-group makers-manage__rise">
              {hubRows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className="settings-nav makers-manage__catalog-row"
                    disabled={busy}
                    onClick={() => {
                      setSection(row.id);
                      setFpOpen(null);
                    }}
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{row.title}</span>
                      <span className="settings-nav__desc">{row.desc}</span>
                    </span>
                    <ChevronRight
                      className="settings-nav__chev"
                      size={17}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                </li>
              ))}
            </ul>

            <div className="app-actions">
              <button
                type="button"
                className="app-btn-primary"
                disabled={busy}
                onClick={() => void onSave()}
              >
                {busy ? '保存中…' : '保存'}
              </button>
            </div>
          </>
        )}
      </div>
    </AppPush>
  );
}
