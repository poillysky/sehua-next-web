/**
 * AI 大模型与向量服务设置
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import type {
  AuthUser,
  BrowseResult,
  FilterSize,
  FilterTime,
  MatchMode,
  ResourceDbConfig,
  ResourceItem,
  SearchResult,
  SortType,
} from '@/types/resource';

export type AiSamplingConfig = {
  temperature?: number | null;
  topP?: number | null;
  maxTokens?: number | null;
  maxContext?: number | null;
  frequencyPenalty?: number | null;
  presencePenalty?: number | null;
  topK?: number | null;
  minP?: number | null;
  repetitionPenalty?: number | null;
  seed?: number | null;
  n?: number | null;
  streamOpenai?: boolean | null;
  maxContextUnlocked?: boolean | null;
  continuePrefill?: boolean | null;
  squashSystemMessages?: boolean | null;
  showThoughts?: boolean | null;
};

export type AiLlmConfig = {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
  configured?: boolean;
  fromEnv?: boolean;
  fromEnvKey?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiEmbedDevice = 'cpu' | 'cuda' | 'directml';

export type AiEmbedDeviceOption = {
  value: AiEmbedDevice | string;
  label: string;
  hint?: string;
  available?: boolean;
};

export type AiEmbedConfig = {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  devices?: AiEmbedDeviceOption[];
  topK?: number;
  minScore?: number;
  chunkSize?: number;
  configured?: boolean;
  fromEnv?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiPresetOption = { value: string; label: string; baseUrl?: string; dim?: string };

export type AiPresets = {
  chatSources: AiPresetOption[];
  localEmbedModels: AiPresetOption[];
  localEmbedDevices?: AiEmbedDeviceOption[];
  openaiEmbedModels: AiPresetOption[];
  promptPostProcessing: AiPresetOption[];
  webSearchProviders?: AiPresetOption[];
};

export async function getAiPresets(): Promise<AiPresets> {
  const res = await apiFetch('/settings/ai/presets');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiPresets>).data;
}

export async function getAiLlm(): Promise<AiLlmConfig> {
  const res = await apiFetch('/settings/ai/llm');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiLlmConfig>).data;
}

export async function putAiLlm(body: {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
}): Promise<AiLlmConfig> {
  const res = await apiFetch('/settings/ai/llm', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiLlmConfig>).data;
}

export async function connectAiLlm(body: {
  baseUrl?: string;
  apiKey?: string;
  customIncludeHeaders?: string;
  listModels?: boolean;
}): Promise<{ ok: boolean; models: string[]; modelCount: number; message: string }> {
  const res = await apiFetch('/settings/ai/llm/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok: boolean;
    models?: string[];
    modelCount?: number;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    models: json.data?.models || [],
    modelCount: json.data?.modelCount ?? 0,
    message: json.message || '',
  };
}

export async function testAiLlm(body: {
  enabled?: boolean;
  chatCompletionSource?: string;
  apiMode?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  promptPostProcessing?: string;
  customIncludeHeaders?: string;
  customIncludeBody?: string;
  customExcludeBody?: string;
  proxyUrl?: string;
  timeoutSec?: number;
  sampling?: AiSamplingConfig;
}): Promise<{ ok: boolean; message: string }> {
  const res = await apiFetch('/settings/ai/llm/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean }> & { message: string };
  return { ok: Boolean(json.data?.ok), message: json.message || '' };
}

export async function getAiEmbed(): Promise<AiEmbedConfig> {
  const res = await apiFetch('/settings/ai/embed');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiEmbedConfig>).data;
}

export async function putAiEmbed(body: {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  topK?: number;
  minScore?: number;
  chunkSize?: number;
}): Promise<AiEmbedConfig> {
  const res = await apiFetch('/settings/ai/embed', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiEmbedConfig>).data;
}

export async function connectAiEmbed(body: {
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  apiKey?: string;
  listModels?: boolean;
}): Promise<{
  ok: boolean;
  models: string[];
  modelCount: number;
  totalModelCount?: number;
  embedMatchCount?: number;
  devices?: AiEmbedDeviceOption[];
  device?: string;
  message: string;
}> {
  const res = await apiFetch('/settings/ai/embed/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok: boolean;
    models?: string[];
    modelCount?: number;
    totalModelCount?: number;
    embedMatchCount?: number;
    devices?: AiEmbedDeviceOption[];
    device?: string;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    models: json.data?.models || [],
    modelCount: json.data?.modelCount ?? 0,
    totalModelCount: json.data?.totalModelCount,
    embedMatchCount: json.data?.embedMatchCount,
    devices: json.data?.devices,
    device: json.data?.device,
    message: json.message || '',
  };
}

export async function testAiEmbed(body: {
  enabled?: boolean;
  provider?: 'local' | 'openai';
  useMainLlm?: boolean;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  dim?: number;
  device?: AiEmbedDevice | string;
  topK?: number;
  minScore?: number;
  chunkSize?: number;
}): Promise<{ ok: boolean; message: string; dim?: number }> {
  const res = await apiFetch('/settings/ai/embed/test', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{ ok: boolean; dim?: number }> & { message: string };
  return {
    ok: Boolean(json.data?.ok),
    message: json.message || '',
    dim: typeof json.data?.dim === 'number' ? json.data.dim : undefined,
  };
}

export async function downloadAiEmbed(body: {
  provider?: 'local' | 'openai';
  model?: string;
  device?: AiEmbedDevice | string;
  dim?: number;
}): Promise<{
  ok: boolean;
  skipped?: boolean;
  downloaded?: boolean;
  model?: string;
  message: string;
}> {
  const res = await apiFetch('/settings/ai/embed/download', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = (await res.json()) as Envelope<{
    ok?: boolean;
    skipped?: boolean;
    downloaded?: boolean;
    model?: string;
    message?: string;
  }> & { message: string };
  return {
    ok: Boolean(json.data?.ok ?? true),
    skipped: json.data?.skipped,
    downloaded: json.data?.downloaded,
    model: json.data?.model,
    message: json.message || json.data?.message || '',
  };
}

