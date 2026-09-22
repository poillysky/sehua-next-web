'use client';

import { useEffect, useState } from 'react';
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
  type AiPresets,
} from '@/lib/api';
import {
  testResultText,
  usePanelAction,
  type StatusReporter,
} from '@/hooks/usePanelAction';
import {
  DEFAULT_ASSISTANT_TOOLS,
  DEFAULT_SKILL_GROUPS,
  DEFAULT_TOOL_META,
  EMBED_DEVICE_DEFAULT,
  EMBED_DEVICE_FALLBACK,
  EMBED_MODEL_DEFAULT,
  LLM_BASE_DEFAULT,
  LLM_MODEL_DEFAULT,
  PRESET_DEFAULTS,
  deviceLabel,
  hubStatus,
  normalizeEmbedDevice,
  numStr,
  presetDim,
  type AiTab,
} from './helpers';

export type AiModelsPanelState = ReturnType<typeof useAiModelsPanel>;
export { hubStatus as aiModelsHubStatus } from './helpers';

export function useAiModelsPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
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

  // onConnect*/onDownload* 的 catch 落到各自的 hint 变量而非 msg，故保留 setBusy 手动管理
  const { msg, setMsg, busy, setBusy, run } = usePanelAction();

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
    await run('测试失败', async () => {
      const r = await testAiLlm(llmBody());
      setMsg(testResultText(r, '聊天模型正常', '失败'));
    });
  }

  async function onSaveLlm() {
    await run('保存失败', async () => {
      const next = await putAiLlm(llmBody());
      applyLlm(next);
      setLlmApiKey('');
      const embed = await getAiEmbed();
      publish(next, embed);
      setMsg('聊天模型已保存');
    });
  }

  async function onTestEmbed() {
    await run('测试失败', async () => {
      const r = await testAiEmbed(embedBody());
      const dim = r.dim;
      if (typeof dim === 'number' && dim > 0 && String(dim) !== embedDim) {
        setEmbedDim(String(dim));
        setMsg(`${r.message || '测试成功'} · 维度已改为 ${dim}`);
      } else {
        setMsg(testResultText(r, '向量模型正常', '失败'));
      }
    });
  }

  async function onSaveEmbed() {
    await run('保存失败', async () => {
      const next = await putAiEmbed(embedBody());
      applyEmbed(next);
      setEmbedApiKey('');
      const llm = await getAiLlm();
      publish(llm, next);
      setMsg('向量模型已保存');
    });
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
    await run('保存失败', async () => {
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
    });
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

  return {
    onBack,
    onStatus,
    tab,
    switchTab,
    presets,
    llmEnabled,
    setLlmEnabled,
    llmSource,
    llmBaseUrl,
    setLlmBaseUrl,
    llmModel,
    setLlmModel,
    llmApiKey,
    setLlmApiKey,
    llmHint,
    llmFromEnv,
    llmShowKey,
    setLlmShowKey,
    llmPostProcess,
    setLlmPostProcess,
    llmHeaders,
    setLlmHeaders,
    llmTimeout,
    setLlmTimeout,
    llmAdvanced,
    setLlmAdvanced,
    modelList,
    connectHint,
    embedModelList,
    embedConnectHint,
    embedEnabled,
    setEmbedEnabled,
    embedProvider,
    setEmbedProvider,
    embedDevice,
    setEmbedDevice,
    embedDevices,
    embedUseMainLlm,
    setEmbedUseMainLlm,
    embedBaseUrl,
    setEmbedBaseUrl,
    embedModel,
    embedDim,
    setEmbedDim,
    embedTopK,
    setEmbedTopK,
    embedMinScore,
    setEmbedMinScore,
    embedChunkSize,
    setEmbedChunkSize,
    embedApiKey,
    setEmbedApiKey,
    embedHint,
    embedFromEnv,
    embedShowKey,
    setEmbedShowKey,
    webEnabled,
    setWebEnabled,
    webProvider,
    setWebProvider,
    webBaseUrl,
    setWebBaseUrl,
    webApiKey,
    setWebApiKey,
    webHint,
    webShowKey,
    setWebShowKey,
    assistantTools,
    skillGroups,
    toolMeta,
    msg,
    setMsg,
    busy,
    applyLlm,
    onLlmSourceChange,
    onEmbedModelChange,
    onConnectLlm,
    onConnectEmbed,
    onDownloadEmbed,
    onTestLlm,
    onSaveLlm,
    onTestEmbed,
    onSaveEmbed,
    setToolEnabled,
    setSkillEnabled,
    skillOn,
    onSaveXiaohua,
    chatSources,
    localModels,
    openaiModels,
    postOptions,
    webProviders,
    isSearxng,
    enabledSkillLabels,
    deviceOptions,
    llmConfigured,
    llmStatusText,
    llmStatusTone,
    embedStatusText,
    embedStatusTone,
  };
}
