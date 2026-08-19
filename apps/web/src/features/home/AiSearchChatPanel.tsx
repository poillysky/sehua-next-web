'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, ChevronRight, Sparkles } from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import { ResourceDetailBody } from './ResourceDetailBody';
import { aiChatSearch, proxiedCoverUrl } from '@/lib/api';
import { formatByteSize } from '@/lib/format';
import { parseMakerCode } from '@/lib/makerCode';
import {
  getDescriptionField,
  normalizeResourceView,
} from '@/lib/resourceView';
import type { ResourceItem } from '@/types/resource';
import { cn } from '@/lib/utils';

type ChatHit = {
  hash: string;
  code: string;
  title: string;
  board: string;
  size: string;
  cover: string;
  score?: number;
};

type ChatMsg = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  keyword?: string;
  searchMode?: 'semantic' | 'keyword';
  hits?: ChatHit[];
  total?: number;
};

function stripForumChrome(s: string): string {
  return s
    .replace(/\s*[-–|]\s*Powered by Discuz!.*$/i, '')
    .replace(/\s*[-–|]\s*98堂\s*[\[【]?原?色花堂[\]】]?.*/i, '')
    .replace(/\[原色花堂\]/g, '')
    .replace(
      /\s*[-–|]\s*(亚洲有码原创|亚洲无码原创|欧美无码|国产原创|有码中字).*$/i,
      '',
    )
    .trim();
}

function firstCode(...parts: string[]): string {
  for (const p of parts) {
    const stem = p.replace(/\.(mp4|mkv|avi|wmv|iso|ts|m2ts)$/i, '');
    const whole = parseMakerCode(stem);
    if (whole?.canonical) return whole.canonical;
    const re =
      /(?:^|[^A-Za-z0-9])((?:\d{2,3})?[A-Za-z]{2,15}[-_\s]?\d{2,8}|FC2[-_\s]?PPV[-_\s]?\d{5,10})/gi;
    let m: RegExpExecArray | null;
    while ((m = re.exec(stem))) {
      const parsed = parseMakerCode(m[1]);
      if (parsed?.canonical) return parsed.canonical;
    }
  }
  return '';
}

function displayHitTitle(raw: ResourceItem, view: ReturnType<typeof normalizeResourceView>): {
  code: string;
  title: string;
} {
  const film = getDescriptionField(raw.description, '影片名称') || '';
  const resource = getDescriptionField(raw.description, '资源名称') || '';
  const code = firstCode(view.name || '', film, resource, view.title || '');
  let title = stripForumChrome(film || resource || view.title || view.name || '');
  if (code && title) {
    const folded = title.replace(/[\s_\-]/g, '').toUpperCase();
    if (folded.startsWith(code.replace(/-/g, ''))) {
      title = title.replace(new RegExp(`^${code}[\\s_\\-]*`, 'i'), '').trim() || title;
    }
  }
  if (!title) title = view.hash;
  return { code, title };
}

function toHits(items: ResourceItem[]): ChatHit[] {
  return items.map((raw) => {
    const view = normalizeResourceView(raw);
    const cover = (view.preview_images || [])[0] || '';
    const extra = raw as ResourceItem & { score?: number };
    const score = typeof extra.score === 'number' ? extra.score : undefined;
    const { code, title } = displayHitTitle(raw, view);
    return {
      hash: view.hash,
      code,
      title,
      board: view.board_name || '',
      size: formatByteSize(view.size),
      cover: cover ? proxiedCoverUrl(cover) : '',
      score,
    };
  });
}

export function AiSearchChatPanel({ onBack }: { onBack: () => void }) {
  const [draft, setDraft] = useState('');
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [detailHash, setDetailHash] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [msgs, busy]);

  useEffect(() => {
    const input = inputRef.current;
    const list = listRef.current;
    if (!input || !list) return;

    const scrollEnd = () => {
      list.scrollTop = list.scrollHeight;
    };

    input.addEventListener('focus', scrollEnd);
    return () => {
      input.removeEventListener('focus', scrollEnd);
    };
  }, []);

  async function send(textRaw?: string) {
    const text = (textRaw ?? draft).trim();
    if (!text || busy) return;
    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: 'user', text };
    setDraft('');
    setMsgs((prev) => [...prev, userMsg]);
    setBusy(true);
    try {
      const history = [...msgs, userMsg]
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.text }));
      const r = await aiChatSearch({ message: text, history });
      setMsgs((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          text: r.reply || '搜完了',
          keyword: r.keyword,
          searchMode: r.searchMode,
          hits: toHits(r.resources || []),
          total: r.total_count,
        },
      ]);
    } catch (e) {
      setMsgs((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: 'assistant',
          text: e instanceof Error ? e.message : '搜索失败',
        },
      ]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  return (
    <>
      <AppPush title="对话搜" onBack={onBack} bodyClassName="ai-chat-push">
        <div className="ai-chat">
          <div className="ai-chat__msgs" ref={listRef}>
            {msgs.length === 0 && !busy ? (
              <div className="ai-chat__empty">
                <span className="ai-chat__empty-icon" aria-hidden>
                  <Sparkles size={22} strokeWidth={1.8} />
                </span>
                <p className="ai-chat__empty-title">用说话的方式找片</p>
                <p className="ai-chat__empty-sub">番号、女优、类型都可以</p>
              </div>
            ) : null}
            {msgs.map((m) => (
              <div
                key={m.id}
                className={cn('ai-chat__row', m.role === 'user' && 'ai-chat__row--user')}
              >
                {m.text ? (
                  <div
                    className={cn(
                      'ai-chat__bubble',
                      m.role === 'user' && 'ai-chat__bubble--user',
                    )}
                  >
                    <p className={cn(m.role === 'user' ? '' : 'allow-select')}>{m.text}</p>
                  </div>
                ) : null}
                {m.hits && m.hits.length > 0 ? (
                  <div className="ai-chat__pack">
                    <p className="ai-chat__pack-label">
                      {m.searchMode === 'semantic' ? '相近结果' : '搜索结果'}
                      {m.total ? ` · ${m.total}` : ''}
                    </p>
                    <ul className="ai-chat__hits">
                      {m.hits.map((hit) => (
                        <li key={hit.hash}>
                          <button
                            type="button"
                            className="ai-chat__hit"
                            onClick={() => setDetailHash(hit.hash)}
                          >
                            {hit.cover ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img className="ai-chat__hit-cover" src={hit.cover} alt="" />
                            ) : (
                              <span className="ai-chat__hit-cover ai-chat__hit-cover--empty" />
                            )}
                            <span className="ai-chat__hit-main">
                              {hit.code ? (
                                <span className="ai-chat__hit-code">{hit.code}</span>
                              ) : null}
                              <span className="ai-chat__hit-title">{hit.title}</span>
                              <span className="ai-chat__hit-meta">
                                {[hit.board, hit.size].filter(Boolean).join(' · ')}
                              </span>
                            </span>
                            {hit.score != null ? (
                              <span className="ai-chat__hit-score">
                                {hit.score.toFixed(2)}
                              </span>
                            ) : null}
                            <ChevronRight
                              className="ai-chat__hit-chevron"
                              size={18}
                              strokeWidth={2}
                              aria-hidden
                            />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ))}
            {busy ? (
              <div className="ai-chat__row">
                <div className="ai-chat__bubble ai-chat__bubble--pending">
                  <span className="ai-chat__dots" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                  正在搜
                </div>
              </div>
            ) : null}
          </div>
          <form
            className="ai-chat__composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <div className="ai-chat__field">
              <input
                ref={inputRef}
                className="allow-select ai-chat__input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="想找什么"
                disabled={busy}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                enterKeyHint="send"
              />
              <button
                type="submit"
                className="ai-chat__send"
                disabled={busy || !draft.trim()}
                aria-label="发送"
              >
                <ArrowUp size={16} strokeWidth={2.6} />
              </button>
            </div>
          </form>
        </div>
      </AppPush>
      {detailHash ? (
        <AppPush title="详情" onBack={() => setDetailHash(null)}>
          <ResourceDetailBody hash={detailHash} />
        </AppPush>
      ) : null}
    </>
  );
}
