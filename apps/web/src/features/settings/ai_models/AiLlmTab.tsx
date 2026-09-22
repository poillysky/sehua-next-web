'use client';

import { ChevronRight } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { AppFootnote } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { FormCard, SettingRow } from './ui';
import { LLM_BASE_DEFAULT, LLM_MODEL_DEFAULT, renderSourceOptions } from './helpers';
import type { AiModelsPanelState } from './useAiModelsPanel';

export function AiLlmTab({ p }: { p: AiModelsPanelState }) {
  const {
    llmModel,
    llmStatusTone,
    llmStatusText,
    llmEnabled,
    setLlmEnabled,
    busy,
    llmSource,
    onLlmSourceChange,
    llmFromEnv,
    chatSources,
    llmBaseUrl,
    setLlmBaseUrl,
    llmHint,
    llmShowKey,
    setLlmShowKey,
    llmApiKey,
    setLlmApiKey,
    setLlmModel,
    modelList,
    llmPostProcess,
    setLlmPostProcess,
    postOptions,
    onConnectLlm,
    connectHint,
    llmAdvanced,
    setLlmAdvanced,
    llmTimeout,
    setLlmTimeout,
    llmHeaders,
    setLlmHeaders,
    onTestLlm,
    onSaveLlm,
  } = p;

  return (
    <>
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">当前模型</span>
            <span className="settings-kv__val allow-select">{llmModel || '—'}</span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">密钥</span>
            <span
              className={cn(
                'settings-nav__status',
                llmStatusTone === 'ok' && 'settings-nav__status--ok',
                llmStatusTone === 'warn' && 'settings-nav__status--warn',
              )}
            >
              {llmStatusText}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">启用</span>
            <Switch checked={llmEnabled} onCheckedChange={setLlmEnabled} disabled={busy} />
          </div>
        </li>
      </ul>

      <p className="settings-group-label">连接配置</p>
      <FormCard>
        <SettingRow label="来源">
          <select
            className="allow-select ai-input"
            value={llmSource}
            onChange={(e) => onLlmSourceChange(e.target.value)}
            disabled={busy || llmFromEnv}
          >
            {chatSources.length > 0 ? (
              <>
                <optgroup label="常用">{renderSourceOptions(chatSources, 0, 3)}</optgroup>
                <optgroup label="兼容">{renderSourceOptions(chatSources, 3, 12)}</optgroup>
                <optgroup label="更多">{renderSourceOptions(chatSources, 12)}</optgroup>
              </>
            ) : (
              <option value="custom">自定义</option>
            )}
          </select>
        </SettingRow>
        <SettingRow label="端点">
          <input
            className="allow-select ai-input"
            placeholder={LLM_BASE_DEFAULT}
            value={llmBaseUrl}
            onChange={(e) => setLlmBaseUrl(e.target.value)}
            disabled={busy || llmFromEnv}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </SettingRow>
        {llmHint && !llmShowKey ? (
          <SettingRow label="密钥">
            <div className="ai-key-saved">
              <span className="allow-select">{llmHint}</span>
              <button
                type="button"
                className="settings-inline-action"
                disabled={busy}
                onClick={() => setLlmShowKey(true)}
              >
                更换
              </button>
            </div>
          </SettingRow>
        ) : (
          <SettingRow label="密钥">
            <input
              type="password"
              className="allow-select ai-input"
              placeholder={llmHint ? `已配置 ${llmHint}` : 'OpenAI 兼容 Key'}
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              disabled={busy || llmFromEnv}
              autoComplete="off"
              spellCheck={false}
            />
          </SettingRow>
        )}
        <SettingRow label="模型">
          <input
            className="allow-select ai-input"
            placeholder={LLM_MODEL_DEFAULT}
            value={llmModel}
            onChange={(e) => setLlmModel(e.target.value)}
            disabled={busy}
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </SettingRow>
        <SettingRow label="列表">
          <select
            className="allow-select ai-input ai-input--select"
            value={modelList.includes(llmModel) ? llmModel : ''}
            onChange={(e) => {
              if (e.target.value) setLlmModel(e.target.value);
            }}
            disabled={busy}
          >
            <option value="">{modelList.length ? '从列表选择…' : '先点连接'}</option>
            {modelList.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </SettingRow>
        <SettingRow label="后处理">
          <select
            className="allow-select ai-input ai-input--select"
            value={llmPostProcess}
            onChange={(e) => setLlmPostProcess(e.target.value)}
            disabled={busy}
          >
            {(postOptions.length > 0
              ? postOptions
              : [{ value: '', label: '未选择（小花助手忽略）' }]
            ).map((o) => (
              <option key={o.value || 'none'} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </SettingRow>
        <div className="ai-row ai-row--action">
          <button
            type="button"
            className="app-btn-secondary ai-row__btn"
            disabled={busy}
            onClick={() => void onConnectLlm()}
          >
            连接并拉取模型
          </button>
        </div>
      </FormCard>
      {connectHint ? (
        <p
          className={cn(
            'ai-models-hint',
            connectHint.includes('失败') || connectHint.includes('无效')
              ? 'ai-models-hint--err'
              : 'ai-models-hint--ok',
          )}
        >
          {connectHint}
        </p>
      ) : null}

      <ul className="settings-group">
        <li>
          <button
            type="button"
            className="settings-nav"
            onClick={() => setLlmAdvanced((v) => !v)}
          >
            <span className="settings-nav__main">
              <span className="settings-nav__title">连接高级</span>
              <span className="settings-nav__desc">超时 · Headers</span>
            </span>
            <ChevronRight
              className="settings-nav__chev"
              size={16}
              strokeWidth={2.25}
              style={{
                transform: llmAdvanced ? 'rotate(90deg)' : undefined,
                transition: 'transform 0.2s',
              }}
            />
          </button>
        </li>
      </ul>

      {llmAdvanced ? (
        <FormCard>
          <SettingRow label="超时（秒）">
            <input
              className="allow-select ai-input"
              inputMode="numeric"
              placeholder="30"
              value={llmTimeout}
              onChange={(e) => setLlmTimeout(e.target.value)}
              disabled={busy}
            />
          </SettingRow>
          <SettingRow label="Headers" stack>
            <textarea
              className="allow-select ai-textarea"
              rows={3}
              placeholder="X-Custom: value"
              value={llmHeaders}
              onChange={(e) => setLlmHeaders(e.target.value)}
              disabled={busy}
              spellCheck={false}
            />
          </SettingRow>
        </FormCard>
      ) : null}

      <AppFootnote>
        采样参数请到「聊天预设」配置（对齐 BrewStory 对话预设）。环境变量 LLM_* 可覆盖密钥与端点。
      </AppFootnote>
      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={busy}
          onClick={() => void onTestLlm()}
        >
          测试
        </button>
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => void onSaveLlm()}
        >
          保存
        </button>
      </div>
    </>
  );
}
