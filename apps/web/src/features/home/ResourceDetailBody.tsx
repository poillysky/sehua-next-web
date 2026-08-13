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

function DetailInfoRow({ label, children }: { label: string; children: ReactNode }) {
  const labelText = label.replace(/[:：]\s*$/, '');
  return (
    <div className="detail-info-row">
      <dt className="detail-info-row__label">{labelText}：</dt>
      <dd className="detail-info-row__value">{children}</dd>
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
      className="detail-copy-code allow-select"
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

function PreviewGrid({ images }: { images: string[] }) {
  const [failed, setFailed] = useState<Record<number, true>>({});
  const proxied = images.map((u) => proxiedCoverUrl(u)).filter(Boolean);
  useEffect(() => {
    setFailed({});
  }, [proxied.join('\0')]);

  const visible = proxied
    .map((src, index) => ({ src, index }))
    .filter(({ index }) => !failed[index]);
  if (!visible.length) return null;

  return (
    <section className="detail-card">
      <header className="detail-card__head">预览</header>
      <div className="detail-card__body detail-card__body--preview">
        <div className="detail-preview-grid">
          {visible.map(({ src, index }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={`${src}-${index}`}
              src={src}
              alt=""
              loading="lazy"
              className="detail-preview-grid__img"
              onError={() =>
                setFailed((prev) => (prev[index] ? prev : { ...prev, [index]: true }))
              }
            />
          ))}
        </div>
      </div>
    </section>
  );
}

/** 资源详情正文（色花 DetailClient 子集 · AppPush 内） */
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
    <div className="detail-stack">
      {msg ? (
        <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg>
      ) : null}

      <div className="detail-hero">
        <h1 className="detail-title allow-select">{displayTitle}</h1>
        <div className="detail-meta">
          {item.size ? (
            <span className="detail-meta__chip detail-meta__chip--size">
              {formatByteSize(item.size)}
            </span>
          ) : null}
          {item.board_name ? (
            <span className="detail-meta__chip">{item.board_name}</span>
          ) : null}
          {item.created_at ? (
            <span className="detail-meta__chip">{formatDate(item.created_at)}</span>
          ) : null}
          {kind !== 'other' ? (
            <span className="detail-meta__chip detail-meta__chip--kind">
              {kind === '115share'
                ? '115'
                : kind === 'magnet'
                  ? '磁力'
                  : kind === 'stub'
                    ? '占位'
                    : 'ed2k'}
            </span>
          ) : null}
        </div>
      </div>

      <section className="detail-card">
        <header className="detail-card__head">详情</header>
        <div className="detail-card__body">
          <dl className="detail-info-list">
            {detailRows.map((row) => (
              <DetailInfoRow key={row.label} label={row.label}>
                {row.label === '解压密码' ? (
                  <CopyableCode value={row.value} onCopy={(v) => void onCopy(v, '已复制密码')} />
                ) : (
                  <span className="allow-select">{row.value}</span>
                )}
              </DetailInfoRow>
            ))}

            {!hasPasswordInDesc && extractPassword ? (
              <DetailInfoRow label={passwordLabel}>
                <CopyableCode
                  value={extractPassword}
                  onCopy={(v) => void onCopy(v, '已复制密码')}
                />
              </DetailInfoRow>
            ) : null}

            {item.forum_name ? (
              <DetailInfoRow label="论坛">
                <span className="allow-select">{item.forum_name}</span>
              </DetailInfoRow>
            ) : null}

            {item.board_name ? (
              <DetailInfoRow label="板块">
                <span className="allow-select">{item.board_name}</span>
              </DetailInfoRow>
            ) : null}

            {item.source_url ? (
              <DetailInfoRow label="来源">
                <a
                  className="detail-source-link allow-select"
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {shortSourceLabel(item.source_url)}
                </a>
              </DetailInfoRow>
            ) : null}

            {item.created_at ? (
              <DetailInfoRow label="收录时间">
                <span className="allow-select">{formatDate(item.created_at)}</span>
              </DetailInfoRow>
            ) : null}

            {!detailRows.length &&
            !extractPassword &&
            !item.forum_name &&
            !item.board_name &&
            !item.source_url &&
            !item.created_at ? (
              <DetailInfoRow label="Hash">
                <span className="allow-select">{item.hash}</span>
              </DetailInfoRow>
            ) : null}
          </dl>
        </div>
      </section>

      {previews.length > 0 ? <PreviewGrid images={previews} /> : null}

      <section className="detail-card">
        <header className="detail-card__head detail-card__head--actions">
          <span>{linkSectionTitle(view.link_kind)}</span>
          <div className="detail-card__actions">
            <P115SaveButton item={view} compact onToast={setMsg} />
            {allCopy ? (
              <button
                type="button"
                className="detail-compact-btn"
                onClick={() =>
                  void onCopy(allCopy, kind === 'magnet' ? '已复制磁力' : '已复制链接')
                }
              >
                {copyAllLabel(view)}
              </button>
            ) : null}
          </div>
        </header>
        <div className="detail-card__body">
          {links.length === 0 ? (
            <p className="detail-stub-hint">
              {kind === 'stub' ? '暂无可用下载链接' : '暂无链接'}
            </p>
          ) : (
            <div className="detail-link-list">
              {links.map((link, index) => (
                <div key={`${link}-${index}`} className="detail-link-row">
                  <span className="detail-link-row__idx">{index + 1}</span>
                  <span className="detail-link-row__url allow-select">{link}</span>
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
    </div>
  );
}
