'use client';

import { Switch } from '@/components/ui/switch';
import { AppFootnote } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { FormCard, SettingRow } from './ui';
import {
  LLM_BASE_DEFAULT,
  normalizeEmbedDevice,
} from './helpers';
import type { AiModelsPanelState } from './useAiModelsPanel';

export function AiEmbedTab({ p }: { p: AiModelsPanelState }) {
  const {
    embedModel,
    embedStatusTone,
    embedStatusText,
    embedEnabled,
    setEmbedEnabled,
    busy,
    embedProvider,
    setEmbedProvider,
    embedUseMainLlm,
    setEmbedUseMainLlm,
    embedFromEnv,
    localModels,
    openaiModels,
    onEmbedModelChange,
    embedModelList,
    embedDevice,
    setEmbedDevice,
    deviceOptions,
    embedBaseUrl,
    setEmbedBaseUrl,
    embedHint,
    embedShowKey,
    setEmbedShowKey,
    embedApiKey,
    setEmbedApiKey,
    onConnectEmbed,
    onDownloadEmbed,
    embedConnectHint,
    embedDim,
    setEmbedDim,
    embedTopK,
    setEmbedTopK,
    embedMinScore,
    setEmbedMinScore,
    embedChunkSize,
    setEmbedChunkSize,
    onTestEmbed,
    onSaveEmbed,
  } = p;

  return (
    <>
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">当前模型</span>
            <span className="settings-kv__val allow-select">{embedModel || '—'}</span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span
              className={cn(
                'settings-nav__status',
                embedStatusTone === 'ok' && 'settings-nav__status--ok',
                embedStatusTone === 'warn' && 'settings-nav__status--warn',
              )}
            >
              {embedStatusText}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">启用</span>
            <Switch checked={embedEnabled} onCheckedChange={setEmbedEnabled} disabled={busy} />
          </div>
        </li>
        {embedProvider === 'openai' ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">沿用聊天</span>
              <Switch
                checked={embedUseMainLlm}
                onCheckedChange={setEmbedUseMainLlm}
                disabled={busy}
              />
            </div>
          </li>
        ) : null}
      </ul>

      <p className="settings-group-label">嵌入模型</p>
      <FormCard>
        <SettingRow label="来源">
          <select
            className="allow-select ai-input ai-input--select"
            value={embedProvider}
            onChange={(e) => {
              const next = e.target.value === 'openai' ? 'openai' : 'local';
              setEmbedProvider(next);
              if (next === 'local' && localModels[0]) {
                onEmbedModelChange(localModels[0].value);
              } else if (next === 'openai' && openaiModels[0]) {
                onEmbedModelChange(openaiModels[0].value);
              }
            }}
            disabled={busy || embedFromEnv}
          >
            <option value="local">本地 fastembed</option>
            <option value="openai">OpenAI 兼容</option>
          </select>
        </SettingRow>

        {embedProvider === 'local' ? (
          <>
            <SettingRow label="模型">
              <select
                className="allow-select ai-input ai-input--select"
                value={embedModel}
                onChange={(e) => onEmbedModelChange(e.target.value)}
                disabled={busy || embedFromEnv}
              >
                {(embedModelList.length > 0
                  ? embedModelList
                  : localModels.map((m) => m.value)
                ).map((id) => {
                  const preset = localModels.find((m) => m.value === id);
                  return (
                    <option key={id} value={id}>
                      {preset?.label || id}
                    </option>
                  );
                })}
              </select>
            </SettingRow>
            <SettingRow label="推理">
              <select
                className="allow-select ai-input ai-input--select"
                value={embedDevice}
                onChange={(e) =>
                  setEmbedDevice(normalizeEmbedDevice(e.target.value))
                }
                disabled={busy || embedFromEnv}
              >
                {deviceOptions.map((d) => {
                  const tag =
                    d.available === true
                      ? '可用'
                      : d.available === false
                        ? '未检测'
                        : '';
                  return (
                    <option key={d.value} value={d.value}>
                      {d.label}
                      {tag ? ` · ${tag}` : ''}
                    </option>
                  );
                })}
              </select>
            </SettingRow>
          </>
        ) : (
          <>
            {!embedUseMainLlm ? (
              <SettingRow label="端点">
                <input
                  className="allow-select ai-input"
                  placeholder={LLM_BASE_DEFAULT}
                  value={embedBaseUrl}
                  onChange={(e) => setEmbedBaseUrl(e.target.value)}
                  disabled={busy || embedFromEnv}
                  spellCheck={false}
                />
              </SettingRow>
            ) : null}
            {!embedUseMainLlm ? (
              embedHint && !embedShowKey ? (
                <SettingRow label="密钥">
                  <div className="ai-key-saved">
                    <span className="allow-select">{embedHint}</span>
                    <button
                      type="button"
                      className="settings-inline-action"
                      disabled={busy}
                      onClick={() => setEmbedShowKey(true)}
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
                    placeholder={embedHint ? `已配置 ${embedHint}` : 'embeddings Key'}
                    value={embedApiKey}
                    onChange={(e) => setEmbedApiKey(e.target.value)}
                    disabled={busy}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </SettingRow>
              )
            ) : null}
            <SettingRow label="模型">
              <input
                className="allow-select ai-input"
                placeholder="text-embedding-3-small"
                value={embedModel}
                onChange={(e) => onEmbedModelChange(e.target.value)}
                disabled={busy || embedFromEnv}
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
              />
            </SettingRow>
            <SettingRow label="列表">
              <select
                className="allow-select ai-input ai-input--select"
                value={embedModelList.includes(embedModel) ? embedModel : ''}
                onChange={(e) => {
                  if (e.target.value) onEmbedModelChange(e.target.value);
                }}
                disabled={busy}
              >
                <option value="">
                  {embedModelList.length ? '从列表选择…' : '先点连接'}
                </option>
                {embedModelList.map((m) => (
                  <option key={m} value={m}>
                    {openaiModels.find((x) => x.value === m)?.label || m}
                  </option>
                ))}
              </select>
            </SettingRow>
          </>
        )}

        <div className="ai-row ai-row--action">
          <button
            type="button"
            className="app-btn-secondary ai-row__btn"
            disabled={busy}
            onClick={() => void onConnectEmbed()}
          >
            {embedProvider === 'local' ? '刷新本地模型' : '连接并拉取模型'}
          </button>
          {embedProvider === 'local' ? (
            <button
              type="button"
              className="app-btn-secondary ai-row__btn"
              disabled={busy || !embedModel.trim()}
              onClick={() => void onDownloadEmbed()}
            >
              下载模型
            </button>
          ) : null}
        </div>
      </FormCard>
      {embedConnectHint ? (
        <p
          className={cn(
            'ai-models-hint',
            embedConnectHint.includes('失败') || embedConnectHint.includes('无效')
              ? 'ai-models-hint--err'
              : 'ai-models-hint--ok',
          )}
        >
          {embedConnectHint}
        </p>
      ) : null}

      <FormCard>
        <SettingRow label="维度">
          <input
            className="allow-select ai-input"
            inputMode="numeric"
            placeholder="512"
            value={embedDim}
            onChange={(e) => setEmbedDim(e.target.value)}
            disabled={busy || embedProvider === 'local'}
            spellCheck={false}
          />
        </SettingRow>
      </FormCard>

      <p className="settings-group-label">检索参数</p>
      <FormCard>
        <SettingRow label="Top K">
          <input
            className="allow-select ai-input"
            inputMode="numeric"
            placeholder="8"
            value={embedTopK}
            onChange={(e) => setEmbedTopK(e.target.value)}
            disabled={busy}
          />
        </SettingRow>
        <SettingRow label="最低相似度">
          <input
            className="allow-select ai-input"
            inputMode="decimal"
            placeholder="0.35"
            value={embedMinScore}
            onChange={(e) => setEmbedMinScore(e.target.value)}
            disabled={busy}
          />
        </SettingRow>
        <SettingRow label="分块大小">
          <input
            className="allow-select ai-input"
            inputMode="numeric"
            placeholder="500"
            value={embedChunkSize}
            onChange={(e) => setEmbedChunkSize(e.target.value)}
            disabled={busy}
          />
        </SettingRow>
      </FormCard>

      {embedProvider === 'local' ? (
        <AppFootnote>
          本地多语种向量。推理可选 CPU / N卡(CUDA) / A卡(DirectML)。灌库入口：片商管理 →
          六区目录。
        </AppFootnote>
      ) : embedUseMainLlm ? (
        <AppFootnote>沿用聊天 tab 的端点与密钥。</AppFootnote>
      ) : null}

      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={busy}
          onClick={() => void onTestEmbed()}
        >
          测试
        </button>
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => void onSaveEmbed()}
        >
          保存
        </button>
      </div>
    </>
  );
}
