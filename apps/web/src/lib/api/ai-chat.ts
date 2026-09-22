/**
 * AI 对话 / 助手 / 联网
 *
 * 由 lib/api.ts 拆分而来；对外统一从 `@/lib/api` 导入，请不要直接引用本文件。
 */
import { API_BASE, apiFetch, parseError } from './client';
import type { Envelope } from './client';
import type { AiSamplingConfig } from './ai';
import type { MediaItem } from './media';
import type { ScrapLibraryEmbedItem } from './scrap-library';
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

export type AiChatSearchResult = {
  reply: string;
  keyword: string;
  usedLlm?: boolean;
  searchMode?: 'semantic' | 'keyword';
  resources: ResourceItem[];
  total_count: number;
};

export async function aiChatSearch(opts: {
  message: string;
  history?: Array<{ role: 'user' | 'assistant'; content: string }>;
}): Promise<AiChatSearchResult> {
  const res = await apiFetch('/ai/chat-search', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiChatSearchResult>).data;
}

export type AssistantSource = 'sehua' | 'magnet' | 'scrap' | 'media' | 'web';

export type AssistantCard = {
  id: string;
  source: AssistantSource | string;
  title: string;
  subtitle?: string;
  meta?: string;
  cover?: string;
  score?: number;
  open: {
    kind: 'sehua' | 'magnet' | 'scrap' | 'media' | 'url' | string;
    hash?: string;
    url?: string;
    title?: string;
    item?: ScrapLibraryEmbedItem | MediaItem | Record<string, unknown>;
  };
};

export type AssistantStep = {
  tool?: string;
  label?: string;
  query?: string;
  status?: string;
  ok?: boolean;
  summary?: string;
};

export type AssistantChatResult = {
  reply: string;
  cards: AssistantCard[];
  steps?: AssistantStep[];
  usedLlm?: boolean;
  usedTools?: string[];
  toolSummary?: string;
};

export type AssistantMeta = {
  suggestChips: string[];
  webSearchEnabled?: boolean;
  sources?: string[];
};

export type AiWebSearchConfig = {
  enabled?: boolean;
  provider?: 'serper' | 'brave' | 'searxng' | string;
  baseUrl?: string;
  configured?: boolean;
  fromEnv?: boolean;
  apiKeyHint?: string;
  updated_at?: string;
};

export type AiAssistantToolMeta = {
  id: string;
  group: string;
  label: string;
  desc: string;
};

export type AiAssistantSkillGroup = {
  id: string;
  label: string;
  desc: string;
};

export type AiAssistantConfig = {
  systemPrompt?: string;
  suggestChips?: string[];
  tools?: Record<string, boolean>;
  toolMeta?: AiAssistantToolMeta[];
  skillGroups?: AiAssistantSkillGroup[];
  updated_at?: string;
};

export async function getAssistantMeta(): Promise<AssistantMeta> {
  const res = await apiFetch('/ai/assistant/meta');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AssistantMeta>).data;
}

export async function assistantChat(opts: {
  message: string;
  history?: Array<{ role: 'user' | 'assistant'; content: string; summary?: string }>;
  preferSources?: string[];
}): Promise<AssistantChatResult> {
  const res = await apiFetch('/ai/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
      preferSources: opts.preferSources || [],
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AssistantChatResult>).data;
}

export async function assistantChatStream(
  opts: {
    message: string;
    history?: Array<{ role: 'user' | 'assistant'; content: string; summary?: string }>;
    preferSources?: string[];
  },
  handlers: {
    onStatus?: (text: string, tool?: string) => void;
    onStep?: (step: AssistantStep) => void;
    onCardsPartial?: (cards: AssistantCard[]) => void;
    onDone?: (data: AssistantChatResult) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<AssistantChatResult> {
  const abortError = () => {
    const err = new DOMException('Aborted', 'AbortError');
    throw err;
  };
  if (signal?.aborted) abortError();

  const res = await apiFetch('/ai/assistant/chat/stream', {
    method: 'POST',
    body: JSON.stringify({
      message: opts.message,
      history: opts.history || [],
      preferSources: opts.preferSources || [],
    }),
    signal,
  });
  if (signal?.aborted) abortError();
  if (!res.ok) throw new Error(await parseError(res));
  if (!res.body) throw new Error('无流式响应');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: AssistantChatResult | null = null;

  const onAbort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      if (signal?.aborted) abortError();
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';
      for (const chunk of chunks) {
        const line = chunk
          .split('\n')
          .map((l) => l.trim())
          .find((l) => l.startsWith('data:'));
        if (!line) continue;
        const raw = line.replace(/^data:\s*/, '');
        try {
          const evt = JSON.parse(raw) as {
            event?: string;
            data?: Record<string, unknown>;
          };
          const data = (evt.data || {}) as Record<string, unknown>;
          if (evt.event === 'status') {
            handlers.onStatus?.(String(data.text || ''), data.tool ? String(data.tool) : undefined);
          } else if (evt.event === 'step') {
            handlers.onStep?.(data as AssistantStep);
          } else if (evt.event === 'cards_partial') {
            handlers.onCardsPartial?.((data.cards as AssistantCard[]) || []);
          } else if (evt.event === 'error') {
            handlers.onError?.(String(data.message || '失败'));
          } else if (evt.event === 'done') {
            finalResult = data as unknown as AssistantChatResult;
            handlers.onDone?.(finalResult);
          }
        } catch {
          /* ignore bad chunk */
        }
      }
    }
  } catch (e) {
    if (signal?.aborted) abortError();
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    if (e instanceof Error && e.name === 'AbortError') throw e;
    throw e;
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }

  if (signal?.aborted) abortError();
  if (!finalResult) throw new Error('流式结束但无结果');
  return finalResult;
}

export async function getAiWebSearch(): Promise<AiWebSearchConfig> {
  const res = await apiFetch('/settings/ai/web-search');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiWebSearchConfig>).data;
}

export async function putAiWebSearch(body: {
  enabled?: boolean;
  provider?: string;
  apiKey?: string;
  baseUrl?: string;
}): Promise<AiWebSearchConfig> {
  const res = await apiFetch('/settings/ai/web-search', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiWebSearchConfig>).data;
}

export async function getAiAssistant(): Promise<AiAssistantConfig> {
  const res = await apiFetch('/settings/ai/assistant');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiAssistantConfig>).data;
}

export async function putAiAssistant(body: {
  suggestChips?: string[];
  systemPrompt?: string;
  tools?: Record<string, boolean>;
}): Promise<AiAssistantConfig> {
  const res = await apiFetch('/settings/ai/assistant', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<AiAssistantConfig>).data;
}

export type ChatPresetListItem = {
  id: string;
  name: string;
  updatedAt?: string;
  promptCount?: number;
  kind?: string;
};

export type ChatPresetPrompt = {
  identifier: string;
  name: string;
  role: string;
  enabled: boolean;
  marker?: boolean;
  content?: string;
  injection_position?: number | null;
  injection_depth?: number | null;
  injection_order?: number | null;
  forbid_overrides?: boolean;
};

export type ChatPresetDetail = {
  id: string;
  name: string;
  updatedAt?: string;
  sampling: AiSamplingConfig;
  prompts: ChatPresetPrompt[];
  regexScripts?: Array<{
    id: string;
    scriptName: string;
    disabled?: boolean;
    findRegex?: string;
  }>;
  active?: boolean;
};

export async function listChatPresets(): Promise<{
  presets: ChatPresetListItem[];
  activeId: string | null;
}> {
  const res = await apiFetch('/settings/ai/chat-presets');
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function getChatPreset(id: string): Promise<ChatPresetDetail> {
  const res = await apiFetch(`/settings/ai/chat-presets/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetDetail>).data;
}

export async function importChatPreset(file: File): Promise<ChatPresetListItem> {
  const text = await file.text();
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error('JSON 解析失败');
  }
  const res = await apiFetch('/settings/ai/chat-presets/import', {
    method: 'POST',
    body: JSON.stringify({ name: file.name, data }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetListItem>).data;
}

export async function activateChatPreset(
  id: string | null,
): Promise<{ presets: ChatPresetListItem[]; activeId: string | null }> {
  const res = await apiFetch('/settings/ai/chat-presets/activate', {
    method: 'POST',
    body: JSON.stringify({ id }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function deleteChatPreset(
  id: string,
): Promise<{ presets: ChatPresetListItem[]; activeId: string | null }> {
  const res = await apiFetch(`/settings/ai/chat-presets/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<{
    presets: ChatPresetListItem[];
    activeId: string | null;
  }>).data;
}

export async function saveChatPresetParams(
  id: string,
  sampling: AiSamplingConfig,
): Promise<ChatPresetDetail> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/params`,
    {
      method: 'PUT',
      body: JSON.stringify(sampling),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return ((await res.json()) as Envelope<ChatPresetDetail>).data;
}

export async function enableChatPresetPrompt(
  id: string,
  identifier: string,
  enabled: boolean,
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts/enable`,
    {
      method: 'POST',
      body: JSON.stringify({ identifier, enabled }),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export async function saveChatPresetPrompt(
  id: string,
  body: {
    identifier: string;
    name?: string;
    role?: string;
    content?: string;
    enabled?: boolean;
  },
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts`,
    {
      method: 'PUT',
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export async function addChatPresetPrompt(
  id: string,
  body?: { name?: string; role?: string; content?: string },
): Promise<ChatPresetPrompt[]> {
  const res = await apiFetch(
    `/settings/ai/chat-presets/${encodeURIComponent(id)}/prompts`,
    {
      method: 'POST',
      body: JSON.stringify(body || {}),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (
    ((await res.json()) as Envelope<{ prompts: ChatPresetPrompt[] }>).data.prompts || []
  );
}

export function chatPresetExportUrl(id: string): string {
  return `${API_BASE}/settings/ai/chat-presets/${encodeURIComponent(id)}/export`;
}

