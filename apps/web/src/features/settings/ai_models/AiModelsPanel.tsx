'use client';

import { getAiLlm } from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { type StatusReporter } from '@/hooks/usePanelAction';
import { ChatPresetsSection } from '../ChatPresetsSection';
import { TABS } from './helpers';
import { useAiModelsPanel } from './useAiModelsPanel';
import { AiLlmTab } from './AiLlmTab';
import { AiEmbedTab } from './AiEmbedTab';
import { AiXiaohuaTab } from './AiXiaohuaTab';

export function AiModelsPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  const p = useAiModelsPanel({ onBack, onStatus });

  return (
    <AppPush title="AI 模型" onBack={onBack} bodyClassName="ai-models-panel">
      <div className="app-seg" role="tablist" aria-label="AI 模型分页">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={p.tab === t.key}
            className={cn('app-seg__btn', p.tab === t.key && 'app-seg__btn--active')}
            onClick={() => p.switchTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {p.tab === 'llm' ? (
        <AiLlmTab p={p} />
      ) : p.tab === 'preset' ? (
        <ChatPresetsSection
          onSamplingApplied={() => {
            void (async () => {
              try {
                const llm = await getAiLlm();
                p.applyLlm(llm);
              } catch {
                /* ignore */
              }
            })();
          }}
        />
      ) : p.tab === 'embed' ? (
        <AiEmbedTab p={p} />
      ) : (
        <AiXiaohuaTab p={p} />
      )}

      <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
        {p.msg}
      </AppMsg>
    </AppPush>
  );
}

export { aiModelsHubStatus } from './useAiModelsPanel';
