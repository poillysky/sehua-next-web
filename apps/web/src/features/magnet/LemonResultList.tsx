'use client';

import {
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';
import { createPortal } from 'react-dom';
import {
  Check,
  CloudUpload,
  Copy,
  ExternalLink,
  Link2,
} from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import {
  fetchMagnetResolve,
  type MagnetHit,
} from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import { parseHighlight } from '@/lib/format';
import { runP115Save } from '@/lib/p115SaveClient';
import { useTabNavigation } from '@/shell';

function pickMagnets(data: {
  magnet?: string | null;
  magnets?: string[] | null;
}): string[] {
  const fromList = (data.magnets || []).filter((m) =>
    String(m || '').startsWith('magnet:'),
  );
  if (fromList.length) return [...new Set(fromList)];
  const one = (data.magnet || '').trim();
  return one.startsWith('magnet:') ? [one] : [];
}

export function LemonResultList({
  keyword,
  items,
  onItemsChange,
}: {
  keyword: string;
  items: MagnetHit[];
  onItemsChange: Dispatch<SetStateAction<MagnetHit[]>>;
}) {
  const tabCtx = useTabNavigation();
  const anchorRef = useRef<HTMLDivElement>(null);
  const [stackRoot, setStackRoot] = useState<Element | null>(null);
  const [msg, setMsg] = useState('');
  const [resolvingPath, setResolvingPath] = useState<string | null>(null);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [magnetSheet, setMagnetSheet] = useState<{
    title: string;
    magnets: string[];
    detailUrl: string;
  } | null>(null);
  const [sheetCopying, setSheetCopying] = useState<string | null>(null);
  const [saving115, setSaving115] = useState(false);

  useLayoutEffect(() => {
    setStackRoot(anchorRef.current?.closest('.app-stack-root') ?? null);
  }, []);

  async function copyMagnet(item: MagnetHit) {
    if (!keyword) return;
    setResolvingPath(item.path);
    try {
      let magnets = pickMagnets(item);
      if (!magnets.length) {
        const data = await fetchMagnetResolve({
          path: item.path,
          keyword,
        });
        magnets = pickMagnets(data);
        onItemsChange((prev) =>
          prev.map((x) =>
            x.path === item.path
              ? {
                  ...x,
                  magnet: magnets[0] || null,
                  magnets,
                }
              : x,
          ),
        );
      }
      if (!magnets.length) {
        setMsg('未拿到磁力链接');
        return;
      }

      // 先复制再开页：保住用户手势，并避免 copy 抢焦点打断 push 动画
      let copiedOk = false;
      let toast = '';
      if (magnets.length === 1) {
        copiedOk = await copyText(magnets[0]);
        toast = copiedOk ? '已复制，也可一键转存 115' : '请复制或转存 115';
      } else {
        toast = `共 ${magnets.length} 条磁力，可复制或转存 115`;
      }

      setResolvingPath(null);
      setMagnetSheet({
        title: item.title,
        magnets,
        detailUrl: item.detailUrl,
      });
      if (copiedOk) {
        setCopiedPath(item.path);
        window.setTimeout(() => {
          setCopiedPath((p) => (p === item.path ? null : p));
        }, 1800);
      }
      // toast 稍晚于 push，避免与入场动画叠在一起闪
      window.setTimeout(() => setMsg(toast), 280);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '获取磁力失败');
    } finally {
      setResolvingPath(null);
    }
  }

  async function copyOne(magnet: string, closeAfter = false) {
    setSheetCopying(magnet);
    try {
      const ok = await copyText(magnet);
      if (ok) {
        setMsg('已复制磁力链接');
        if (closeAfter) setMagnetSheet(null);
      } else {
        setMsg('仍无法自动复制，请长按文本全选');
      }
    } finally {
      setSheetCopying(null);
    }
  }

  async function copyAll() {
    if (!magnetSheet?.magnets.length) return;
    setSheetCopying('__all__');
    try {
      const ok = await copyText(magnetSheet.magnets.join('\n'));
      if (ok) {
        setMsg(`已复制全部 ${magnetSheet.magnets.length} 条`);
        setMagnetSheet(null);
      } else {
        setMsg('仍无法自动复制，请逐条长按复制');
      }
    } finally {
      setSheetCopying(null);
    }
  }

  async function saveTo115() {
    if (!magnetSheet?.magnets.length || saving115) return;
    setSaving115(true);
    try {
      const result = await runP115Save({
        urls: magnetSheet.magnets,
        titleHint: magnetSheet.title,
      });
      if (!result.ok) {
        setMsg(result.message);
        if (result.needConfig) {
          window.setTimeout(() => tabCtx?.scrollToTab('/settings'), 600);
        }
        return;
      }
      setMsg(result.message || '已转存');
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '转存 115 失败');
    } finally {
      setSaving115(false);
    }
  }

  return (
    <>
      <div ref={anchorRef} hidden aria-hidden />
      {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}

      <div className="resource-list magnet-bm-list">
        {items.map((item) => {
          const busy = resolvingPath === item.path;
          const copied = copiedPath === item.path;
          const count = pickMagnets(item).length;
          const ready = count > 0;
          return (
            <article key={item.path} className="resource-card magnet-bm-card">
              <div className="magnet-bm-card__head">
                <h2
                  className="resource-title allow-select"
                  dangerouslySetInnerHTML={{
                    __html: parseHighlight(item.title, [keyword]),
                  }}
                />
              </div>
              <div className="magnet-bm-card__foot">
                <div className="magnet-bm-card__meta">
                  {item.sizeText ? (
                    <span className="resource-size">{item.sizeText}</span>
                  ) : null}
                  {item.fileCount != null ? <span>{item.fileCount} 个文件</span> : null}
                  {item.createdAt ? <time>{item.createdAt}</time> : null}
                  {count > 1 ? (
                    <span className="magnet-bm-card__count">{count} 条磁力</span>
                  ) : null}
                  <a
                    className="magnet-bm-card__detail"
                    href={item.detailUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    详情
                  </a>
                </div>
                <button
                  type="button"
                  className={`magnet-bm-card__magnet${copied ? ' is-copied' : ''}${busy ? ' is-busy' : ''}`}
                  disabled={busy}
                  onClick={() => void copyMagnet(item)}
                >
                  {busy ? (
                    <span className="home-search__spinner" aria-hidden />
                  ) : copied ? (
                    <Check size={14} strokeWidth={2.5} aria-hidden />
                  ) : (
                    <Copy size={14} strokeWidth={2.25} aria-hidden />
                  )}
                  <span>
                    {busy
                      ? '解析中'
                      : copied
                        ? '已复制'
                        : ready
                          ? count > 1
                            ? `查看 ${count}`
                            : '复制'
                          : '获取'}
                  </span>
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {magnetSheet && stackRoot
        ? createPortal(
            <AppPush
              title={
                magnetSheet.magnets.length > 1
                  ? `磁力链接（${magnetSheet.magnets.length}）`
                  : '复制磁力'
              }
              onBack={() => setMagnetSheet(null)}
            >
              <div className="magnet-copy-page">
                <div className="magnet-copy-sheet__hero">
                  <span className="magnet-copy-sheet__badge" aria-hidden>
                    <Link2 size={18} strokeWidth={2.2} />
                  </span>
                  <p className="magnet-copy-sheet__title allow-select">{magnetSheet.title}</p>
                </div>

                {magnetSheet.magnets.length > 1 ? (
                  <ul className="magnet-copy-sheet__list">
                    {magnetSheet.magnets.map((m, i) => (
                      <li key={`${i}-${m.slice(0, 48)}`} className="magnet-copy-sheet__item">
                        <div className="magnet-copy-sheet__item-top">
                          <span className="magnet-copy-sheet__idx">#{i + 1}</span>
                          <button
                            type="button"
                            className="magnet-copy-sheet__item-copy"
                            disabled={Boolean(sheetCopying)}
                            onClick={() => void copyOne(m)}
                          >
                            {sheetCopying === m ? '…' : '复制'}
                          </button>
                        </div>
                        <textarea
                          className="magnet-copy-sheet__ta magnet-copy-sheet__ta--row allow-select"
                          readOnly
                          rows={2}
                          value={m}
                          onFocus={(e) => e.currentTarget.select()}
                          onClick={(e) => e.currentTarget.select()}
                        />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="magnet-copy-sheet__box">
                    <div className="magnet-copy-sheet__box-head">
                      <span>磁力链接</span>
                      <span className="mute">点按全选</span>
                    </div>
                    <textarea
                      className="magnet-copy-sheet__ta allow-select"
                      readOnly
                      rows={4}
                      value={magnetSheet.magnets[0] || ''}
                      onFocus={(e) => e.currentTarget.select()}
                      onClick={(e) => e.currentTarget.select()}
                    />
                  </div>
                )}

                <p className="magnet-copy-sheet__hint">
                  {magnetSheet.magnets.length > 1
                    ? '本条资源含多条磁力，可逐条复制或一次复制全部'
                    : '若自动复制失败，请长按上方链接全选后复制'}
                </p>

                <div className="magnet-copy-page__actions">
                  {magnetSheet.detailUrl ? (
                    <a
                      className="magnet-copy-sheet__btn magnet-copy-sheet__btn--ghost"
                      href={magnetSheet.detailUrl}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      <ExternalLink size={15} strokeWidth={2.2} aria-hidden />
                      详情
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="magnet-copy-sheet__btn magnet-copy-sheet__btn--115"
                    disabled={saving115 || !magnetSheet.magnets.length}
                    onClick={() => void saveTo115()}
                  >
                    <CloudUpload size={15} strokeWidth={2.2} aria-hidden />
                    {saving115 ? '转存中…' : '转存115'}
                  </button>
                  {magnetSheet.magnets.length > 1 ? (
                    <button
                      type="button"
                      className="magnet-copy-sheet__btn magnet-copy-sheet__btn--primary"
                      disabled={Boolean(sheetCopying) || saving115}
                      onClick={() => void copyAll()}
                    >
                      <Copy size={15} strokeWidth={2.2} aria-hidden />
                      {sheetCopying === '__all__' ? '复制中…' : '复制全部'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="magnet-copy-sheet__btn magnet-copy-sheet__btn--primary"
                      disabled={Boolean(sheetCopying) || saving115}
                      onClick={() => void copyOne(magnetSheet.magnets[0] || '', true)}
                    >
                      <Copy size={15} strokeWidth={2.2} aria-hidden />
                      {sheetCopying ? '复制中…' : '复制'}
                    </button>
                  )}
                </div>
              </div>
            </AppPush>,
            stackRoot,
          )
        : null}
    </>
  );
}
