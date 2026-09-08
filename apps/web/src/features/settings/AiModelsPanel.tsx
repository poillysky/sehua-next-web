'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  connectAiEmbed,
  connectAiLlm,
  downloadAiEmbed,
  getAiAssistant,
  getAiEmbed,
  getAiLlm,
  getAiPresets,
  getAiWebSearch,
  putAiAssistant,
  putAiEmbed,
  putAiLlm,
  putAiWebSearch,
  testAiEmbed,
  testAiLlm,
  type AiAssistantSkillGroup,
  type AiAssistantToolMeta,
  type AiEmbedConfig,
  type AiEmbedDevice,
  type AiEmbedDeviceOption,
  type AiLlmConfig,
  type AiPresetOption,
  type AiPresets,
} from '@/lib/api';
import { Switch } from '@/components/ui/switch';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import { ChatPresetsSection } from './ChatPresetsSection';

const LLM_BASE_DEFAULT = 'https://api.openai.com/v1';
const LLM_MODEL_DEFAULT = 'gpt-4o-mini';
const EMBED_MODEL_DEFAULT = 'intfloat/multilingual-e5-large';
const EMBED_DEVICE_DEFAULT: AiEmbedDevice = 'directml';

const EMBED_DEVICE_FALLBACK: AiEmbedDeviceOption[] = [
  { value: 'cpu', label: 'CPU', hint: '兼容最好，速度慢' },
  { value: 'cuda', label: 'N卡 (CUDA)', hint: '需 NVIDIA 驱动 + onnxruntime-gpu' },
  { value: 'directml', label: 'A卡 (DirectML)', hint: 'Windows AMD/Intel；需 onnxruntime-directml' },
];

function normalizeEmbedDevice(raw: string | undefined | null): AiEmbedDevice {
  const v = String(raw || '').trim().toLowerCase();
  if (v === 'cuda' || v === 'nvidia' || v === 'n') return 'cuda';
  if (v === 'directml' || v === 'amd' || v === 'a' || v === 'dml') return 'directml';
  if (v === 'cpu') return 'cpu';
  return EMBED_DEVICE_DEFAULT;
}

function deviceLabel(device: AiEmbedDevice, list: AiEmbedDeviceOption[]): string {
  return list.find((d) => d.value === device)?.label || device;
}
type AiTab = 'llm' | 'preset' | 'embed' | 'xiaohua';

const TABS: { key: AiTab; label: string }[] = [
  { key: 'llm', label: '聊天' },
  { key: 'preset', label: '聊天预设' },
  { key: 'embed', label: '向量' },
  { key: 'xiaohua', label: '小花' },
];

const DEFAULT_ASSISTANT_TOOLS: Record<string, boolean> = {
  sehua_keyword: true,
  sehua_semantic: true,
  scrap_search: true,
  scrap_list: true,
  magnet_search: true,
  magnet_semantic: true,
  media_search: true,
  web_search: true,
};

const DEFAULT_SKILL_GROUPS: AiAssistantSkillGroup[] = [
  { id: 'warehouse', label: '仓库', desc: '色花资源库' },
  { id: 'makers', label: '片商', desc: '刮削番号库' },
  { id: 'magnet', label: '磁力', desc: 'Bitmagnet' },
  { id: 'media', label: '影视', desc: 'TMDB 等元数据' },
  { id: 'web', label: '网络', desc: '公开网页搜索' },
];

const DEFAULT_TOOL_META: AiAssistantToolMeta[] = [
  { id: 'sehua_keyword', group: 'warehouse', label: '仓库关键词', desc: '色花标题/文件名搜索' },
  { id: 'sehua_semantic', group: 'warehouse', label: '仓库语义', desc: '向量相近推荐' },
  { id: 'scrap_search', group: 'makers', label: '片商语义', desc: '刮削库向量搜' },
  { id: 'scrap_list', group: 'makers', label: '片商筛选', desc: '女优/厂牌/标签列表' },
  { id: 'magnet_search', group: 'magnet', label: '磁力搜索', desc: 'Bitmagnet 关键词' },
  { id: 'magnet_semantic', group: 'magnet', label: '磁力语义', desc: 'Bitmagnet 向量相近' },
  { id: 'media_search', group: 'media', label: '影视搜索', desc: 'TMDB / 豆瓣等' },
  { id: 'web_search', group: 'web', label: '网络搜索', desc: 'SearXNG / Serper / Brave' },
];

/** 对齐 BrewStory 对话预设默认值 */
const PRESET_DEFAULTS = {
  temperature: '1',
  topP: '1',
  maxTokens: '2048',
  maxContext: '8192',
  frequencyPenalty: '0',
  presencePenalty: '0',
  topK: '',
  minP: '',
  repetitionPenalty: '',
  seed: '-1',
  n: '1',
  streamOpenai: true,
  maxContextUnlocked: false,
  continuePrefill: false,
  squashSystemMessages: false,
  showThoughts: false,
};

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
  const [llmTemp, setLlmTemp] = useState(PRESET_DEFAULTS.temperature);
  const [llmTopP, setLlmTopP] = useState(PRESET_DEFAULTS.topP);
  const [llmMaxTokens, setLlmMaxTokens] = useState(PRESET_DEFAULTS.maxTokens);
  const [llmMaxContext, setLlmMaxContext] = useState(PRESET_DEFAULTS.maxContext);
  const [llmFreqPenalty, setLlmFreqPenalty] = useState(PRESET_DEFAULTS.frequencyPenalty);
  const [llmPresPenalty, setLlmPresPenalty] = useState(PRESET_DEFAULTS.presencePenalty);
  const [llmTopK, setLlmTopK] = useState(PRESET_DEFAULTS.topK);
  const [llmMinP, setLlmMinP] = useState(PRESET_DEFAULTS.minP);
  const [llmRepPenalty, setLlmRepPenalty] = useState(PRESET_DEFAULTS.repetitionPenalty);
  const [llmSeed, setLlmSeed] = useState(PRESET_DEFAULTS.seed);
  const [llmN, setLlmN] = useState(PRESET_DEFAULTS.n);
  const [llmStream, setLlmStream] = useState(PRESET_DEFAULTS.streamOpenai);
  const [llmCtxUnlocked, setLlmCtxUnlocked] = useState(PRESET_DEFAULTS.maxContextUnlocked);
  const [llmContinuePrefill, setLlmContinuePrefill] = useState(PRESET_DEFAULTS.continuePrefill);
  const [llmSquashSystem, setLlmSquashSystem] = useState(PRESET_DEFAULTS.squashSystemMessages);
  const [llmShowThoughts, setLlmShowThoughts] = useState(PRESET_DEFAULTS.showThoughts);
  const [llmAdvanced, setLlmAdvanced] = useState(false);
  const [modelList, setModelList] = useState<string[]>([]);
  const [connectHint, setConnectHint] = useState('');
  const [embedModelList, setEmbedModelList] = useState<string[]>([]);
  const [embedConnectHint, setEmbedConnectHint] = useState('');

  const [embedEnabled, setEmbedEnabled] = useState(true);
  const [embedProvider, setEmbedProvider] = useState<'local' | 'openai'>('local');
  const [embedDevice, setEmbedDevice] = useState<AiEmbedDevice>(EMBED_DEVICE_DEFAULT);
  const [embedDevices, setEmbedDevices] =
    useState<AiEmbedDeviceOption[]>(EMBED_DEVICE_FALLBACK);
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

  const [webEnabled, setWebEnabled] = useState(false);
  const [webProvider, setWebProvider] = useState('searxng');
  const [webBaseUrl, setWebBaseUrl] = useState('http://192.168.2.38:8085');
  const [webApiKey, setWebApiKey] = useState('');
  const [webHint, setWebHint] = useState('');
  const [webShowKey, setWebShowKey] = useState(true);
  const [assistantTools, setAssistantTools] = useState<Record<string, boolean>>(DEFAULT_ASSISTANT_TOOLS);
  const [skillGroups, setSkillGroups] = useState<AiAssistantSkillGroup[]>(DEFAULT_SKILL_GROUPS);
  const [toolMeta, setToolMeta] = useState<AiAssistantToolMeta[]>(DEFAULT_TOOL_META);

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
    setLlmTemp(numStr(s.temperature) || PRESET_DEFAULTS.temperature);
    setLlmTopP(numStr(s.topP) || PRESET_DEFAULTS.topP);
    setLlmMaxTokens(numStr(s.maxTokens) || PRESET_DEFAULTS.maxTokens);
    setLlmMaxContext(numStr(s.maxContext) || PRESET_DEFAULTS.maxContext);
    setLlmFreqPenalty(numStr(s.frequencyPenalty) || PRESET_DEFAULTS.frequencyPenalty);
    setLlmPresPenalty(numStr(s.presencePenalty) || PRESET_DEFAULTS.presencePenalty);
    setLlmTopK(numStr(s.topK));
    setLlmMinP(numStr(s.minP));
    setLlmRepPenalty(numStr(s.repetitionPenalty));
    setLlmSeed(numStr(s.seed) || PRESET_DEFAULTS.seed);
    setLlmN(numStr(s.n) || PRESET_DEFAULTS.n);
    setLlmStream(s.streamOpenai !== false);
    setLlmCtxUnlocked(Boolean(s.maxContextUnlocked));
    setLlmContinuePrefill(Boolean(s.continuePrefill));
    setLlmSquashSystem(Boolean(s.squashSystemMessages));
    setLlmShowThoughts(Boolean(s.showThoughts));
  }

  function applyEmbed(embed: AiEmbedConfig) {
    setEmbedEnabled(embed.enabled !== false);
    setEmbedProvider(embed.provider === 'openai' ? 'openai' : 'local');
    setEmbedDevice(normalizeEmbedDevice(embed.device));
    if (Array.isArray(embed.devices) && embed.devices.length > 0) {
      setEmbedDevices(embed.devices);
    }
    setEmbedUseMainLlm(Boolean(embed.useMainLlm));
    setEmbedBaseUrl(embed.baseUrl || LLM_BASE_DEFAULT);
    setEmbedModel(embed.model || EMBED_MODEL_DEFAULT);
    setEmbedDim(String(embed.dim || 1024));
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
        const [llm, embed, p, web, assistant] = await Promise.all([
          getAiLlm(),
          getAiEmbed(),
          getAiPresets(),
          getAiWebSearch(),
          getAiAssistant(),
        ]);
        setPresets(p);
        applyLlm(llm);
        applyEmbed(embed);
        setWebEnabled(Boolean(web.enabled));
        setWebProvider(web.provider || 'searxng');
        setWebBaseUrl(web.baseUrl || 'http://192.168.2.38:8085');
        setWebHint(web.apiKeyHint || '');
        setWebShowKey(web.provider === 'searxng' ? false : !web.configured || Boolean(web.fromEnv));
        setAssistantTools({ ...DEFAULT_ASSISTANT_TOOLS, ...(assistant.tools || {}) });
        if (assistant.skillGroups?.length) setSkillGroups(assistant.skillGroups);
        if (assistant.toolMeta?.length) setToolMeta(assistant.toolMeta);
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
    const parseIntSafe = (s: string) => {
      const n = parse(s);
      return n != null ? Math.round(n) : undefined;
    };
    return {
      temperature: parse(llmTemp),
      topP: parse(llmTopP),
      maxTokens: parseIntSafe(llmMaxTokens),
      maxContext: parseIntSafe(llmMaxContext),
      frequencyPenalty: parse(llmFreqPenalty),
      presencePenalty: parse(llmPresPenalty),
      topK: parseIntSafe(llmTopK),
      minP: parse(llmMinP),
      repetitionPenalty: parse(llmRepPenalty),
      seed: parseIntSafe(llmSeed),
      n: parseIntSafe(llmN),
      streamOpenai: llmStream,
      maxContextUnlocked: llmCtxUnlocked,
      continuePrefill: llmContinuePrefill,
      squashSystemMessages: llmSquashSystem,
      showThoughts: llmShowThoughts,
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
      dim: Number.isFinite(dim) ? dim : 1024,
      device: embedDevice,
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
      if (r.devices?.length) setEmbedDevices(r.devices);
      if (r.device) setEmbedDevice(normalizeEmbedDevice(r.device));
      setEmbedConnectHint(r.message || '连接成功');
    } catch (e) {
      setEmbedModelList([]);
      setEmbedConnectHint(e instanceof Error ? e.message : '连接失败');
    } finally {
      setBusy(false);
    }
  }

  async function onDownloadEmbed() {
    if (embedProvider !== 'local') return;
    setBusy(true);
    setEmbedConnectHint('检查 / 下载模型中…');
    try {
      const r = await downloadAiEmbed({
        provider: 'local',
        model: embedModel.trim(),
        device: embedDevice,
        dim: Number.parseInt(embedDim, 10) || undefined,
      });
      setEmbedConnectHint(r.message || (r.skipped ? '已缓存，跳过' : '下载完成'));
    } catch (e) {
      setEmbedConnectHint(e instanceof Error ? e.message : '下载失败');
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

  function setToolEnabled(id: string, on: boolean) {
    setAssistantTools((prev) => {
      const next = { ...prev, [id]: on };
      if (id === 'web_search' && on && !webEnabled) setWebEnabled(true);
      return next;
    });
  }

  function setSkillEnabled(groupId: string, on: boolean) {
    const ids = toolMeta.filter((t) => t.group === groupId).map((t) => t.id);
    setAssistantTools((prev) => {
      const next = { ...prev };
      for (const id of ids) next[id] = on;
      return next;
    });
    if (groupId === 'web') {
      if (on && !webEnabled) setWebEnabled(true);
      if (!on) setWebEnabled(false);
    }
  }

  function skillOn(groupId: string): boolean {
    const ids = toolMeta.filter((t) => t.group === groupId).map((t) => t.id);
    if (!ids.length) return false;
    return ids.some((id) => assistantTools[id] !== false);
  }

  async function onSaveXiaohua() {
    setBusy(true);
    setMsg('');
    try {
      const webToolOn = assistantTools.web_search !== false;
      await putAiWebSearch({
        enabled: webEnabled && webToolOn,
        provider: webProvider,
        apiKey: webProvider === 'searxng' ? undefined : webApiKey.trim(),
        baseUrl: webBaseUrl.trim(),
      });
      await putAiAssistant({ tools: assistantTools });
      const web = await getAiWebSearch();
      setWebHint(web.apiKeyHint || '');
      setWebBaseUrl(web.baseUrl || webBaseUrl);
      setWebShowKey(web.provider === 'searxng' ? false : !web.configured || Boolean(web.fromEnv));
      setWebApiKey('');
      setMsg('小花设置已保存');
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
  const webProviders = presets?.webSearchProviders || [
    { value: 'searxng', label: 'SearXNG（自建免费）' },
    { value: 'serper', label: 'Serper (Google)' },
    { value: 'brave', label: 'Brave Search' },
  ];
  const isSearxng = webProvider === 'searxng';
  const enabledSkillLabels = skillGroups
    .filter((g) => skillOn(g.id))
    .map((g) => g.label);
  const deviceOptions =
    embedDevices.length > 0
      ? embedDevices
      : presets?.localEmbedDevices?.length
        ? presets.localEmbedDevices
        : EMBED_DEVICE_FALLBACK;

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
      ? `本地 · ${deviceLabel(embedDevice, deviceOptions)}`
      : embedUseMainLlm
        ? '沿用聊天'
        : embedHint
          ? '已配置'
          : '未配置';
  const embedStatusTone =
    !embedEnabled
      ? 'mute'
      : embedProvider === 'local' || embedHint || embedUseMainLlm
        ? 'ok'
        : 'warn';

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
      ) : tab === 'preset' ? (
        <ChatPresetsSection
          onSamplingApplied={() => {
            void (async () => {
              try {
                const llm = await getAiLlm();
                applyLlm(llm);
              } catch {
                /* ignore */
              }
            })();
          }}
        />
      ) : tab === 'embed' ? (
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
              七区目录。
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
      ) : (
        <>
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">角色</span>
                <span className="settings-kv__val">智能搜片助手</span>
              </div>
            </li>
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">可搜</span>
                <span className="settings-kv__val">
                  {enabledSkillLabels.length ? enabledSkillLabels.join(' · ') : '未启用'}
                </span>
              </div>
            </li>
          </ul>

          <p className="settings-group-label">技能与工具</p>
          {skillGroups.map((group) => {
            const toolsInGroup = toolMeta.filter((t) => t.group === group.id);
            const groupOn = skillOn(group.id);
            return (
              <div key={group.id} style={{ marginBottom: 12 }}>
                <ul className="settings-group">
                  <li>
                    <div className="settings-kv">
                      <span className="settings-kv__key">
                        {group.label}
                        <span
                          className="settings-kv__hint"
                          style={{ display: 'block', fontSize: 12, opacity: 0.65, fontWeight: 400 }}
                        >
                          {group.desc}
                        </span>
                      </span>
                      <Switch
                        checked={groupOn}
                        onCheckedChange={(on) => setSkillEnabled(group.id, on)}
                        disabled={busy}
                      />
                    </div>
                  </li>
                  {toolsInGroup.map((tool) => (
                    <li key={tool.id}>
                      <div className="settings-kv">
                        <span className="settings-kv__key">
                          {tool.label}
                          <span
                            style={{ display: 'block', fontSize: 12, opacity: 0.65, fontWeight: 400 }}
                          >
                            {tool.desc}
                          </span>
                        </span>
                        <Switch
                          checked={assistantTools[tool.id] !== false}
                          onCheckedChange={(on) => setToolEnabled(tool.id, on)}
                          disabled={busy}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}

          {skillOn('web') ? (
            <>
              <p className="settings-group-label">网络搜索</p>
              <FormCard>
                <SettingRow label="启用服务">
                  <Switch
                    checked={webEnabled}
                    onCheckedChange={(on) => {
                      setWebEnabled(on);
                      if (on) setToolEnabled('web_search', true);
                    }}
                    disabled={busy}
                  />
                </SettingRow>
                <SettingRow label="服务商">
                  <select
                    className="allow-select ai-input"
                    value={webProvider}
                    onChange={(e) => {
                      const v = e.target.value;
                      setWebProvider(v);
                      if (v === 'searxng') {
                        setWebShowKey(false);
                        if (!webBaseUrl.trim()) setWebBaseUrl('http://192.168.2.38:8085');
                      } else {
                        setWebShowKey(true);
                      }
                    }}
                    disabled={busy || !webEnabled}
                  >
                    {webProviders.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </SettingRow>
                {isSearxng ? (
                  <SettingRow label="服务地址">
                    <input
                      className="allow-select ai-input"
                      type="url"
                      placeholder="http://192.168.2.38:8085"
                      value={webBaseUrl}
                      onChange={(e) => setWebBaseUrl(e.target.value)}
                      disabled={busy || !webEnabled}
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                    />
                  </SettingRow>
                ) : webHint && !webShowKey ? (
                  <SettingRow label="API Key">
                    <div className="ai-key-saved">
                      <span className="allow-select">{webHint}</span>
                      <button
                        type="button"
                        className="settings-inline-action"
                        disabled={busy}
                        onClick={() => setWebShowKey(true)}
                      >
                        更换
                      </button>
                    </div>
                  </SettingRow>
                ) : (
                  <SettingRow label="API Key">
                    <input
                      className="allow-select ai-input"
                      type="password"
                      placeholder={webProvider === 'brave' ? 'Brave API Key' : 'Serper API Key'}
                      value={webApiKey}
                      onChange={(e) => setWebApiKey(e.target.value)}
                      disabled={busy || !webEnabled}
                      autoCapitalize="off"
                      autoCorrect="off"
                      spellCheck={false}
                    />
                  </SettingRow>
                )}
              </FormCard>
            </>
          ) : null}

          <AppFootnote>
            关掉某技能后，小花对话里不会再调用对应工具。网络可选 SearXNG（自建免 Key）或 Serper/Brave；本地库不依赖外网。
          </AppFootnote>

          <div className="app-actions">
            <button
              type="button"
              className="app-btn-primary"
              style={{ flex: 1 }}
              disabled={busy}
              onClick={() => void onSaveXiaohua()}
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
