'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Copy } from 'lucide-react';
import { fetchResource, proxiedCoverUrl } from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import { formatByteSize, formatDate } from '@/lib/format';
import {
  copyAllLabel,
  formatDescriptionLinesForItem,
  getDetailTitle,
  getEd2kCopyText,
  getExtractPassword,
  linkSectionTitle,
  linksForResource,
  normalizeLinkKind,
  normalizeResourceView,
  shortSourceLabel,
} from '@/lib/detailResource';
import type { ResourceItem } from '@/types/resource';
import { AppMsg } from '@/components/ui/AppMsg';
import { P115SaveButton } from './P115SaveButton';

function KvRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="bm-kv__row">
      <span className="bm-kv__k">{label}</span>
      <span className="bm-kv__v">{children}</span>
    </div>
  );
}

function CopyableCode({
  value,
  onCopy,
}: {
  value: string;
  onCopy: (text: string) => void;
}) {
  return (
    <code
      className="bm-hash allow-select"
      title="点击复制"
      role="button"
      tabIndex={0}
      onClick={() => onCopy(value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onCopy(value);
        }
      }}
    >
      {value}
    </code>
  );
}

type PreviewOrient = 'landscape' | 'portrait';

/** 详情预览：一行 4 槽，竖图 1 / 横图 2，同高；加载全部图 */
function PreviewGrid({ images }: { images: string[] }) {
  const MIN_PREVIEW_PX = 48;
  const [failed, setFailed] = useState<Record<number, true>>({});
  const [orientations, setOrientations] = useState<
    Record<number, PreviewOrient>
  >({});
  const proxied = images.map((u) => proxiedCoverUrl(u)).filter(Boolean);
  const proxiedKey = proxied.join('\0');

  const markFailed = (index: number) => {
    setFailed((prev) => (prev[index] ? prev : { ...prev, [index]: true }));
  };

  useEffect(() => {
    setFailed({});
    setOrientations({});
    if (!proxied.length) return;

    let cancelled = false;
    const loaders: HTMLImageElement[] = [];

    proxied.forEach((src, index) => {
      const img = new Image();
      loaders.push(img);
      const applyOk = () => {
        if (cancelled) return;
        if (
          !img.naturalWidth ||
          !img.naturalHeight ||
          img.naturalWidth < MIN_PREVIEW_PX ||
          img.naturalHeight < MIN_PREVIEW_PX
        ) {
          markFailed(index);
          return;
        }
        const next: PreviewOrient =
          img.naturalWidth > img.naturalHeight ? 'landscape' : 'portrait';
        setOrientations((prev) =>
          prev[index] === next ? prev : { ...prev, [index]: next },
        );
      };
      const applyErr = () => {
        if (cancelled) return;
        markFailed(index);
      };
      img.onload = applyOk;
      img.onerror = applyErr;
      img.src = src;
      if (img.complete && img.naturalWidth > 0) applyOk();
    });

    return () => {
      cancelled = true;
      for (const img of loaders) {
        img.onload = null;
        img.onerror = null;
        img.src = '';
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proxiedKey]);

  const slots = proxied
    .map((src, index) => ({
      src,
      index,
      orient: orientations[index],
    }))
    .filter(
      (s): s is { src: string; index: number; orient: PreviewOrient } =>
        !failed[s.index] && Boolean(s.orient),
    );
  const stillLoading = proxied.some(
    (_, i) => !failed[i] && !orientations[i],
  );
  if (!proxied.length) return null;
  if (!slots.length && !stillLoading) return null;

  return (
    <section className="bm-card">
      <header className="bm-card__head bm-card__head--static">内容预览</header>
      <div className="bm-card__body bm-card__body--preview">
        <div className="detail-preview-grid">
          {slots.map(({ src, index, orient }) => (
            <span
              key={`${src}-${index}`}
              className={`detail-preview-grid__slot detail-preview-grid__slot--${orient}`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt=""
                className="detail-preview-grid__img"
                onError={() => markFailed(index)}
              />
            </span>
          ))}
          {stillLoading ? (
            <span className="detail-preview-grid__slot detail-preview-grid__slot--landscape detail-preview-grid__slot--pending" />
          ) : null}
        </div>
      </div>
    </section>
  );
}

/** 色花详情：对齐 Bitmagnet bm-detail 分区 + 共用文件图标 */
export function ResourceDetailBody({ hash }: { hash: string }) {
  const [item, setItem] = useState<ResourceItem | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      setItem(null);
      try {
        const data = await fetchResource(hash);
        if (!cancelled) setItem(normalizeResourceView(data));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hash]);

  async function onCopy(text: string, success = '已复制') {
    if (!text?.trim()) {
      setMsg('暂无链接可复制');
      return;
    }
    const ok = await copyText(text);
    setMsg(ok ? success : '复制失败');
  }

  if (loading) return <p className="app-loading">加载中…</p>;
  if (error) return <div className="app-error">{error}</div>;
  if (!item) return null;

  const view = normalizeResourceView(item);
  const displayTitle = getDetailTitle(view) || hash;
  const detailRows = formatDescriptionLinesForItem(view);
  const extractPassword = getExtractPassword(view);
  const hasPasswordInDesc = detailRows.some((row) => row.label === '解压密码');
  const previews = view.preview_images || [];
  const links = linksForResource(view);
  const allCopy = getEd2kCopyText(view);
  const kind = normalizeLinkKind(view.link_kind);
  const passwordLabel = kind === '115share' ? '分享码' : '解压密码';

  return (
    <div className="bm-detail">
      {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}

      <h1 className="bm-detail__title allow-select">{displayTitle}</h1>

      <div className="bm-detail__stack">
        <section className="bm-card">
          <header className="bm-card__head bm-card__head--static">详情</header>
          <div className="bm-card__body">
            <div className="bm-kv">
              {detailRows.map((row) => (
                <KvRow key={row.label} label={row.label}>
                  {row.label === '解压密码' ? (
                    <CopyableCode
                      value={row.value}
                      onCopy={(v) => void onCopy(v, '已复制密码')}
                    />
                  ) : (
                    <span className="allow-select">{row.value}</span>
                  )}
                </KvRow>
              ))}

              {!hasPasswordInDesc && extractPassword ? (
                <KvRow label={passwordLabel}>
                  <CopyableCode
                    value={extractPassword}
                    onCopy={(v) => void onCopy(v, '已复制密码')}
                  />
                </KvRow>
              ) : null}

              {view.size ? (
                <KvRow label="大小">
                  <span className="allow-select">
                    {formatByteSize(view.size)}
                  </span>
                </KvRow>
              ) : null}

              {item.board_name ? (
                <KvRow label="板块">
                  <span className="allow-select">{item.board_name}</span>
                </KvRow>
              ) : null}

              {item.source_url ? (
                <KvRow label="来源">
                  <a
                    className="bm-magnet-line allow-select"
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {shortSourceLabel(item.source_url)}
                  </a>
                </KvRow>
              ) : null}

              {item.created_at ? (
                <KvRow label="收录">
                  <span className="allow-select">
                    {formatDate(item.created_at)}
                  </span>
                </KvRow>
              ) : null}

              {!detailRows.length &&
              !extractPassword &&
              !item.board_name &&
              !item.source_url &&
              !item.created_at ? (
                <KvRow label="Hash">
                  <span className="allow-select">{item.hash}</span>
                </KvRow>
              ) : null}
            </div>
          </div>
        </section>

        <section className="bm-card">
          <header className="bm-card__head bm-card__head--static bm-card__head--actions">
            <span>{linkSectionTitle(view.link_kind)}</span>
            <div className="bm-card__actions">
              <P115SaveButton item={view} compact onToast={setMsg} />
              {allCopy ? (
                <button
                  type="button"
                  className="bm-action-btn"
                  onClick={() =>
                    void onCopy(
                      allCopy,
                      kind === 'magnet' ? '已复制磁力' : '已复制链接',
                    )
                  }
                >
                  <Copy size={13} strokeWidth={2.25} aria-hidden />
                  {copyAllLabel(view)}
                </button>
              ) : null}
            </div>
          </header>
          <div className="bm-card__body">
            {links.length === 0 ? (
              <p className="detail-stub-hint">
                {kind === 'stub' ? '暂无可用下载链接' : '暂无链接'}
              </p>
            ) : (
              <div className="detail-link-list">
                {links.map((link, index) => (
                  <div key={`${link}-${index}`} className="detail-link-row">
                    <span className="detail-link-row__idx">{index + 1}</span>
                    <span className="detail-link-row__url allow-select">
                      {link}
                    </span>
                    <button
                      type="button"
                      className="detail-link-row__copy"
                      aria-label={`复制链接 ${index + 1}`}
                      onClick={() => void onCopy(link, '已复制')}
                    >
                      <Copy size={13} strokeWidth={2.25} aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {previews.length > 0 ? <PreviewGrid images={previews} /> : null}
      </div>
    </div>
  );
}
