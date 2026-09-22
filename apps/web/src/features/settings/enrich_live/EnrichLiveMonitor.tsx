'use client';

import { Activity, ChevronRight, LoaderCircle } from 'lucide-react';
import type {
  EnrichMonitorInflight,
  ScrapLibraryEnrichJobStatus,
  ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import { EnrichTabIdle } from './EnrichTabIdle';
import {
  findQueueForMonitor,
  formatMs,
  monitorRowDesc,
  topStallKinds,
} from './monitorFormat';
import { rowKey } from './queueFormat';

export function EnrichLiveMonitor({
  running,
  hasCheckpoint,
  monitor,
  runningViewRows,
  hasRunningRows,
  liveRunningPool,
  queueItems,
  onOpenRow,
}: {
  running: boolean;
  hasCheckpoint: boolean;
  monitor: ScrapLibraryEnrichJobStatus['monitor'] | null;
  runningViewRows: EnrichMonitorInflight[];
  hasRunningRows: boolean;
  liveRunningPool: ScrapLibraryEnrichQueueItem[];
  queueItems: ScrapLibraryEnrichQueueItem[];
  onOpenRow: (key: string) => void;
}) {
  return (
    <div className="enrich-live__monitor">
      {(running || runningViewRows.length > 0) && (
        <p className="enrich-live__queue-hint">
          番号并发 {Number(monitor?.itemWorkers || 5)} · 进行中{' '}
          {Number(
            monitor?.summary?.inflightN ||
              runningViewRows.length ||
              liveRunningPool.length ||
              0,
          )}
          {Number(monitor?.summary?.stallingN || 0) > 0
            ? ` · 卡顿 ${Number(monitor?.summary?.stallingN || 0)}`
            : ''}
          {Number(monitor?.summary?.avgFetchMs || 0) > 0
            ? ` · 均耗时 ${formatMs(monitor?.summary?.avgFetchMs)}`
            : ''}
          {' · '}
          {topStallKinds(monitor)}
        </p>
      )}
      {!hasRunningRows ? (
        <EnrichTabIdle
          waiting={running}
          title={running ? '等待番号占槽…' : '暂无进行中任务'}
          desc={
            running
              ? '占槽后会显示各路阶段、耗时与卡顿原因；改策略后下一番号即用新数据源'
              : hasCheckpoint
                ? '已暂停 · 新策略保存后立即生效，继续刮削用最新配置'
                : '开始刮削后，最多 5 路番号进度会出现在这里'
          }
          icon={
            running ? (
              <LoaderCircle size={22} strokeWidth={2.2} />
            ) : (
              <Activity size={22} strokeWidth={2.2} />
            )
          }
        />
      ) : (
        <ul className="settings-group enrich-live__queue">
          {runningViewRows.map((row) => {
            const stall = row.stall?.label || '';
            const stallKind = String(row.stall?.kind || '').trim();
            const softStall = Boolean(
              stall &&
                (!stallKind ||
                  [
                    'slot_blocked',
                    'cover_slow',
                    'source_slow',
                    'fetch_tail',
                    'all_sources_pending',
                    'actress_slow',
                    'write_slow',
                  ].includes(stallKind)),
            );
            const hardStall = Boolean(stall && !softStall);
            const matched = findQueueForMonitor(row, [
              ...liveRunningPool,
              ...queueItems,
            ]);
            const desc = monitorRowDesc(row);
            const rowTone = hardStall ? 'fail' : softStall ? 'warn' : 'on';
            const badgeTone = hardStall
              ? 'fail'
              : softStall
                ? 'warn'
                : 'running';
            const badgeText = hardStall
              ? '卡顿'
              : softStall
                ? '偏慢'
                : row.phaseLabel || '处理中';
            return (
              <li key={`${row.code || ''}-${row.itemId || ''}`}>
                {matched ? (
                  <button
                    type="button"
                    className={cn(
                      'settings-nav enrich-live__queue-row',
                      `enrich-live__queue-row--${rowTone}`,
                    )}
                    onClick={() => onOpenRow(rowKey(matched))}
                  >
                    <span
                      className={cn(
                        'enrich-live__queue-badge',
                        `enrich-live__queue-badge--${badgeTone}`,
                      )}
                    >
                      {badgeText}
                    </span>
                    <span className="settings-nav__main enrich-live__queue-main">
                      <span className="settings-nav__title">
                        {row.code || matched.code || '—'}
                      </span>
                      <span className="settings-nav__desc">{desc}</span>
                    </span>
                    <span className="enrich-live__queue-meta">
                      {formatMs(row.elapsedMs)}
                    </span>
                    <ChevronRight
                      className="settings-nav__chev"
                      size={17}
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </button>
                ) : (
                  <div
                    className={cn(
                      'settings-nav enrich-live__queue-row enrich-live__queue-row--static',
                      `enrich-live__queue-row--${rowTone}`,
                    )}
                  >
                    <span
                      className={cn(
                        'enrich-live__queue-badge',
                        `enrich-live__queue-badge--${badgeTone}`,
                      )}
                    >
                      {badgeText}
                    </span>
                    <span className="settings-nav__main enrich-live__queue-main">
                      <span className="settings-nav__title">
                        {row.code || '—'}
                      </span>
                      <span className="settings-nav__desc">{desc}</span>
                    </span>
                    <span className="enrich-live__queue-meta">
                      {formatMs(row.elapsedMs)}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
