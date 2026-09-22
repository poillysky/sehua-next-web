'use client';

import type {
  AiAssistantSkillGroup,
  AiAssistantToolMeta,
  AiEmbedConfig,
  AiEmbedDevice,
  AiEmbedDeviceOption,
  AiLlmConfig,
  AiPresetOption,
  AiPresets,
} from '@/lib/api';

export const LLM_BASE_DEFAULT = 'https://api.openai.com/v1';
export const LLM_MODEL_DEFAULT = 'gpt-4o-mini';
export const EMBED_MODEL_DEFAULT = 'intfloat/multilingual-e5-large';
export const EMBED_DEVICE_DEFAULT: AiEmbedDevice = 'directml';

export const EMBED_DEVICE_FALLBACK: AiEmbedDeviceOption[] = [
  { value: 'cpu', label: 'CPU', hint: '兼容最好，速度慢' },
  { value: 'cuda', label: 'N卡 (CUDA)', hint: '需 NVIDIA 驱动 + onnxruntime-gpu' },
  { value: 'directml', label: 'A卡 (DirectML)', hint: 'Windows AMD/Intel；需 onnxruntime-directml' },
];

export function normalizeEmbedDevice(raw: string | undefined | null): AiEmbedDevice {
  const v = String(raw || '').trim().toLowerCase();
  if (v === 'cuda' || v === 'nvidia' || v === 'n') return 'cuda';
  if (v === 'directml' || v === 'amd' || v === 'a' || v === 'dml') return 'directml';
  if (v === 'cpu') return 'cpu';
  return EMBED_DEVICE_DEFAULT;
}

export function deviceLabel(device: AiEmbedDevice, list: AiEmbedDeviceOption[]): string {
  return list.find((d) => d.value === device)?.label || device;
}
export type AiTab = 'llm' | 'preset' | 'embed' | 'xiaohua';

export const TABS: { key: AiTab; label: string }[] = [
  { key: 'llm', label: '聊天' },
  { key: 'preset', label: '聊天预设' },
  { key: 'embed', label: '向量' },
  { key: 'xiaohua', label: '小花' },
];

export const DEFAULT_ASSISTANT_TOOLS: Record<string, boolean> = {
  sehua_keyword: true,
  sehua_semantic: true,
  scrap_search: true,
  scrap_list: true,
  magnet_search: true,
  magnet_semantic: true,
  media_search: true,
  web_search: true,
};

export const DEFAULT_SKILL_GROUPS: AiAssistantSkillGroup[] = [
  { id: 'warehouse', label: '仓库', desc: '色花资源库' },
  { id: 'makers', label: '片商', desc: '刮削番号库' },
  { id: 'magnet', label: '磁力', desc: 'Bitmagnet' },
  { id: 'media', label: '影视', desc: 'TMDB 等元数据' },
  { id: 'web', label: '网络', desc: '公开网页搜索' },
];

export const DEFAULT_TOOL_META: AiAssistantToolMeta[] = [
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
export const PRESET_DEFAULTS = {
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

export function hubStatus(llm: AiLlmConfig | null, embed: AiEmbedConfig | null): string {
  const llmOk = Boolean(llm?.enabled && llm?.configured);
  const embOk = Boolean(embed?.enabled && embed?.configured);
  if (llmOk && embOk) return '已就绪';
  if (llmOk) return '聊天已配';
  if (embOk) return '向量已配';
  return '未配置';
}

export function numStr(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '';
  return String(v);
}

export function presetDim(model: string, presets: AiPresets | null): string {
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


export function renderSourceOptions(list: AiPresetOption[], start: number, end?: number) {
  return list.slice(start, end).map((o) => (
    <option key={o.value} value={o.value}>
      {o.label}
    </option>
  ));
}
