'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Sparkles } from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import { ResourceDetailBody } from './ResourceDetailBody';
import { BitmagnetDetailBody } from '@/features/magnet/BitmagnetDetailBody';
import { ScrapDetailBody } from '@/features/makers/ScrapDetailBody';
import { MediaDetailBody } from '@/features/media/MediaDetailBody';
import {
  assistantChatStream,
  proxiedCoverUrl,
  scrapLibraryCoverUrl,
  type AssistantCard,
  type AssistantStep,
  type MediaItem,
  type ScrapLibraryEmbedItem,
} from '@/lib/api';
import { cn } from '@/lib/utils';

type ChatMsg = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  cards?: AssistantCard[];
  steps?: AssistantStep[];
  toolSummary?: string;
};

type DetailState =
  | { kind: 'sehua'; hash: string }
  | { kind: 'magnet'; hash: string }
  | { kind: 'scrap'; item: ScrapLibraryEmbedItem }
  | { kind: 'media'; item: MediaItem }
  | null;

const SOURCE_LABEL: Record<string, string> = {
  sehua: '色花',
  scrap: '片商',
  magnet: 'bitmagnet',
  media: '影视',
  web: '网络',
};

const SOURCE_MARK: Record<string, string> = {
  sehua: '色',
  scrap: '片',
  magnet: '磁',
  media: '影',
  web: '网',
};

const PREFER_CHIPS: { id: string; label: string; sources: string[] }[] = [
  { id: 'all', label: '全部', sources: [] },
  { id: 'media', label: '影视', sources: ['media'] },
  { id: 'scrap', label: '片商', sources: ['scrap'] },
  { id: 'sehua', label: '色花', sources: ['sehua'] },
  { id: 'magnet', label: 'bitmagnet', sources: ['magnet'] },
];

function coverForCard(card: AssistantCard): string {
  const raw = String(card.cover || '').trim();
  if (!raw) return '';
  if (card.source === 'scrap') {
    const item = card.open?.item as ScrapLibraryEmbedItem | undefined;
    if (item) return scrapLibraryCoverUrl(item, { prefer: 'poster', w: 160 });
  }
  if (raw.startsWith('http') || raw.startsWith('/')) {
    return proxiedCoverUrl(raw);
  }
  return proxiedCoverUrl(raw);
}

function hostFromUrl(url?: string): string {
  const raw = String(url || '').trim();
  if (!raw) return '';
  try {
    return new URL(raw).hostname.replace(/^www\./i, '');
  } catch {
    return '';
  }
}

/** 摘要字段用间隔点拆开，便于扫读 */
function formatCardMeta(raw?: string): string {
  let text = String(raw || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return '';
  const labels = [
    '导演',
    '主演',
    '演员',
    '类型',
    '制片国家/地区',
    '制片国家',
    '地区',
    '上映日期',
    '片长',
    '年份',
    '评分',
    '评语',
  ];
  for (const label of labels) {
    text = text.replace(
      new RegExp(`(?<![·\\s])\\s*(${label})\\s*[:：]`, 'g'),
      ' · $1：',
    );
  }
  return text
    .replace(/^(?:\s*·\s*)+/, '')
    .replace(/(?:\s*·\s*){2,}/g, ' · ')
    .trim();
}

function packLabel(cards: AssistantCard[]): string {
  const counts: Record<string, number> = {};
  for (const c of cards) {
    const s = String(c.source || '');
    counts[s] = (counts[s] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([s, n]) => `${SOURCE_LABEL[s] || s} ${n}`)
    .join(' · ');
}

function cardSecondary(hit: AssistantCard): string {
  const source = String(hit.source || '');
  if (source === 'web' || hit.open?.kind === 'url') {
    return hit.subtitle || hostFromUrl(hit.open?.url) || '';
  }
  return String(hit.subtitle || '').trim();
}

export function AiSearchChatPanel({ onBack }: { onBack: () => void }) {
  const [draft, setDraft] = useState('');
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState('正在搜');
  const [liveSteps, setLiveSteps] = useState<AssistantStep[]>([]);
  const [partialCards, setPartialCards] = useState<AssistantCard[]>([]);
  const [preferId, setPreferId] = useState('all');
  const [detail, setDetail] = useState<DetailState>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const liveStepsRef = useRef<AssistantStep[]>([]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.aiChat = '1';
    return () => {
      delete root.dataset.aiChat;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [msgs, busy, partialCards, statusText, liveSteps]);

  useEffect(() => {
    const input = inputRef.current;
    const list = listRef.current;
    if (!input || !list) return;
    const scrollEnd = () => {
      list.scrollTop = list.scrollHeight;
    };
    input.addEventListener('focus', scrollEnd);
    return () => input.removeEventListener('focus', scrollEnd);
  }, []);

  function openCard(card: AssistantCard) {
    const open = card.open || { kind: '' };
    if (open.kind === 'sehua' && open.hash) {
      setDetail({ kind: 'sehua', hash: open.hash });
      return;
    }
    if (open.kind === 'magnet' && open.hash) {
      setDetail({ kind: 'magnet', hash: open.hash });
      return;
    }
    if (open.kind === 'scrap' && open.item) {
      setDetail({ kind: 'scrap', item: open.item as ScrapLibraryEmbedItem });
      return;
    }
    if (open.kind === 'media' && open.item) {
      setDetail({ kind: 'media', item: open.item as MediaItem });
      return;
    }
    if (open.kind === 'url' && open.url) {
      window.open(open.url, '_blank', 'noopener,noreferrer');
    }
  }

  async function send(textRaw?: string) {
    const text = (textRaw ?? draft).trim();
    if (!text || busy) return;
    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: 'user', text };
    setDraft('');
    setMsgs((prev) => [...prev, userMsg].slice(-80));
    setBusy(true);
    setStatusText('小花在想…');
    liveStepsRef.current = [];
    setLiveSteps([]);
    setPartialCards([]);
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const prefer = PREFER_CHIPS.find((p) => p.id === preferId)?.sources || [];
    const history = [...msgs, userMsg].slice(-6).map((m) => ({
      role: m.role,
      content: m.text,
      summary: m.toolSummary,
    }));
    const appendMsg = (msg: ChatMsg) => {
      setMsgs((prev) => [...prev, msg].slice(-80));
    };

    try {
      const r = await assistantChatStream(
        { message: text, history, preferSources: prefer },
        {
          onStatus: (t) => setStatusText(t || '正在搜'),
          onStep: (step) => {
            liveStepsRef.current = [...liveStepsRef.current, step];
            setLiveSteps(liveStepsRef.current);
          },
          onCardsPartial: (cards) => setPartialCards(cards),
          onError: (message) => {
            appendMsg({ id: `e-${Date.now()}`, role: 'assistant', text: message });
          },
        },
        ac.signal,
      );
      const steps =
        r.steps && r.steps.length > 0 ? r.steps : liveStepsRef.current;
      const replyText =
        (r.reply || '').trim() ||
        (r.toolSummary
          ? `已检索完成（${r.toolSummary}），但正文未生成，请再试一次。`
          : '这次没有生成有效答复，请再试一次。');
      appendMsg({
        id: `a-${Date.now()}`,
        role: 'assistant',
        text: replyText,
        cards: r.cards || [],
        steps,
        toolSummary: r.toolSummary,
      });
    } catch (e) {
      if (ac.signal.aborted) return;
      if ((e as Error)?.name === 'AbortError') return;
      appendMsg({
        id: `e-${Date.now()}`,
        role: 'assistant',
        text: e instanceof Error ? e.message : '搜索失败',
      });
    } finally {
      setBusy(false);
      setPartialCards([]);
      setLiveSteps([]);
      liveStepsRef.current = [];
      setStatusText('正在搜');
      inputRef.current?.focus();
    }
  }

  return (
    <>
      <AppPush title="小花" onBack={onBack} bodyClassName="ai-chat-push">
        <div className="ai-chat">
          <div className="ai-chat__msgs" ref={listRef}>
            {msgs.length === 0 && !busy ? (
              <div className="ai-chat__empty">
                <span className="ai-chat__empty-icon" aria-hidden>
                  <Sparkles size={22} strokeWidth={1.8} />
                </span>
                <p className="ai-chat__empty-title">智能搜片助手</p>
                <p className="ai-chat__empty-sub">影视 · 片商 · 色花 · bitmagnet · 网络</p>
              </div>
            ) : null}

            {msgs.map((m) => (
              <div
                key={m.id}
                className={cn('ai-chat__row', m.role === 'user' && 'ai-chat__row--user')}
              >
                {m.role === 'assistant' && m.steps && m.steps.length > 0 ? (
                  <ThinkingTrace steps={m.steps} />
                ) : null}
                {m.text ? (
                  <div
                    className={cn(
                      'ai-chat__bubble',
                      m.role === 'user' && 'ai-chat__bubble--user',
                    )}
                  >
                    {m.role === 'user' ? (
                      <p>{m.text}</p>
                    ) : (
                      <AssistantText text={m.text} />
                    )}
                  </div>
                ) : null}
                {m.cards && m.cards.length > 0 ? (
                  <CardPack cards={m.cards} onOpen={openCard} />
                ) : null}
              </div>
            ))}

            {busy ? (
              <div className="ai-chat__row">
                {liveSteps.length > 0 ? (
                  <ThinkingTrace steps={liveSteps} live statusText={statusText} />
                ) : (
                  <div className="ai-chat__bubble ai-chat__bubble--pending">
                    <span className="ai-chat__dots" aria-hidden>
                      <i />
                      <i />
                      <i />
                    </span>
                    {statusText}
                  </div>
                )}
                {partialCards.length > 0 ? (
                  <CardPack cards={partialCards} onOpen={openCard} />
                ) : null}
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
            <div className="ai-chat__prefer" role="toolbar" aria-label="优先来源">
              {PREFER_CHIPS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={cn(
                    'ai-chat__prefer-chip',
                    preferId === p.id && 'ai-chat__prefer-chip--on',
                  )}
                  onClick={() => setPreferId(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
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
                <ArrowUp size={18} strokeWidth={2.6} />
              </button>
            </div>
          </form>
          <div className="ai-chat__kbd-spacer" aria-hidden />
        </div>
      </AppPush>

      {detail?.kind === 'sehua' ? (
        <AppPush title="详情" scrollMode="top" onBack={() => setDetail(null)}>
          <ResourceDetailBody hash={detail.hash} />
        </AppPush>
      ) : null}
      {detail?.kind === 'magnet' ? (
        <AppPush title="磁力" scrollMode="top" onBack={() => setDetail(null)}>
          <BitmagnetDetailBody hash={detail.hash} />
        </AppPush>
      ) : null}
      {detail?.kind === 'scrap' ? (
        <AppPush title="片商" scrollMode="top" onBack={() => setDetail(null)}>
          <ScrapDetailBody item={detail.item} />
        </AppPush>
      ) : null}
      {detail?.kind === 'media' ? (
        <AppPush title="影视" scrollMode="top" onBack={() => setDetail(null)}>
          <MediaDetailBody item={detail.item} />
        </AppPush>
      ) : null}
    </>
  );
}

function AssistantText({ text }: { text: string }) {
  const lines = String(text || '').split(/\n+/).map((l) => l.trim()).filter(Boolean);
  if (lines.length <= 1) {
    return <p className="allow-select">{text}</p>;
  }
  return (
    <div className="ai-chat__prose allow-select">
      {lines.map((line, i) => {
        const bullet = /^[·•\-–—]\s+/.test(line) || /^\d+[\.、]\s*/.test(line);
        const body = line.replace(/^[·•\-–—]\s+/, '').replace(/^\d+[\.、]\s*/, '');
        if (bullet) {
          return (
            <p key={i} className="ai-chat__prose-li">
              <span aria-hidden>·</span>
              <span>{body}</span>
            </p>
          );
        }
        return (
          <p key={i} className={i === 0 ? 'ai-chat__prose-lead' : undefined}>
            {line}
          </p>
        );
      })}
    </div>
  );
}

function ThinkingTrace({
  steps,
  live = false,
  statusText,
}: {
  steps: AssistantStep[];
  live?: boolean;
  statusText?: string;
}) {
  const [open, setOpen] = useState(live);
  useEffect(() => {
    if (live) setOpen(true);
  }, [live, steps.length]);

  if (!steps.length) return null;
  return (
    <div className={cn('ai-chat__think', live && 'ai-chat__think--live')}>
      <button
        type="button"
        className="ai-chat__think-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{live ? statusText || '思考中…' : '思考过程'}</span>
        <span className="ai-chat__think-count">{steps.length}</span>
        <span className={cn('ai-chat__think-chev', open && 'ai-chat__think-chev--open')} aria-hidden>
          ▾
        </span>
      </button>
      {open ? (
        <ol className="ai-chat__think-list">
          {steps.map((s, i) => {
            const label = s.label || TOOL_STEP_LABEL[String(s.tool || '')] || s.tool || '检索';
            const detail = [s.query ? `「${s.query}」` : '', s.summary || '']
              .filter(Boolean)
              .join(' · ');
            return (
              <li key={`${s.tool || 't'}-${i}`} className={s.ok === false ? 'is-bad' : undefined}>
                <span className="ai-chat__think-label">{label}</span>
                {detail ? <span className="ai-chat__think-detail">{detail}</span> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}

const TOOL_STEP_LABEL: Record<string, string> = {
  sehua_keyword: '仓库搜索',
  sehua_semantic: '仓库语义',
  scrap_search: '片商搜索',
  scrap_list: '片商筛选',
  magnet_search: '磁力搜索',
  magnet_semantic: '磁力语义',
  media_search: '影视搜索',
  media_person_works: '影人作品',
  web_search: '网络搜索',
};

function CardPack({
  cards,
  onOpen,
}: {
  cards: AssistantCard[];
  onOpen: (card: AssistantCard) => void;
}) {
  return (
    <div className="ai-chat__pack">
      <p className="ai-chat__pack-label">{packLabel(cards)}</p>
      <ul className="ai-chat__hits">
        {cards.map((hit) => {
          const source = String(hit.source || 'web');
          const cover = coverForCard(hit);
          const secondary = cardSecondary(hit);
          const meta = formatCardMeta(hit.meta);
          const scoreText =
            hit.score != null && Number.isFinite(Number(hit.score))
              ? Number(hit.score).toFixed(2)
              : '';
          const mark = SOURCE_MARK[source] || (secondary || '·').slice(0, 1);
          return (
            <li key={hit.id}>
              <button
                type="button"
                className={cn('ai-chat__hit', `ai-chat__hit--${source}`)}
                data-source={source}
                onClick={() => onOpen(hit)}
              >
                {cover ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="ai-chat__hit-cover" src={cover} alt="" />
                ) : (
                  <span
                    className={cn(
                      'ai-chat__hit-mark',
                      `ai-chat__hit-mark--${source}`,
                    )}
                    aria-hidden
                  >
                    {mark}
                  </span>
                )}
                <span className="ai-chat__hit-main">
                  <span className="ai-chat__hit-source-row">
                    <span
                      className={cn(
                        'ai-chat__hit-source',
                        `ai-chat__hit-source--${source}`,
                      )}
                    >
                      {SOURCE_LABEL[source] || source}
                    </span>
                    {secondary ? (
                      <span className="ai-chat__hit-secondary">{secondary}</span>
                    ) : null}
                    {scoreText ? (
                      <span className="ai-chat__hit-score">{scoreText}</span>
                    ) : null}
                  </span>
                  <span className="ai-chat__hit-title">{hit.title}</span>
                  {meta ? <span className="ai-chat__hit-meta">{meta}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
