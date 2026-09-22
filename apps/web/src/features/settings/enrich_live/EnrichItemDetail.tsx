'use client';

import { useEffect, useState } from 'react';
import { getScrapLibraryEnrichLocalCovers, type ScrapLibraryEnrichCurrent } from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import { cn } from '@/lib/utils';
import {
  ENRICH_POSTER_W,
  ENRICH_SHOT_W,
  ensurePosterField,
  localCoverSrc,
} from './cover';
import { gapsText, statusLabel } from './queueFormat';
import { displayHitSource, sourceIconMeta } from './sourceMeta';

function FieldSourceIcon({ source }: { source?: string }) {
  const meta = sourceIconMeta(String(source || ''));
  if (!meta.id) return null;
  return (
    <span
      className="enrich-live__field-src"
      title={meta.label}
      style={
        {
          ['--enrich-src-hue' as string]: String(meta.hue),
        } as Record<string, string>
      }
    >
      {meta.label}
    </span>
  );
}

export function EnrichItemDetail({
  detail,
  regionId,
}: {
  detail: ScrapLibraryEnrichCurrent;
  regionId: string;
}) {
  const timingsRaw = detail.sourceTimings || [];
  const timings = [...timingsRaw].sort((a, b) => {
    const rank = (t: (typeof timingsRaw)[number]) => {
      const st = String(t.status || '');
      if (st === 'done' || t.ok) return 0;
      if (st === 'fail' || t.error) return 1;
      if (st === 'skipped') return 3;
      return 2;
    };
    const d = rank(a) - rank(b);
    if (d !== 0) return d;
    return Number(b.ms || 0) - Number(a.ms || 0);
  });
  const maxSrcMs = timings.reduce(
    (m, t) => Math.max(m, Number(t.ms || 0)),
    0,
  );
  const fields = ensurePosterField(detail.fields || [], {
    posterDownloaded: detail.posterDownloaded,
  });
  const wallMs =
    typeof detail.fetchMs === 'number' ? detail.fetchMs : null;
  const totalMs =
    typeof detail.totalMs === 'number' ? detail.totalMs : null;
  const coverMs =
    typeof detail.coverMs === 'number' ? detail.coverMs : null;
  const vectorMs =
    typeof detail.vectorMs === 'number' ? detail.vectorMs : null;
  const actressMs =
    typeof detail.actressMs === 'number' ? detail.actressMs : null;
  const timingParts = [
    wallMs != null ? `拉源 ${wallMs}ms` : '',
    coverMs != null ? `封面 ${coverMs}ms` : '',
    vectorMs != null ? `向量 ${vectorMs}ms` : '',
    actressMs != null ? `女优 ${actressMs}ms` : '',
  ].filter(Boolean);

  const [localCovers, setLocalCovers] = useState<{
    ready: boolean;
    folder: string;
    poster: string;
    extras: Array<{ key: string; label: string; url: string }>;
  }>({ ready: false, folder: '', poster: '', extras: [] });
  /** 原图横/竖：横图不进 2:3 竖框裁切 */
  const [posterLandscape, setPosterLandscape] = useState(false);

  useEffect(() => {
    const code = String(detail.code || '').trim();
    const iid = String(detail.itemId || detail.relPath || '').trim();
    if (!code && !iid) {
      setLocalCovers({ ready: true, folder: '', poster: '', extras: [] });
      setPosterLandscape(false);
      return;
    }
    let alive = true;
    setPosterLandscape(false);
    setLocalCovers((prev) => ({ ...prev, ready: false }));
    void (async () => {
      try {
        const data = await getScrapLibraryEnrichLocalCovers({
          region: regionId,
          code,
          itemId: iid,
        });
        if (!alive) return;
        const files = Array.isArray(data.files) ? data.files : [];
        const posterFile =
          files.find((f) => f.kind === 'poster') ||
          (data.posterApi ? { posterApi: data.posterApi, mtime: 0 } : null);
        const poster = localCoverSrc(
          posterFile?.posterApi,
          posterFile?.mtime,
          ENRICH_POSTER_W,
        );
        const extras: Array<{ key: string; label: string; url: string }> = [];
        const labels: Record<string, string> = {
          thumb: '横图',
          fanart: '剧照',
        };
        for (const f of files) {
          if (f.kind === 'poster') continue;
          const url = localCoverSrc(f.posterApi, f.mtime, ENRICH_SHOT_W);
          if (!url || url === poster) continue;
          extras.push({
            key: String(f.kind || f.name || extras.length),
            label: labels[String(f.kind || '')] || String(f.name || '图'),
            url,
          });
        }
        setLocalCovers({
          ready: true,
          folder: String(data.folder || ''),
          poster,
          extras,
        });
      } catch {
        if (!alive) return;
        setLocalCovers({ ready: true, folder: '', poster: '', extras: [] });
      }
    })();
    return () => {
      alive = false;
    };
  }, [detail.code, detail.itemId, detail.relPath, regionId]);

  const showPoster = localCovers.poster;
  const extraShots = localCovers.extras;
  const coverHint = !showPoster
    ? localCovers.ready
      ? localCovers.folder
        ? '目录无 poster.jpg'
        : '未找到本地番号目录'
      : '读取本地封面…'
    : '';

  useEffect(() => {
    setPosterLandscape(false);
  }, [showPoster]);

  return (
    <div className="enrich-live__detail">
      <ul className="settings-group">
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">番号</span>
            <span className="settings-kv__val allow-select">
              {detail.code || '—'}
            </span>
          </div>
        </li>
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">状态</span>
            <span className="settings-kv__val">
              {statusLabel(detail.status, detail)}
              {typeof detail.index === 'number' &&
              typeof detail.total === 'number'
                ? ` · ${detail.index + 1}/${detail.total}`
                : totalMs != null
                  ? ` · 总耗时 ${totalMs}ms`
                  : wallMs != null
                    ? ` · 拉源 ${wallMs}ms`
                    : ''}
            </span>
          </div>
        </li>
        {(totalMs != null || timingParts.length > 0) && (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">耗时</span>
              <span className="settings-kv__val">
                {totalMs != null ? `合计 ${totalMs}ms` : '合计 —'}
                {timingParts.length ? ` · ${timingParts.join(' · ')}` : ''}
              </span>
            </div>
          </li>
        )}
        <li>
          <div className="settings-kv">
            <span className="settings-kv__key">缺口</span>
            <span className="settings-kv__val">
              {gapsText(detail.gaps) || '—'}
            </span>
          </div>
        </li>
        {detail.detailTitle ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">标题</span>
              <span className="settings-kv__val allow-select">
                {detail.detailTitle}
              </span>
            </div>
          </li>
        ) : null}
        {detail.source && displayHitSource(detail.source) ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">命中源</span>
              <span className="settings-kv__val">
                {displayHitSource(detail.source)}
                {wallMs != null ? ` · 拉源 ${wallMs}ms` : ''}
                {maxSrcMs > 0 ? ` · 最慢源 ${maxSrcMs}ms` : ''}
              </span>
            </div>
          </li>
        ) : null}
        {typeof detail.posterDownloaded === 'boolean' ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">封面下载</span>
              <span className="settings-kv__val">
                {detail.posterDownloaded ? '已落盘' : '未落盘'}
                {coverMs != null ? ` · ${coverMs}ms` : ''}
              </span>
            </div>
          </li>
        ) : null}
        {detail.status === 'done' ||
        detail.status === 'fail' ||
        typeof detail.vectorSynced === 'boolean' ||
        detail.vectorSkipped ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">向量</span>
              <span className="settings-kv__val">
                {detail.vectorSkipped
                  ? '本步跳过（仅本地）'
                  : detail.vectorSynced
                    ? '已同步'
                    : detail.vectorError
                      ? `未同步 · ${detail.vectorError}`
                      : detail.status === 'running'
                        ? '同步中…'
                        : ['local_scan', 'scan'].includes(
                              String(detail.source || '').trim(),
                            )
                          ? '本地扫描分类'
                          : '未同步'}
                {!detail.vectorSkipped && vectorMs != null
                  ? ` · ${vectorMs}ms`
                  : ''}
                {!detail.vectorSkipped && actressMs != null
                  ? ` · 女优 ${actressMs}ms`
                  : ''}
              </span>
            </div>
          </li>
        ) : null}
        {detail.error ? (
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">错误</span>
              <span className="settings-kv__val">{detail.error}</span>
            </div>
          </li>
        ) : null}
      </ul>

      <p className="settings-group-label">刮削图片</p>
      <div className="enrich-live__covers">
        {showPoster ? (
          <div
            className={cn(
              'enrich-live__cover enrich-live__cover--poster',
              posterLandscape && 'enrich-live__cover--landscape',
            )}
          >
            <SoftImg
              src={showPoster}
              alt={detail.code || 'poster'}
              className="enrich-live__cover-img"
              onLoad={(e) => {
                const el = e.currentTarget;
                const w = el.naturalWidth || 0;
                const h = el.naturalHeight || 0;
                setPosterLandscape(w > 0 && h > 0 && w > h);
              }}
            />
          </div>
        ) : (
          <div className="enrich-live__cover enrich-live__cover--empty">
            <span className="enrich-live__cover-empty-text">{coverHint}</span>
          </div>
        )}
        {localCovers.folder ? (
          <p className="enrich-live__cover-path allow-select">{localCovers.folder}</p>
        ) : null}
        {extraShots.length > 0 ? (
          <div className="enrich-live__cover-row">
            {extraShots.map((shot) => (
              <div key={shot.key} className="enrich-live__cover enrich-live__cover--shot">
                <SoftImg
                  src={shot.url}
                  alt={shot.label}
                  className="enrich-live__cover-img"
                />
                <span className="enrich-live__cover-cap">{shot.label}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <p className="settings-group-label">字段情况</p>
      <ul className="settings-group">
        {fields.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                {detail.status === 'running'
                  ? '拉取中…'
                  : '暂无字段结果（旧任务可能未保留）'}
              </span>
            </div>
          </li>
        ) : (
          fields.map((f) => {
            const srcLabel = String(f.source || '').trim();
            const rawVal = f.ok ? f.value || '有' : '无';
            const isPoster = f.id === 'poster' || f.label === '封面';
            const val =
              isPoster && f.ok && /^https?:\/\//i.test(String(f.value || ''))
                ? '有链接'
                : rawVal;
            return (
              <li key={f.id || f.label}>
                <div
                  className={cn(
                    'settings-kv enrich-live__field-kv',
                    !f.ok && 'enrich-live__field-kv--miss',
                  )}
                >
                  <span className="settings-kv__key enrich-live__field-key">
                    <span className="enrich-live__field-label">
                      {f.ok ? '✓ ' : '· '}
                      {f.label || f.id}
                    </span>
                    <FieldSourceIcon source={srcLabel} />
                  </span>
                  <span className="settings-kv__val enrich-live__field-val allow-select">
                    {val}
                  </span>
                </div>
              </li>
            );
          })
        )}
      </ul>

      <p className="settings-group-label">
        源耗时
        {timings.length > 0 ? ` · ${timings.length}` : ''}
        {wallMs != null ? ` · 拉源墙钟 ${wallMs}ms` : ''}
        {maxSrcMs > 0 ? ` · 最慢 ${maxSrcMs}ms` : ''}
      </p>
      <ul className="settings-group">
        {timings.length === 0 ? (
          <li>
            <div className="settings-kv">
              <span className="settings-nav__desc">
                {['local_scan', 'scan'].includes(
                  String(detail.source || '').trim(),
                )
                  ? '本地扫描分类，无各站刮削耗时；重刮后会写入番号目录 SONE-999.log'
                  : '暂无源耗时（刮削后写入番号目录 {番号}.log，清空·扫描可回读）'}
              </span>
            </div>
          </li>
        ) : (
          timings.map((t, i) => {
            const tone =
              t.status === 'done' || t.ok
                ? 'done'
                : t.status === 'fail' || t.error
                  ? 'fail'
                  : t.status === 'skipped'
                    ? 'skip'
                    : 'pending';
            return (
              <li key={`${t.id || i}-${t.ms || 0}`}>
                <div className="settings-kv">
                  <span className="settings-kv__key">
                    <span
                      className={cn(
                        'enrich-live__src-mark',
                        `enrich-live__src-mark--${tone}`,
                      )}
                    />
                    {t.id || '源'}
                  </span>
                  <span className="settings-kv__val">
                    {typeof t.ms === 'number' ? `${t.ms}ms` : '—'}
                    {t.poster ? ' · 封面' : ''}
                    {typeof t.actors === 'number' && t.actors > 0
                      ? ` · 女优${t.actors}`
                      : ''}
                    {t.error ? ` · ${t.error}` : ''}
                  </span>
                </div>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}
