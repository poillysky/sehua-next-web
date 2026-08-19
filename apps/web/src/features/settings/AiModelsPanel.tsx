'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  connectAiEmbed,
  connectAiLlm,
  getAiEmbed,
  getAiLlm,
  getAiPresets,
  putAiEmbed,
  putAiLlm,
  testAiEmbed,
  testAiLlm,
  type AiEmbedConfig,
  type AiLlmConfig,
  type AiPresetOption,
  type AiPresets,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

const LLM_BASE_DEFAULT = 'https://api.openai.com/v1';
const LLM_MODEL_DEFAULT = 'gpt-4o-mini';
const EMBED_MODEL_DEFAULT = 'BAAI/bge-small-zh-v1.5';

type AiTab = 'llm' | 'embed';

const TABS: { key: AiTab; label: string }[] = [
  { key: 'llm', label: '聊天' },
  { key: 'embed', label: '向量' },
];

function hubStatus(llm: AiLlmConfig | null, embed: AiEmbedConfig | null): string {
  const llmOk = Boolean(llm?.enabled && llm?.configured);
  const embOk = Boolean(embed?.enabled && embed?.configured);
  if (llmOk && embOk) return '已就绪';
  if (llmOk) return '聊天已配';
  if (embOk) return '向量已配';
  return '未配置';
}

function numStr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '';
  return String(v);
}

function presetDim(model: string, presets: AiPresets | null): string {
  if (!presets) return '';
  const all = [...presets.localEmbedModels, ...presets.openaiEmbedModels];
  const hit = all.find((m) => m.value === model);
  if (hit?.dim) return hit.dim;
  const lower = model.toLowerCase();
  if (lower.includes('large')) return '3072';
  if (lower.includes('small') || lower.includes('ada')) return '1536';
  if (lower.includes('base')) return '768';
  return '';
}

function FormCard({ children }: { children: ReactNode }) {
  return <section className="ai-card">{children}</section>;
}

function SettingRow({
  label,
  children,
  stack,
}: {
  label: string;
  children: ReactNode;
  stack?: boolean;
}) {
  return (
    <div className={cn('ai-row', stack && 'ai-row--stack')}>
      <span className="ai-row__label">{label}</span>
      <div className="ai-row__control">{children}</div>
    </div>
  );
}

function renderSourceOptions(list: AiPresetOption[], start: number, end?: number) {
  return list.slice(start, end).map((o) => (
    <option key={o.value} value={o.value}>
      {o.label}
    </option>
  ));
}

export function AiModelsPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [tab, setTab] = useState<AiTab>('llm');
  const [presets, setPresets] = useState<AiPresets | null>(null);

  const [llmEnabled, setLlmEnabled] = useState(true);
  const [llmSource, setLlmSource] = useState('custom');
  const [llmBaseUrl, setLlmBaseUrl] = useState(LLM_BASE_DEFAULT);
  const [llmModel, setLlmModel] = useState(LLM_MODEL_DEFAULT);
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmHint, setLlmHint] = useState('');
  const [llmFromEnv, setLlmFromEnv] = useState(false);
  const [llmShowKey, setLlmShowKey] = useState(true);
  const [llmPostProcess, setLlmPostProcess] = useState('');
  const [llmHeaders, setLlmHeaders] = useState('');
  const [llmTimeout, setLlmTimeout] = useState('30');
  const [llmTemp, setLlmTemp] = useState('');
  const [llmTopP, setLlmTopP] = useState('');
  const [llmMaxTokens, setLlmMaxTokens] = useState('');
  const [llmFreqPenalty, setLlmFreqPenalty] = useState('');
  const [llmPresPenalty, setLlmPresPenalty] = useState('');
  const [llmAdvanced, setLlmAdvanced] = useState(false);
  const [modelList, setModelList] = useState<string[]>([]);
  const [connectHint, setConnectHint] = useState('');
  const [embedModelList, setEmbedModelList] = useState<string[]>([]);
  const [embedConnectHint, setEmbedConnectHint] = useState('');

  const [embedEnabled, setEmbedEnabled] = useState(true);
  const [embedProvider, setEmbedProvider] = useState<'local' | 'openai'>('local');
  const [embedUseMainLlm, setEmbedUseMainLlm] = useState(false);
  const [embedBaseUrl, setEmbedBaseUrl] = useState(LLM_BASE_DEFAULT);
  const [embedModel, setEmbedModel] = useState(EMBED_MODEL_DEFAULT);
  const [embedDim, setEmbedDim] = useState('512');
  const [embedTopK, setEmbedTopK] = useState('8');
  const [embedMinScore, setEmbedMinScore] = useState('0.35');
  const [embedChunkSize, setEmbedChunkSize] = useState('500');
  const [embedApiKey, setEmbedApiKey] = useState('');
  const [embedHint, setEmbedHint] = useState('');
  const [embedFromEnv, setEmbedFromEnv] = useState(false);
  const [embedShowKey, setEmbedShowKey] = useState(true);

  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  function publish(llm: AiLlmConfig, embed: AiEmbedConfig) {
    const text = hubStatus(llm, embed);
    onStatus(text, text === '未配置' ? 'warn' : 'ok');
  }

  function applyLlm(llm: AiLlmConfig) {
    setLlmEnabled(llm.enabled !== false);
    setLlmSource(llm.chatCompletionSource || 'custom');
    setLlmBaseUrl(llm.baseUrl || LLM_BASE_DEFAULT);
    setLlmModel(llm.model || LLM_MODEL_DEFAULT);
    setLlmHint(llm.apiKeyHint || '');
    setLlmFromEnv(Boolean(llm.fromEnvKey || llm.fromEnv));
    setLlmShowKey(!llm.configured || Boolean(llm.fromEnvKey));
    setLlmPostProcess(llm.promptPostProcessing || '');
    setLlmHeaders(llm.customIncludeHeaders || '');
    setLlmTimeout(String(llm.timeoutSec || 30));
    const s = llm.sampling || {};
    setLlmTemp(numStr(s.temperature));
    setLlmTopP(numStr(s.topP));
    setLlmMaxTokens(numStr(s.maxTokens));
    setLlmFreqPenalty(numStr(s.frequencyPenalty));
    setLlmPresPenalty(numStr(s.presencePenalty));
  }

  function applyEmbed(embed: AiEmbedConfig) {
    setEmbedEnabled(embed.enabled !== false);
    setEmbedProvider(embed.provider === 'openai' ? 'openai' : 'local');
    setEmbedUseMainLlm(Boolean(embed.useMainLlm));
    setEmbedBaseUrl(embed.baseUrl || LLM_BASE_DEFAULT);
    setEmbedModel(embed.model || EMBED_MODEL_DEFAULT);
    setEmbedDim(String(embed.dim || 512));
    setEmbedTopK(String(embed.topK ?? 8));
    setEmbedMinScore(String(embed.minScore ?? 0.35));
    setEmbedChunkSize(String(embed.chunkSize ?? 500));
    setEmbedHint(embed.apiKeyHint || '');
    setEmbedFromEnv(Boolean(embed.fromEnv));
    setEmbedShowKey(embed.provider === 'openai' && !embed.configured);
  }

  useEffect(() => {
    void (async () => {
      try {
        const [llm, embed, p] = await Promise.all([getAiLlm(), getAiEmbed(), getAiPresets()]);
        setPresets(p);
        applyLlm(llm);
        applyEmbed(embed);
        publish(llm, embed);
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '读取失败');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function llmSamplingBody() {
    const parse = (s: string) => {
      const t = s.trim();
      if (!t) return undefined;
      const n = Number(t);
      return Number.isFinite(n) ? n : undefined;
    };
    return {
      temperature: parse(llmTemp),
      topP: parse(llmTopP),
      maxTokens: parse(llmMaxTokens) != null ? Math.round(parse(llmMaxTokens)!) : undefined,
      frequencyPenalty: parse(llmFreqPenalty),
      presencePenalty: parse(llmPresPenalty),
    };
  }

  function llmBody() {
    const timeout = parseInt(llmTimeout, 10);
    return {
      enabled: llmEnabled,
      chatCompletionSource: llmSource,
      apiMode: 'chat',
      baseUrl: llmBaseUrl.trim(),
      model: llmModel.trim(),
      apiKey: llmApiKey.trim(),
      promptPostProcessing: llmPostProcess,
      customIncludeHeaders: llmHeaders.trim(),
      timeoutSec: Number.isFinite(timeout) ? timeout : 30,
      sampling: llmSamplingBody(),
    };
  }

  function embedBody() {
    const dim = parseInt(embedDim, 10);
    const topK = parseInt(embedTopK, 10);
    const minScore = parseFloat(embedMinScore);
    const chunkSize = parseInt(embedChunkSize, 10);
    return {
      enabled: embedEnabled,
      provider: embedProvider,
      useMainLlm: embedUseMainLlm,
      baseUrl: embedBaseUrl.trim(),
      model: embedModel.trim(),
      apiKey: embedApiKey.trim(),
      dim: Number.isFinite(dim) ? dim : 512,
      topK: Number.isFinite(topK) ? topK : 8,
      minScore: Number.isFinite(minScore) ? minScore : 0.35,
      chunkSize: Number.isFinite(chunkSize) ? chunkSize : 500,
    };
  }

  function switchTab(next: AiTab) {
    setTab(next);
    setMsg('');
  }

  function onLlmSourceChange(value: string) {
    setLlmSource(value);
    const preset = presets?.chatSources.find((x) => x.value === value);
    if (preset?.baseUrl) setLlmBaseUrl(preset.baseUrl);
  }

  function onEmbedModelChange(value: string) {
    setEmbedModel(value);
    const dim = presetDim(value, presets);
    if (dim) setEmbedDim(dim);
  }

  async function onConnectLlm() {
    setBusy(true);
    setMsg('');
    setConnectHint('');
    try {
      const r = await connectAiLlm({
        baseUrl: llmBaseUrl.trim(),
        apiKey: llmApiKey.trim() || undefined,
        customIncludeHeaders: llmHeaders.trim() || undefined,
      });
      setModelList(r.models);
      setConnectHint(r.message || `已拉取 ${r.modelCount} 个模型`);
    } catch (e) {
      setModelList([]);
      setConnectHint(e instanceof Error ? e.message : '连接失败');
    } finally {
      setBusy(false);
    }
  }

  async function onConnectEmbed() {
    setBusy(true);
    setEmbedConnectHint('');
    try {
      const r = await connectAiEmbed({
        provider: embedProvider,
        useMainLlm: embedUseMainLlm,
        baseUrl: embedBaseUrl.trim() || undefined,
        apiKey: embedApiKey.trim() || undefined,
      });
      setEmbedModelList(r.models);
      setEmbedConnectHint(r.message || '连接成功');
    } catch (e) {
      setEmbedModelList([]);
      setEmbedConnectHint(e instanceof Error ? e.message : '连接失败');
    } finally {
      setBusy(false);
    }
  }

  async function onTestLlm() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testAiLlm(llmBody());
      setMsg(r.message || (r.ok ? '聊天模型正常' : '失败'));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSaveLlm() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putAiLlm(llmBody());
      applyLlm(next);
      setLlmApiKey('');
      const embed = await getAiEmbed();
      publish(next, embed);
      setMsg('聊天模型已保存');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  async function onTestEmbed() {
    setBusy(true);
    setMsg('');
    try {
      const r = await testAiEmbed(embedBody());
      const dim = r.dim;
      if (typeof dim === 'number' && dim > 0 && String(dim) !== embedDim) {
        setEmbedDim(String(dim));
        setMsg(`${r.message || '测试成功'} · 维度已改为 ${dim}`);
      } else {
        setMsg(r.message || (r.ok ? '向量模型正常' : '失败'));
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '测试失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEmbed() {
    setBusy(true);
    setMsg('');
    try {
      const next = await putAiEmbed(embedBody());
      applyEmbed(next);
      setEmbedApiKey('');
      const llm = await getAiLlm();
      publish(llm, next);
      setMsg('向量模型已保存');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  const chatSources = presets?.chatSources || [];
  const localModels = presets?.localEmbedModels || [];
  const openaiModels = presets?.openaiEmbedModels || [];
  const postOptions = presets?.promptPostProcessing || [];

  const llmConfigured = Boolean(llmHint || llmFromEnv);
  const llmStatusText = !llmEnabled
    ? '已关闭'
    : llmFromEnv
      ? '环境变量'
      : llmConfigured
        ? '已配置'
        : '未配置';
  const llmStatusTone =
    !llmEnabled ? 'mute' : llmConfigured || llmFromEnv ? 'ok' : 'warn';

  const embedStatusText = !embedEnabled
    ? '已关闭'
    : embedProvider === 'local'
      ? '本地'
      : embedUseMainLlm
        ? '沿用聊天'
        : embedHint
          ? '已配置'
          : '未配置';
  const embedStatusTone =
    !embedEnabled ? 'mute' : embedProvider === 'local' || embedHint || embedUseMainLlm ? 'ok' : 'warn';

  return (
    <AppPush title="AI 模型" onBack={onBack} bodyClassName="ai-models-panel">
      <div className="app-seg" role="tablist" aria-label="AI 模型分页">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={cn('app-seg__btn', tab === t.key && 'app-seg__btn--active')}
            onClick={() => switchTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'llm' ? (
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
                {(postOptions.length > 0 ? postOptions : [{ value: '', label: '未选择' }]).map((o) => (
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
                  <span className="settings-nav__title">采样与高级</span>
                  <span className="settings-nav__desc">Temperature · Top P · Headers</span>
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
              <SettingRow label="Temperature">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  placeholder="0.7"
                  value={llmTemp}
                  onChange={(e) => setLlmTemp(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Top P">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  placeholder="1"
                  value={llmTopP}
                  onChange={(e) => setLlmTopP(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Max Tokens">
                <input
                  className="allow-select ai-input"
                  inputMode="numeric"
                  placeholder="2048"
                  value={llmMaxTokens}
                  onChange={(e) => setLlmMaxTokens(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Freq Penalty">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  placeholder="0"
                  value={llmFreqPenalty}
                  onChange={(e) => setLlmFreqPenalty(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
              <SettingRow label="Pres Penalty">
                <input
                  className="allow-select ai-input"
                  inputMode="decimal"
                  placeholder="0"
                  value={llmPresPenalty}
                  onChange={(e) => setLlmPresPenalty(e.target.value)}
                  disabled={busy}
                />
              </SettingRow>
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

          <AppFootnote>环境变量 LLM_* 可覆盖 SQLite 配置。</AppFootnote>
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
      ) : (
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
              <SettingRow label="模型">
                <select
                  className="allow-select ai-input ai-input--select"
                  value={embedModel}
                  onChange={(e) => onEmbedModelChange(e.target.value)}
                  disabled={busy || embedFromEnv}
                >
                  {(embedModelList.length > 0 ? embedModelList : localModels.map((m) => m.value)).map(
                    (id) => {
                      const preset = localModels.find((m) => m.value === id);
                      return (
                        <option key={id} value={id}>
                          {preset?.label || id}
                        </option>
                      );
                    },
                  )}
                </select>
              </SettingRow>
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
            <AppFootnote>本地 BGE 中文模型，供色花语义检索灌库。</AppFootnote>
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
      )}

      <AppMsg allowSelect onDismiss={() => setMsg('')}>
        {msg}
      </AppMsg>
    </AppPush>
  );
}

export { hubStatus as aiModelsHubStatus };
