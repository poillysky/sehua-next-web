import { Check } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { MODE_OPTIONS, digitsOnly } from './defaults';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function ScheduleSection({
  adaptiveWorkersText,
  allowFlare,
  busy,
  cfg,
  commitAdaptiveWorkers,
  commitFlareWorkers,
  commitItemWorkers,
  commitTimeout,
  flareOn,
  flareWorkersText,
  itemWorkersText,
  mode,
  patch,
  setAdaptiveWorkersText,
  setFlareWorkersText,
  setItemWorkersText,
  setMode,
  setTimeoutText,
  showFlareWorkers,
  timeoutText,
}: EnrichStrategyForm) {
    if (!cfg) return null;
    const workersLabel =
      mode === 'parallel_all' && flareOn ? '并发上限' : '自适应并发';
    return (
      <>
        <p className="settings-group-label">调度模式</p>
        <ul
          className="settings-group enrich-strategy__choice-group"
          role="radiogroup"
          aria-label="调度模式"
        >
          {MODE_OPTIONS.map((m) => {
            const on = mode === m.value;
            return (
              <li key={m.value}>
                <button
                  type="button"
                  className={cn(
                    'settings-kv enrich-strategy__choice-row',
                    on && 'enrich-strategy__choice-row--on',
                  )}
                  disabled={busy}
                  role="radio"
                  aria-checked={on}
                  onClick={() => setMode(m.value)}
                >
                  <span className="settings-nav__main">
                    <span className="settings-kv__key">{m.label}</span>
                    <span className="settings-nav__desc enrich-strategy__mode-desc">
                      {m.desc}
                    </span>
                  </span>
                  <span
                    className={cn(
                      'enrich-strategy__check',
                      on && 'enrich-strategy__check--on',
                    )}
                    aria-hidden
                  >
                    {on ? <Check strokeWidth={2.5} /> : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        <p className="settings-group-label settings-group-label--spaced">选项</p>
        <ul className="settings-group">
          {allowFlare ? (
            <li>
              <div className="settings-kv enrich-strategy__mode-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">包含过盾源</span>
                  <span className="settings-nav__desc enrich-strategy__mode-desc">
                    {mode === 'adaptive_first'
                      ? '自适应未补齐时再调度 Flare'
                      : '过盾源一并参与并发'}
                  </span>
                </span>
                <Switch
                  checked={flareOn}
                  disabled={busy}
                  onCheckedChange={(v) => patch({ includeFlare: Boolean(v) })}
                />
              </div>
            </li>
          ) : null}
          <li>
            <div className="settings-kv enrich-strategy__mode-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">机翻过烂时大模型译中</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  无可用中文或机翻垃圾时，用设置里的 LLM 译标题/剧情
                </span>
              </span>
              <Switch
                checked={cfg.llmTranslateOnJunk !== false}
                disabled={busy}
                onCheckedChange={(v) =>
                  patch({ llmTranslateOnJunk: Boolean(v) })
                }
              />
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          并发参数
        </p>
        <ul className="settings-group enrich-strategy__params">
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">番号并发</span>
                <span className="settings-nav__desc">同时刮几部 · 1–16</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={itemWorkersText}
                disabled={busy}
                aria-label="番号并发"
                onChange={(e) =>
                  setItemWorkersText(digitsOnly(e.target.value))
                }
                onBlur={() => commitItemWorkers()}
              />
            </label>
          </li>
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">{workersLabel}</span>
                <span className="settings-nav__desc">0 = 不限制</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={adaptiveWorkersText}
                disabled={busy}
                aria-label={workersLabel}
                onChange={(e) =>
                  setAdaptiveWorkersText(digitsOnly(e.target.value))
                }
                onBlur={() => commitAdaptiveWorkers()}
              />
            </label>
          </li>
          {showFlareWorkers ? (
            <li>
              <label className="settings-kv enrich-strategy__param-row">
                <span className="settings-nav__main">
                  <span className="settings-kv__key">过盾并发</span>
                  <span className="settings-nav__desc">0 = 不限制</span>
                </span>
                <input
                  type="text"
                  className="allow-select enrich-strategy__num"
                  inputMode="numeric"
                  value={flareWorkersText}
                  disabled={busy}
                  aria-label="过盾并发"
                  onChange={(e) =>
                    setFlareWorkersText(digitsOnly(e.target.value))
                  }
                  onBlur={() => commitFlareWorkers()}
                />
              </label>
            </li>
          ) : null}
          <li>
            <label className="settings-kv enrich-strategy__param-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">单源超时</span>
                <span className="settings-nav__desc">单位：秒</span>
              </span>
              <input
                type="text"
                className="allow-select enrich-strategy__num"
                inputMode="numeric"
                value={timeoutText}
                disabled={busy}
                aria-label="单源超时（秒）"
                onChange={(e) => setTimeoutText(digitsOnly(e.target.value))}
                onBlur={() => commitTimeout()}
              />
            </label>
          </li>
        </ul>
      </>
    );
  }
