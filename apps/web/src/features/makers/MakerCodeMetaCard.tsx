'use client';

import { useEffect, useMemo, useState } from 'react';
import { CroppedCoverImg } from '@/components/cover/CroppedCoverImg';
import {
  fetchScrapeExportDetail,
  scrapeExportImageUrl,
  type ScrapeExportDetail,
} from '@/lib/api';

function isChineseTitle(s: string | null | undefined): boolean {
  const t = String(s || '').trim();
  if (!t) return false;
  const han = (t.match(/[\u4e00-\u9fff]/g) || []).length;
  const kana = (t.match(/[\u3040-\u30ff]/g) || []).length;
  return han >= 2 && han >= kana;
}

function normalizePlotText(s: string): string {
  return String(s || '')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function pickTitle(detail: ScrapeExportDetail): string {
  const codeU = String(detail.code || '')
    .trim()
    .toUpperCase();
  for (const raw of [detail.titleZh, detail.title]) {
    const t = String(raw || '').trim();
    if (t && t.toUpperCase() !== codeU && isChineseTitle(t)) return t;
  }
  for (const raw of [detail.originalTitle, detail.title]) {
    const t = String(raw || '').trim();
    if (t && t.toUpperCase() !== codeU) return t;
  }
  return codeU || '';
}

function pickPlot(detail: ScrapeExportDetail, title: string): string {
  const plot = normalizePlotText(detail.plot || '');
  if (!plot) return '';
  if (plot === title.trim()) return '';
  return plot;
}

function posterCandidates(detail: ScrapeExportDetail): string[] {
  const out: string[] = [];
  const push = (u?: string | null) => {
    const s = String(u || '').trim();
    if (s && !out.includes(s)) out.push(s);
  };
  if (detail.posterLocal) {
    push(scrapeExportImageUrl({ rel: detail.posterLocal }));
  }
  if (detail.coverLocal) {
    push(scrapeExportImageUrl({ rel: detail.coverLocal }));
  }
  const remote = String(detail.poster || '').trim();
  if (remote) {
    push(
      scrapeExportImageUrl({
        code: detail.code || undefined,
        url: remote,
      }),
    );
  }
  return out;
}

/**
 * 番号页顶部：片库元数据（刮削优先，缺省回退索引物化）。
 * 布局：左封面、右元数据。
 */
export function MakerCodeMetaCard({
  code,
  region,
}: {
  code: string;
  region?: string;
}) {
  const [detail, setDetail] = useState<ScrapeExportDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setDetail(null);
    void fetchScrapeExportDetail(code, ac.signal)
      .then((d) => {
        if (!ac.signal.aborted) setDetail(d || null);
      })
      .catch(() => {
        if (!ac.signal.aborted) setDetail(null);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [code]);

  const title = useMemo(() => (detail ? pickTitle(detail) : ''), [detail]);
  const plot = useMemo(() => (detail ? pickPlot(detail, title) : ''), [detail, title]);
  const actors = useMemo(
    () => (detail?.actors || []).map((a) => String(a || '').trim()).filter(Boolean),
    [detail],
  );
  const tags = useMemo(
    () =>
      (detail?.genres || [])
        .map((g) => String(g || '').trim())
        .filter((g) => g && !/^(4k|8k|hd|fhd|1080p|720p|高清)$/i.test(g)),
    [detail],
  );
  const covers = useMemo(() => (detail ? posterCandidates(detail) : []), [detail]);
  const cropRegion = String(detail?.region || region || '').trim() || undefined;

  const hasContent =
    covers.length > 0 ||
    Boolean(title) ||
    actors.length > 0 ||
    tags.length > 0 ||
    Boolean(plot);

  if (loading) {
    return (
      <div className="mk-code-meta mk-code-meta--loading" aria-busy="true">
        <div className="mk-code-meta__cover mk-code-meta__skel" />
        <div className="mk-code-meta__body">
          <div className="mk-code-meta__skel-line mk-code-meta__skel-line--lg" />
          <div className="mk-code-meta__skel-line" />
          <div className="mk-code-meta__skel-line mk-code-meta__skel-line--sm" />
        </div>
      </div>
    );
  }

  if (!hasContent) {
    const codeLabel = String(code || '').trim();
    if (!codeLabel) return null;
    return (
      <section className="mk-code-meta" aria-label="片库元数据">
        <div className="mk-code-meta__cover">
          <div className="mk-code-meta__cover-empty">无封面</div>
        </div>
        <div className="mk-code-meta__body">
          <h2 className="mk-code-meta__title mk-code-meta__title--code allow-select">
            {codeLabel}
          </h2>
        </div>
      </section>
    );
  }

  return (
    <section className="mk-code-meta" aria-label="片库元数据">
      <div className="mk-code-meta__cover">
        <CroppedCoverImg
          src={covers[0]}
          srcs={covers.slice(1)}
          region={cropRegion}
          alt={`${code} 封面`}
          layout="thumb"
          loading="eager"
          emptyClassName="mk-code-meta__cover-empty"
          emptyLabel="无封面"
          className="mk-code-meta__img"
          frameClassName="mk-code-meta__frame"
        />
      </div>
      <div className="mk-code-meta__body">
        {title ? (
          <h2 className="mk-code-meta__title allow-select">{title}</h2>
        ) : (
          <h2 className="mk-code-meta__title mk-code-meta__title--code allow-select">
            {code}
          </h2>
        )}
        {actors.length > 0 ? (
          <p className="mk-code-meta__actors allow-select">{actors.join('、')}</p>
        ) : null}
        {tags.length > 0 ? (
          <div className="mk-code-meta__tags" aria-label="标签">
            {tags.slice(0, 8).map((t) => (
              <span key={t} className="mk-code-meta__tag">
                {t}
              </span>
            ))}
          </div>
        ) : null}
        {plot ? (
          <p className="mk-code-meta__plot allow-select" title={plot}>
            {plot}
          </p>
        ) : null}
      </div>
    </section>
  );
}
