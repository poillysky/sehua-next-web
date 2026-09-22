'use client';

import { useEffect, useState } from 'react';
import { scrapLibraryCoverUrl } from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 标题尾名与女优栏繁简不一致时仍能对上（辉/輝、绮/綺…）。 */
export function foldActressKey(s: string): string {
  return String(s || '')
    .normalize('NFKC')
    .replace(/[輝]/g, '辉')
    .replace(/[綺]/g, '绮')
    .replace(/[羅]/g, '罗')
    .replace(/[宮]/g, '宫')
    .replace(/[樹]/g, '树')
    .replace(/[愛]/g, '爱')
    .replace(/[麗]/g, '丽')
    .replace(/[條]/g, '条')
    .replace(/[絲]/g, '丝')
    .toLowerCase();
}

const TITLE_TAIL_NAME_RE =
  /(?:[\s\u3000！!。．.…⋯—–―－\-]+)([\u4e00-\u9fff]{2,8})\s*$/;

/** 详情标题不展示尾部女优名（女优栏已有）。 */
export function stripTrailingActressName(title: string, names: string[]): string {
  const s = String(title || '').trim();
  if (!s || names.length === 0) return s;

  const sorted = [...names]
    .map((n) => n.trim())
    .filter((n) => n.length >= 2)
    .sort((a, b) => b.length - a.length);

  let cur = s;
  for (let guard = 0; guard < 6; guard += 1) {
    const m = TITLE_TAIL_NAME_RE.exec(cur);
    if (!m) break;
    const tail = m[1];
    const body = cur.slice(0, m.index).trim();
    if (body.length < 4) break;
    const tailFold = foldActressKey(tail);
    const hit = sorted.some((n) => {
      const nf = foldActressKey(n);
      return (
        tail === n ||
        tailFold === nf ||
        (tailFold.length >= 2 && (tailFold.includes(nf) || nf.includes(tailFold)))
      );
    });
    if (!hit) {
      let matched = false;
      for (const n of sorted) {
        const re = new RegExp(
          `(?:[\\s\\u3000！!。．.…⋯—–―－\\-]+)${escapeRegExp(n)}\\s*$`,
        );
        if (!re.test(cur)) continue;
        const next = cur.replace(re, '').trim();
        if (next.length < 4) return cur;
        cur = next;
        matched = true;
        break;
      }
      if (!matched) break;
      continue;
    }
    cur = body;
  }
  return cur;
}

export function MkdActressAvatar({
  name,
  posterApi,
  onOpen,
}: {
  name: string;
  posterApi?: string;
  onOpen?: (name: string, posterApi?: string) => void;
}) {
  const [gone, setGone] = useState(false);
  const [bust, setBust] = useState(0);
  const base =
    !gone && posterApi
      ? scrapLibraryCoverUrl(
          { posterApi },
          { w: 128, prefer: 'poster', rp: false },
        )
      : '';
  const src = base
    ? `${base}${base.includes('?') ? '&' : '?'}_cb=${bust || 0}`
    : '';

  useEffect(() => {
    setGone(false);
    setBust(0);
  }, [posterApi, name]);

  return (
    <button
      type="button"
      className="mkd-actress"
      onClick={() => onOpen?.(name, posterApi)}
    >
      <span className="mkd-actress__avatar" aria-hidden>
        <span className="mkd-actress__ph">{name.slice(0, 1)}</span>
        {src ? (
          <SoftImg
            src={src}
            loading="eager"
            fetchPriority="high"
            onError={() => {
              if (bust === 0) setBust(Date.now());
              else setGone(true);
            }}
          />
        ) : null}
      </span>
      <span className="mkd-actress__name allow-select">{name}</span>
    </button>
  );
}
