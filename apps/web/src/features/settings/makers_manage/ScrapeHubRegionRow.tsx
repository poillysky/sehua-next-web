'use client';

import { Switch } from '@/components/ui/switch';
import type { ScrapLibraryEnrichJobStatus } from '@/lib/api';

import type { EnrichRegionRow } from './types';
import type { MakersManagePanelState } from './useMakersManagePanel';

export function ScrapeHubRegionRow({
  p,
  region,
}: {
  p: MakersManagePanelState;
  region: EnrichRegionRow;
}) {
  const active = p.enrichBusy && p.enrichCurrentRegion === region.id;
  const cp = p.enrichCheckpoints[region.id];
  const prog = active
    ? p.enrichProgress
    : p.enrichProgressByRegion[region.id] || null;
  // 暂停态也用队列表角标（成功/失败），勿只信本轮 checkpoint.ok=15
  // 优先本区 regionQueueCounts，避免 FC2 卡片吃到有码全局数
  const regionQc = p.enrichRegionQueueCounts?.[region.id] || null;
  const qc =
    regionQc ||
    ((active || Boolean(cp)) &&
    p.enrichQueueCounts &&
    p.enrichCurrentRegion === region.id
      ? p.enrichQueueCounts
      : null);
  const okN = (() => {
    if (qc) return Number(qc.done || 0) + Number(qc.soft || 0);
    if (typeof prog?.ok === 'number') return prog.ok;
    if (typeof cp?.ok === 'number') return cp.ok;
    return null;
  })();
  const failN = (() => {
    if (qc) return Number(qc.fail || 0);
    if (typeof prog?.failed === 'number') return prog.failed;
    if (typeof cp?.failed === 'number') return cp.failed;
    return null;
  })();
  const remainingN = (() => {
    const libInc = Number(p.enrichLibrary[region.id]?.incomplete || 0);
    if (qc) {
      return Math.max(
        Number(qc.pending || 0) + Number(qc.running || 0),
        libInc,
      );
    }
    if (!active && typeof cp?.remaining === 'number') {
      return Math.max(cp.remaining, libInc);
    }
    const tot =
      typeof prog?.total === 'number' && prog.total > 0
        ? prog.total
        : typeof cp?.total === 'number' && cp.total > 0
          ? cp.total
          : Number(p.enrichLibrary[region.id]?.total || 0) || null;
    const fin =
      okN != null || failN != null
        ? Number(okN || 0) + Number(failN || 0)
        : typeof prog?.done === 'number'
          ? prog.done
          : null;
    if (tot != null && fin != null) {
      return Math.max(0, tot - fin, libInc);
    }
    return libInc > 0 ? libInc : null;
  })();
  // 进度%：优先库内已齐比例；避免队列表样例把进度撑到 50%+
  const pct = (() => {
    const lib = p.enrichLibrary[region.id];
    if (
      lib &&
      typeof lib.percent === 'number' &&
      Number(lib.total || 0) > 0
    ) {
      return Math.max(0, Math.min(100, Math.round(lib.percent)));
    }
    const rem = remainingN;
    const complete = Number(lib?.complete || 0);
    if (rem != null && (complete > 0 || rem > 0)) {
      const tot = complete + rem;
      if (tot > 0) {
        return Math.max(
          0,
          Math.min(100, Math.round((100 * complete) / tot)),
        );
      }
    }
    const fin =
      okN != null || failN != null
        ? Number(okN || 0) + Number(failN || 0)
        : null;
    if (fin != null && rem != null) {
      const tot = fin + rem;
      if (tot > 0) {
        return Math.max(
          0,
          Math.min(100, Math.round((100 * fin) / tot)),
        );
      }
      return 0;
    }
    if (
      typeof prog?.total === 'number' &&
      prog.total > 0 &&
      typeof prog?.done === 'number'
    ) {
      return Math.max(
        0,
        Math.min(100, Math.round((100 * prog.done) / prog.total)),
      );
    }
    return active ? 0 : null;
  })();
  const queueStage = prog?.stage === 'queue';
  // 六区互斥：仅「当前开着 / 正在跑 / 有暂停检查点」的分区显示进度条。
  const showProgress = active || region.enabled || Boolean(cp);
  const finN = Number(okN || 0) + Number(failN || 0);
  const speedState =
    p.enrichSpeedRef.current?.regionId === region.id
      ? p.enrichSpeedRef.current
      : null;
  // 一旦真正开始补齐（有完成数，或 stage=enrich），锁住「补齐中」，避免 queue 心跳闪回筛选
  if (
    active &&
    speedState &&
    (finN > 0 ||
      prog?.stage === 'enrich' ||
      prog?.stage === 'disk' ||
      prog?.stage === 'write')
  ) {
    speedState.lockedEnrich = true;
  }
  const stickEnrich = Boolean(active && speedState?.lockedEnrich);
  // 开关关着 + 有检查点 = 已暂停（点开关再开即续跑）；开着且正在跑才是补齐中。
  let stageLabel = active
    ? queueStage && !stickEnrich
      ? String(prog?.label || '').trim() ||
        (p.enrichMode === 'overwrite' ? '排队' : '筛选')
      : prog?.stage === 'done'
        ? '完成'
        : '补齐中'
    : cp
      ? '已暂停'
      : !region.enabled
        ? prog?.stage === 'done'
          ? '已完成'
          : '进度'
        : prog?.stage === 'done'
          ? '已完成'
          : '进度';
  // 速率：短窗滑动，避免 lifetime 大基数 + EMA 粘在「5 部/分」
  const rateLabel = (() => {
    if (!active) return '';
    if (stageLabel !== '补齐中') {
      return stickEnrich && speedState?.rateText ? speedState.rateText : '';
    }
    const sp = speedState;
    if (!sp) return '';
    const now = Date.now();
    const minsAll = (now - sp.t0) / 60000;
    if (minsAll < 0.08) return sp.rateText || '';
    // 优先近 60s 增量（更贴近当前吞吐）；窗口不足再用全程
    const samples = sp.samples || (sp.samples = []);
    samples.push({ t: now, fin: finN });
    const cutoff = now - 60_000;
    while (samples.length > 2 && samples[0]!.t < cutoff) {
      samples.shift();
    }
    const first = samples[0]!;
    const last = samples[samples.length - 1]!;
    const winMins = Math.max(0.05, (last.t - first.t) / 60000);
    const winDelta = Math.max(0, last.fin - first.fin);
    const instant =
      samples.length >= 2 && winMins >= 0.15
        ? winDelta / winMins
        : Math.max(0, finN - sp.fin0) / minsAll;
    if (instant < 0.05 && minsAll < 0.6 && sp.rateEma == null) {
      return sp.rateText || '';
    }
    const next =
      sp.rateEma == null ? instant : sp.rateEma * 0.55 + instant * 0.45;
    sp.rateEma = next;
    const prevShown = Number.parseFloat(sp.rateText) || 0;
    let show = next;
    if (sp.rateText) {
      if (Math.abs(next - prevShown) < 0.8) show = prevShown;
      else show = Math.round(next);
    } else {
      show = next >= 10 ? Math.round(next) : next;
    }
    const text =
      show >= 10 || Number.isInteger(show)
        ? `${Math.round(show)} 部/分`
        : `${show.toFixed(1).replace(/\.0$/, '')} 部/分`;
    sp.rateText = text;
    return text;
  })();

  return (
    <li>
      <div className="settings-nav makers-manage__status">
        <span className="makers-manage__status-lead">
          <Switch
            checked={region.enabled}
            disabled={(() => {
              // 当前正在跑的分区必须可关（暂停）；其它忙态才锁死
              const activeHere =
                p.enrichBusy && p.enrichCurrentRegion === region.id;
              if (activeHere) return false;
              return (
                p.enrichRegionBusy ||
                p.strmBusy ||
                p.localIndexBusy ||
                p.catalogBusy ||
                p.scrapBusy ||
                p.enrichBusy
              );
            })()}
            onCheckedChange={(v) =>
              void p.toggleEnrichRegion(region.id, Boolean(v))
            }
          />
          <span className="settings-nav__main">
            <span className="settings-nav__title">{region.label}</span>
          </span>
        </span>
        <span className="makers-manage__status-actions">
          <button
            type="button"
            className="makers-manage__probe-btn"
            onClick={() => {
              p.setScrapQualityByRegion((prev) => {
                const next = { ...prev };
                delete next[region.id];
                return next;
              });
              p.setScanLogModal({
                qualityRegion: region.id,
                label: region.label,
              });
              p.setGateSummary('');
              void p.refreshScrapQuality([region.id]);
            }}
          >
            详情
          </button>
          <button
            type="button"
            className="makers-manage__probe-btn"
            onClick={() => {
              const activeHere =
                p.enrichBusy && p.enrichCurrentRegion === region.id;
              const rowProg = activeHere
                ? p.enrichProgress
                : p.enrichProgressByRegion[region.id] || null;
              const regionLog = p.enrichRegionLogs[region.id] || [];
              const seed: ScrapLibraryEnrichJobStatus = {
                running: Boolean(activeHere),
                phase: activeHere
                  ? p.enrichPhase || rowProg?.label || '补齐中…'
                  : p.enrichCheckpoints[region.id]
                    ? 'paused'
                    : '',
                progress: rowProg,
                log: regionLog.length
                  ? regionLog.slice(-40)
                  : p.enrichLog.slice(-40),
                regionLogs: p.enrichRegionLogs,
                currentRegion: p.enrichCurrentRegion,
                checkpoints: p.enrichCheckpoints,
                paused: Boolean(p.enrichCheckpoints[region.id]),
                queue: [],
                current: null,
                result: null,
              };
              p.setEnrichLive({
                regionId: region.id,
                label: region.label,
                initialStatus: seed,
                initialLogs: regionLog.slice(-200),
              });
            }}
          >
            日志
          </button>
        </span>
      </div>
      {showProgress ? (
        <div className="makers-manage__scan-progress" aria-live="polite">
          {active || pct != null ? (
            <div
              className="makers-manage__scan-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct != null ? Math.round(pct) : 0}
              aria-label={`${region.label}刮削进度`}
            >
              <span style={{ width: `${pct != null ? pct : 0}%` }} />
            </div>
          ) : null}
          <div className="makers-manage__scan-meta">
            <span className="makers-manage__scan-meta-main">
              <span>
                {stageLabel}
                {rateLabel ? ` · ${rateLabel}` : ''}
              </span>
            </span>
            {pct != null ? (
              <span className="makers-manage__scan-pct">
                {`${Math.round(pct)}%`}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}
