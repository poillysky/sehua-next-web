'use client';

import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { type StatusReporter } from '@/hooks/usePanelAction';
import { TABS } from './format';
import { useP115Panel } from './useP115Panel';
import { P115Overview } from './P115Overview';
import { P115ConfigTab } from './P115ConfigTab';
import { P115TasksTab } from './P115TasksTab';

export function P115Panel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const p = useP115Panel({ onBack, onStatus });

  return (
    <AppPush title="115 转存" onBack={onBack}>
      <div className="p115-console">
        {!p.configured ? (
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">状态</span>
                <span className="settings-nav__status settings-nav__status--warn">
                  待配置
                </span>
              </div>
            </li>
          </ul>
        ) : (
          <div className="app-seg" role="tablist" aria-label="115 转存工作台">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={p.tab === t.key}
                className={cn('app-seg__btn', p.tab === t.key && 'app-seg__btn--active')}
                onClick={() => p.setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {p.tab === 'overview' && p.configured ? <P115Overview p={p} /> : null}
        {p.tab === 'config' ? <P115ConfigTab p={p} /> : null}
        {p.tab === 'tasks' && p.configured ? <P115TasksTab p={p} /> : null}

        <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
          {p.msg}
        </AppMsg>
      </div>
    </AppPush>
  );
}
