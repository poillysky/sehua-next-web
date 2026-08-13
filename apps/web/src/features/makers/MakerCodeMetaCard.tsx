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

function pickTitle(detail: ScrapeExportDetail): string {
  const codeU = String(detail.code || '')
    .trim()
    .toUpperCase();
  const zh = String(detail.titleZh || '').trim();
  if (zh && isChineseTitle(zh)) return zh;
  const ja = [detail.originalTitle, detail.title]
    .map((x) => String(x || '').trim())
    .find((t) => t && t.toUpperCase() !== codeU);
  return ja || zh || '';
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
  const actors = useMemo(
    () => (detail?.actors || []).map((a) => String(a || '').trim()).filter(Boolean),
    [detail],
  );
  const tags = useMemo(
    () => (detail?.genres || []).map((g) => String(g || '').trim()).filter(Boolean),
    [detail],
  );
  const plot = String(detail?.plot || '').trim();
  const studio = String(detail?.studio || '').trim();
  const series = String(detail?.series || '').trim();
  const covers = useMemo(() => (detail ? posterCandidates(detail) : []), [detail]);
  const cropRegion = String(detail?.region || region || '').trim() || undefined;

  const metaBits = [studio, series].filter(Boolean);
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

  if (!hasContent) return null;

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
        {metaBits.length > 0 ? (
          <p className="mk-code-meta__meta allow-select">{metaBits.join(' · ')}</p>
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
