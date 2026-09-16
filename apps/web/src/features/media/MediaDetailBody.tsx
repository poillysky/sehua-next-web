'use client';

import { useEffect, useRef, useState } from 'react';
import { Cloud, ExternalLink, HardDrive, LoaderCircle, Search, Star } from 'lucide-react';
import {
  fetchCloudSaverSearch,
  fetchMediaRelated,
  fetchPansouSearch,
  type MediaCastPerson,
  type MediaItem,
  type PansouHit,
  type PansouLink,
  proxiedCoverUrl,
} from '@/lib/api';
import { copyText } from '@/lib/clipboard';
import { linkKindOf } from '@/lib/resourceView';
import { runP115Save } from '@/lib/p115SaveClient';
import { useTabNavigation } from '@/shell';
import { SoftImg } from '@/components/SoftImg';
import { useOverlay } from '@/components/overlay/OverlayContext';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { openHomeSearchFromItem, pickCloudSearchKeyword } from './mediaUi';
import { MediaPosterCard } from './MediaPosterCard';

type CloudSearchKind = 'pansou' | 'cloudsaver';

function is115ShareLink(lk: PansouLink): boolean {
  return linkKindOf(lk.url) === '115share';
}

function isOfflineSaveLink(lk: PansouLink): boolean {
  const kind = linkKindOf(lk.url);
  return kind === 'magnet' || kind === 'ed2k';
}

function canSaveTo115(lk: PansouLink): boolean {
  return is115ShareLink(lk) || isOfflineSaveLink(lk);
}

function pickAka(item: MediaItem): string[] {
  return [item.originalTitle, ...(item.aka || [])]
    .map((s) => String(s || '').trim())
    .filter(Boolean)
    .filter((s, i, arr) => arr.indexOf(s) === i && s !== item.title)
    .filter((s) => /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z0-9]/.test(s))
    .filter(
      (s) => !/^[\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u1780-\u17FF]+/.test(s),
    )
    .slice(0, 2);
}

const COUNTRY_SHORT: Record<string, string> = {
  'United States of America': '美国',
  'United States': '美国',
  USA: '美国',
  'United Kingdom': '英国',
  UK: '英国',
  Japan: '日本',
  China: '中国',
  'Hong Kong': '中国香港',
  Taiwan: '中国台湾',
  'South Korea': '韩国',
  Korea: '韩国',
  France: '法国',
  Germany: '德国',
  Italy: '意大利',
  Spain: '西班牙',
  Canada: '加拿大',
  Australia: '澳大利亚',
  India: '印度',
  Thailand: '泰国',
  Russia: '俄罗斯',
};

function shortCountry(name: string): string {
  const s = String(name || '').trim();
  return COUNTRY_SHORT[s] || s;
}

function normalizeCast(raw: MediaItem['cast']): MediaCastPerson[] {
  if (!Array.isArray(raw)) return [];
  const out: MediaCastPerson[] = [];
  for (const row of raw) {
    if (typeof row === 'string') {
      const name = row.trim();
      if (name) out.push({ name });
      continue;
    }
    if (row && typeof row === 'object' && 'name' in row) {
      const name = String(row.name || '').trim();
      if (!name) continue;
      const id =
        row.id != null && String(row.id).trim() ? String(row.id) : undefined;
      const avatarUrl =
        row.avatarUrl != null && String(row.avatarUrl).trim()
          ? String(row.avatarUrl)
          : undefined;
      out.push({ name, id, avatarUrl });
    }
  }
  return out.slice(0, 12);
}

export function MediaDetailBody({
  item,
  enriching = false,
  onOpenRelated,
  onOpenPerson,
}: {
  item: MediaItem;
  /** 列表项已展示、详情接口仍在拉取时 */
  enriching?: boolean;
  onOpenRelated?: (next: MediaItem) => void;
  onOpenPerson?: (person: MediaCastPerson) => void;
}) {
  const tabCtx = useTabNavigation();
  const { toast } = useOverlay();
  const [imgGone, setImgGone] = useState(false);
  const [related, setRelated] = useState<MediaItem[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(Boolean(onOpenRelated));
  const [cloudBusy, setCloudBusy] = useState(false);
  const [cloudOpen, setCloudOpen] = useState(false);
  const [cloudKind, setCloudKind] = useState<CloudSearchKind>('pansou');
  const [cloudKw, setCloudKw] = useState('');
  const [cloudItems, setCloudItems] = useState<PansouHit[] | null>(null);
  const [cloudTotal, setCloudTotal] = useState(0);
  const [saving115, setSaving115] = useState<string | null>(null);
  const cloudAbortRef = useRef<AbortController | null>(null);
  /** 同一条目内锁定首张已展示海报，避免详情回填换 URL 导致闪没再载 */
  const stickyPosterRef = useRef<{ id: string; url: string }>({
    id: item.id,
    url: proxiedCoverUrl(item.posterUrl),
  });
  const nextPoster = proxiedCoverUrl(item.posterUrl);
  if (stickyPosterRef.current.id !== item.id) {
    stickyPosterRef.current = { id: item.id, url: nextPoster };
  } else if (nextPoster && !stickyPosterRef.current.url) {
    stickyPosterRef.current.url = nextPoster;
  }
  const poster = stickyPosterRef.current.url;
  const cast = normalizeCast(item.cast);
  const showCastSkel = enriching && cast.length === 0;
  const showRelatedSkel = Boolean(onOpenRelated) && relatedLoading && related.length === 0;

  useEffect(() => {
    setImgGone(false);
    setCloudOpen(false);
    setCloudKw('');
    setCloudItems(null);
    setCloudTotal(0);
    setCloudBusy(false);
    setSaving115(null);
    cloudAbortRef.current?.abort();
    cloudAbortRef.current = null;
  }, [item.id]);

  useEffect(() => {
    return () => {
      cloudAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!onOpenRelated) {
      setRelated([]);
      setRelatedLoading(false);
      return;
    }
    if (enriching) {
      setRelated([]);
      setRelatedLoading(true);
      return;
    }
    let cancelled = false;
    setRelatedLoading(true);
    void (async () => {
      try {
        const data = await fetchMediaRelated({
          source: item.source,
          mediaType: item.mediaType,
          id: item.id,
        });
        if (cancelled) return;
        const merged = [
          ...(data.recommendations || []),
          ...(data.similar || []),
        ];
        const seen = new Set<string>();
        const uniq: MediaItem[] = [];
        for (const row of merged) {
          const k = `${row.source}-${row.id}`;
          if (seen.has(k) || row.id === item.id) continue;
          seen.add(k);
          uniq.push(row);
          if (uniq.length >= 12) break;
        }
        setRelated(uniq);
      } catch {
        if (!cancelled) setRelated([]);
      } finally {
        if (!cancelled) setRelatedLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.id, item.mediaType, item.source, onOpenRelated, enriching]);

  const akaLine = pickAka(item);
  const rating =
    item.rating != null && Number(item.rating) > 0
      ? Number(item.rating).toFixed(1)
      : null;

  function onSearch() {
    const ok = openHomeSearchFromItem(item, (t) => tabCtx?.scrollToTab(t));
    if (!ok) toast('没有可用的片名用于搜索', 'error');
    else toast('已跳转 BT 库搜索', 'success');
  }

  async function onCloudSearch(kind: CloudSearchKind) {
    const kw = pickCloudSearchKeyword(item);
    if (!kw) {
      toast('没有可用的片名用于搜索', 'error');
      return;
    }
    cloudAbortRef.current?.abort();
    const ac = new AbortController();
    cloudAbortRef.current = ac;
    setCloudKind(kind);
    setCloudKw(kw);
    setCloudOpen(true);
    setCloudBusy(true);
    setCloudItems(null);
    setCloudTotal(0);
    try {
      const data =
        kind === 'cloudsaver'
          ? await fetchCloudSaverSearch({ keyword: kw, signal: ac.signal })
          : await fetchPansouSearch({ keyword: kw, signal: ac.signal });
      if (ac.signal.aborted) return;
      setCloudItems(data.items || []);
      setCloudTotal(data.total || data.items?.length || 0);
    } catch (e) {
      if (ac.signal.aborted) return;
      const msg =
        e instanceof Error
          ? e.message
          : kind === 'cloudsaver'
            ? 'CloudSaver 搜索失败'
            : '盘搜失败';
      toast(msg, 'error');
      setCloudItems([]);
      setCloudTotal(0);
    } finally {
      if (!ac.signal.aborted) setCloudBusy(false);
    }
  }

  function onCloseCloud() {
    cloudAbortRef.current?.abort();
    cloudAbortRef.current = null;
    setCloudOpen(false);
    setCloudBusy(false);
  }

  async function onCopyLink(url: string, password?: string) {
    const text = password ? `${url}\n提取码: ${password}` : url;
    const ok = await copyText(text);
    toast(ok ? (password ? '已复制链接和提取码' : '已复制链接') : '复制失败', ok ? 'success' : 'error');
  }

  async function onSave115(lk: PansouLink, titleHint: string) {
    if (saving115) return;
    setSaving115(lk.url);
    try {
      const result = await runP115Save({
        urls: [lk.url],
        password: lk.password || undefined,
        titleHint,
        source: item.mediaType === 'tv' ? 'tv' : 'movie',
      });
      toast(result.message || (result.ok ? '已转存' : '转存失败'), result.ok ? 'success' : 'error');
    } catch (e) {
      toast(e instanceof Error ? e.message : '转存失败', 'error');
    } finally {
      setSaving115(null);
    }
  }

  const cloudLabel = cloudKind === 'cloudsaver' ? 'CloudSaver' : '盘搜';

  return (
    <div className="media-detail">
      {poster && !imgGone ? (
        <div className="media-detail__wash" aria-hidden>
          <SoftImg
            src={poster}
            loading="eager"
            fetchPriority="high"
            onError={() => setImgGone(true)}
          />
        </div>
      ) : null}

      <div className="media-detail__hero">
        <div className="media-detail__poster" aria-hidden>
          <span className="media-detail__poster-ph">
            {item.title.slice(0, 1)}
          </span>
          {poster && !imgGone ? (
            <SoftImg
              src={poster}
              loading="eager"
              fetchPriority="high"
              onError={() => setImgGone(true)}
            />
          ) : null}
          {rating ? (
            <span className="media-detail__score">
              <Star size={11} strokeWidth={2.6} aria-hidden />
              <span className="media-detail__score-n">{rating}</span>
            </span>
          ) : null}
        </div>
        <div className="media-detail__meta">
          <h2 className="media-detail__title allow-select">{item.title}</h2>
          {akaLine.length > 0 ? (
            <p className="media-detail__aka allow-select">
              {akaLine.join(' · ')}
            </p>
          ) : null}

          <div className="media-detail__stats">
            <div className="media-detail__stats-main">
              <p className="media-detail__meta-line allow-select">
                {[
                  item.year || '',
                  item.mediaType === 'tv' ? '剧集' : '电影',
                  item.runtime ? `${item.runtime} 分钟` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              {(item.genres?.length || item.countries?.length) ? (
                <div className="media-detail__tags" aria-label="类型与地区">
                  {(item.genres || []).slice(0, 4).map((g) => (
                    <span key={`g-${g}`} className="media-detail__tag">
                      {g}
                    </span>
                  ))}
                  {(item.countries || []).slice(0, 2).map((c) => (
                    <span
                      key={`c-${c}`}
                      className="media-detail__tag media-detail__tag--place"
                    >
                      {shortCountry(c)}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>

        </div>
      </div>

      {cast.length > 0 || showCastSkel ? (
        <section className="media-detail__section media-detail__cast-sec">
          <h3 className="media-detail__h">主演</h3>
          {showCastSkel ? (
            <div className="media-detail__cast-rail" aria-hidden>
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="media-detail__cast-card media-detail__cast-card--static"
                >
                  <span className="media-detail__cast-avatar media-detail__cast-skel" />
                  <span className="media-detail__cast-skel-name" />
                </div>
              ))}
            </div>
          ) : (
            <div className="media-detail__cast-rail">
              {cast.map((p, i) => {
                const avatar = proxiedCoverUrl(p.avatarUrl);
                const body = (
                  <>
                    <span className="media-detail__cast-avatar" aria-hidden>
                      {avatar ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={avatar}
                          alt=""
                          loading="lazy"
                          decoding="async"
                          referrerPolicy="no-referrer"
                        />
                      ) : (
                        <span className="media-detail__cast-ph">
                          {p.name.slice(0, 1)}
                        </span>
                      )}
                    </span>
                    <span className="media-detail__cast-name">{p.name}</span>
                  </>
                );
                return onOpenPerson ? (
                  <button
                    key={`${p.id || p.name}-${i}`}
                    type="button"
                    className="media-detail__cast-card"
                    onClick={() => onOpenPerson(p)}
                  >
                    {body}
                  </button>
                ) : (
                  <div
                    key={`${p.id || p.name}-${i}`}
                    className="media-detail__cast-card media-detail__cast-card--static"
                  >
                    {body}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      ) : null}

      {item.overview ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">简介</h3>
          <p className="media-detail__overview allow-select">{item.overview}</p>
        </section>
      ) : enriching ? (
        <section className="media-detail__section" aria-hidden>
          <h3 className="media-detail__h">简介</h3>
          <div className="media-detail__overview-skel">
            <span />
            <span />
            <span />
            <span className="media-detail__overview-skel__short" />
          </div>
        </section>
      ) : null}

      <div className="media-detail__actions">
        <button type="button" className="media-detail__cta media-detail__cta--bt" onClick={onSearch}>
          <Search size={17} strokeWidth={2.25} aria-hidden />
          BT 库
        </button>
        <button
          type="button"
          className="media-detail__cta media-detail__cta--pansou"
          onClick={() => void onCloudSearch('pansou')}
          disabled={cloudBusy && cloudKind === 'pansou' && cloudOpen}
        >
          {cloudBusy && cloudKind === 'pansou' && cloudOpen ? (
            <LoaderCircle size={17} strokeWidth={2.4} className="media-detail__cta-spin" aria-hidden />
          ) : (
            <HardDrive size={17} strokeWidth={2.25} aria-hidden />
          )}
          盘搜
        </button>
        <button
          type="button"
          className="media-detail__cta media-detail__cta--cloudsaver"
          onClick={() => void onCloudSearch('cloudsaver')}
          disabled={cloudBusy && cloudKind === 'cloudsaver' && cloudOpen}
        >
          {cloudBusy && cloudKind === 'cloudsaver' && cloudOpen ? (
            <LoaderCircle size={17} strokeWidth={2.4} className="media-detail__cta-spin" aria-hidden />
          ) : (
            <Cloud size={17} strokeWidth={2.25} aria-hidden />
          )}
          CS
        </button>
      </div>

      <AppCenterModal
        open={cloudOpen}
        title={
          cloudBusy
            ? `${cloudLabel}中`
            : cloudTotal > 0
              ? `${cloudLabel} · ${cloudTotal}`
              : cloudLabel
        }
        onClose={onCloseCloud}
        cardClassName={
          cloudKind === 'cloudsaver' ? 'pansou-modal pansou-modal--cs' : 'pansou-modal'
        }
      >
        {cloudKw ? (
          <div className="pansou-modal__kw">
            <span className="pansou-modal__kw-label">关键词</span>
            <span className="pansou-modal__kw-text allow-select">{cloudKw}</span>
          </div>
        ) : null}
        {cloudBusy ? (
          <div className="pansou-modal__loading">
            <LoaderCircle size={22} strokeWidth={2.2} className="media-detail__cta-spin" />
            <span>正在拉取网盘结果…</span>
          </div>
        ) : cloudItems && cloudItems.length === 0 ? (
          <div className="pansou-modal__empty">
            <HardDrive size={28} strokeWidth={1.75} aria-hidden />
            <span>没有找到相关网盘资源</span>
          </div>
        ) : (
          <ul className="pansou-list">
            {(cloudItems || []).map((hit, idx) => (
              <li key={hit.id} className="pansou-card">
                <div className="pansou-card__head">
                  <span className="pansou-card__idx" aria-hidden>
                    {idx + 1}
                  </span>
                  <div className="pansou-card__head-main">
                    <p className="pansou-card__title allow-select">{hit.title}</p>
                    {hit.channel ? (
                      <p className="pansou-card__meta">{hit.channel}</p>
                    ) : null}
                  </div>
                </div>
                {hit.links.length > 0 ? (
                  <div className="pansou-card__links">
                    {hit.links.map((lk) => (
                      <div
                        key={`${hit.id}-${lk.url}`}
                        className={`pansou-link pansou-link--${lk.type || 'other'}`}
                      >
                        <span className="pansou-link__type">{lk.label || lk.type}</span>
                        <div className="pansou-link__actions">
                          {lk.password ? (
                            <span className="pansou-link__pwd allow-select">
                              码 {lk.password}
                            </span>
                          ) : null}
                          {canSaveTo115(lk) ? (
                            <button
                              type="button"
                              className="pansou-link__save"
                              disabled={saving115 != null}
                              onClick={() => void onSave115(lk, hit.title)}
                            >
                              {saving115 === lk.url ? '转存中' : '转存'}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="pansou-link__copy"
                            onClick={() => void onCopyLink(lk.url, lk.password)}
                          >
                            复制
                          </button>
                          <a
                            className="pansou-link__open"
                            href={lk.url}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            <ExternalLink size={13} strokeWidth={2.35} aria-hidden />
                            打开
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="pansou-card__meta">暂无可用链接</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </AppCenterModal>

      {onOpenRelated && (showRelatedSkel || related.length > 0) ? (
        <section className="media-detail__section">
          <h3 className="media-detail__h">相似推荐</h3>
          {showRelatedSkel ? (
            <div className="media-shelf__rail media-shelf__rail--skel" aria-hidden>
              {Array.from({ length: 5 }).map((_, i) => (
                <span key={i} className="media-poster-skel" />
              ))}
            </div>
          ) : (
            <div className="media-shelf__rail">
              {related.map((it) => (
                <MediaPosterCard
                  key={`${it.source}-${it.id}`}
                  item={it}
                  size="sm"
                  onClick={() => onOpenRelated(it)}
                />
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
