'use client';

import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Inbox,
  LoaderCircle,
  Search,
} from 'lucide-react';
import type { ScrapLibraryEnrichQueueItem } from '@/lib/api';
import { cn } from '@/lib/utils';
import { EnrichTabIdle } from './EnrichTabIdle';
import {
  isPartialOk,
  QUEUE_PAGE_SIZE,
  queueRowDesc,
  rowKey,
  statusLabel,
  statusTone,
  type LiveTab,
} from './queueFormat';

export function EnrichLiveQueueList({
  tab,
  searchActive,
  searching,
  searchCode,
  scanTip,
  tabCounts,
  filteredQueue,
  queuePaging,
  queueScanning,
  hydrated,
  running,
  retryingFails,
  retryingSofts,
  clearing,
  onRetryFails,
  onRetrySofts,
  showQueuePager,
  pageShown,
  queuePageTotal,
  queueTotalForTab,
  goQueuePage,
  onOpenRow,
}: {
  tab: LiveTab;
  searchActive: boolean;
  searching: boolean;
  searchCode: string;
  scanTip: string;
  tabCounts: Record<LiveTab, number>;
  filteredQueue: ScrapLibraryEnrichQueueItem[];
  queuePaging: boolean;
  queueScanning: boolean;
  hydrated: boolean;
  running: boolean;
  retryingFails: boolean;
  retryingSofts: boolean;
  clearing: boolean;
  onRetryFails: () => void;
  onRetrySofts: () => void;
  showQueuePager: boolean;
  pageShown: number;
  queuePageTotal: number;
  queueTotalForTab: number;
  goQueuePage: (n: number) => void;
  onOpenRow: (key: string) => void;
}) {
  return (
    <>
      {searchActive ? (
        <p className="enrich-live__queue-hint">
          {searching
            ? `全局搜索 ${searchCode}…`
            : `全局搜索 ${searchCode} · ${filteredQueue.length} 条（跨全部状态）`}
        </p>
      ) : scanTip ? (
        <p className="enrich-live__queue-hint">{scanTip}</p>
      ) : null}
      {!searchActive && tab === 'fail' && Number(tabCounts.fail || 0) > 0 ? (
        <div className="enrich-live__fail-actions">
          <button
            type="button"
            className="makers-manage__probe-btn"
            disabled={
              retryingFails || retryingSofts || clearing || queueScanning
            }
            onClick={onRetryFails}
          >
            {retryingFails ? '重试中…' : '失败重试'}
          </button>
          <span className="enrich-live__fail-actions-hint">
            {`将 ${Number(tabCounts.fail || 0).toLocaleString()} 条失败转入未处理优先刮削`}
          </span>
        </div>
      ) : null}
      {!searchActive && tab === 'soft' && Number(tabCounts.soft || 0) > 0 ? (
        <div className="enrich-live__fail-actions">
          <button
            type="button"
            className="makers-manage__probe-btn"
            disabled={
              retryingSofts || retryingFails || clearing || queueScanning
            }
            onClick={onRetrySofts}
          >
            {retryingSofts ? '重试中…' : '软成功重试'}
          </button>
          <span className="enrich-live__fail-actions-hint">
            {`将 ${Number(tabCounts.soft || 0).toLocaleString()} 条软成功转入未处理优先刮削`}
          </span>
        </div>
      ) : null}
      {filteredQueue.length === 0 ? (
        queuePaging ? (
          <EnrichTabIdle
            waiting
            title="加载队列…"
            desc={`正在加载第 ${pageShown} 页`}
            icon={<LoaderCircle size={22} strokeWidth={2.2} />}
          />
        ) : searchActive ? (
          <EnrichTabIdle
            waiting={searching}
            title={searching ? '全局搜索中…' : '未找到番号'}
            desc={
              searching
                ? `正在跨全部状态查 ${searchCode}`
                : `未处理 / 成功 / 软成功 / 失败中都没有匹配 ${searchCode} 的记录`
            }
            icon={
              searching ? (
                <LoaderCircle size={22} strokeWidth={2.2} />
              ) : (
                <Search size={22} strokeWidth={2.2} />
              )
            }
          />
        ) : tab === 'pending' ? (
          <EnrichTabIdle
            waiting={
              Boolean(scanTip) || queueScanning || !hydrated || running
            }
            title={
              scanTip
                ? '扫描未处理任务…'
                : queueScanning || !hydrated
                  ? '扫描未处理任务…'
                  : running
                    ? '边扫边刮进行中…'
                    : '暂无未处理项'
            }
            desc={
              scanTip || queueScanning || !hydrated
                ? '正在对照库内空壳与本地缺口'
                : running
                  ? '扫描入队与刮削并行，新任务会出现在这里'
                  : '打开分区开关即可边扫边刮，或点「清空·扫描」按向量骨架−本地已分类重建队列'
            }
            icon={
              scanTip || queueScanning || !hydrated || running ? (
                <LoaderCircle size={22} strokeWidth={2.2} />
              ) : (
                <Inbox size={22} strokeWidth={2.2} />
              )
            }
          />
        ) : tab === 'done' ? (
          <EnrichTabIdle
            waiting={Boolean(scanTip)}
            tone={scanTip ? 'neutral' : 'ok'}
            title={scanTip ? '扫描本地成功项…' : '暂无成功项'}
            desc="有封面且有标题即计入成功（女优/片商/剧情等缺失也算）；点「清空·扫描」按磁盘重建"
            icon={
              scanTip ? (
                <LoaderCircle size={22} strokeWidth={2.2} />
              ) : (
                <CheckCircle2 size={22} strokeWidth={2.2} />
              )
            }
          />
        ) : tab === 'soft' ? (
          <EnrichTabIdle
            waiting={Boolean(scanTip)}
            tone={scanTip ? 'neutral' : 'ok'}
            title={scanTip ? '扫描本地软成功…' : '暂无软成功项'}
            desc="有封面但无标题才算软成功；点「清空·扫描」按磁盘重建"
            icon={
              scanTip ? (
                <LoaderCircle size={22} strokeWidth={2.2} />
              ) : (
                <CheckCircle2 size={22} strokeWidth={2.2} />
              )
            }
          />
        ) : (
          <EnrichTabIdle
            waiting={Boolean(scanTip)}
            tone={scanTip ? 'neutral' : 'fail'}
            title={scanTip ? '扫描本地失败项…' : '暂无失败项'}
            desc="无封面或网络/下载失败；点「清空·扫描」按磁盘重建"
            icon={
              scanTip ? (
                <LoaderCircle size={22} strokeWidth={2.2} />
              ) : (
                <CircleAlert size={22} strokeWidth={2.2} />
              )
            }
          />
        )
      ) : (
        <div className="enrich-live__body">
          <ul className="settings-group enrich-live__queue">
            {filteredQueue.map((row) => (
              <li key={rowKey(row)}>
                <button
                  type="button"
                  className={cn(
                    'settings-nav enrich-live__queue-row',
                    row.status === 'running' && 'enrich-live__queue-row--on',
                    row.status === 'done' &&
                      !isPartialOk(row) &&
                      'enrich-live__queue-row--ok',
                    row.status === 'done' &&
                      isPartialOk(row) &&
                      'enrich-live__queue-row--warn',
                    row.status === 'fail' && 'enrich-live__queue-row--fail',
                  )}
                  onClick={() => onOpenRow(rowKey(row))}
                >
                  <span
                    className={cn(
                      'enrich-live__queue-badge',
                      `enrich-live__queue-badge--${statusTone(row.status, row)}`,
                    )}
                  >
                    {statusLabel(row.status, row)}
                  </span>
                  <span className="settings-nav__main enrich-live__queue-main">
                    <span className="settings-nav__title">
                      {row.code || '—'}
                    </span>
                    <span className="settings-nav__desc">
                      {queueRowDesc(row) || '—'}
                    </span>
                  </span>
                  <span className="enrich-live__queue-meta">
                    {typeof row.totalMs === 'number'
                      ? `${row.totalMs}ms`
                      : typeof row.fetchMs === 'number'
                        ? `${row.fetchMs}ms`
                        : ''}
                  </span>
                  <ChevronRight
                    className="settings-nav__chev"
                    size={17}
                    strokeWidth={2.4}
                    aria-hidden
                  />
                </button>
              </li>
            ))}
          </ul>
          {showQueuePager ? (
            <div
              className="enrich-live__pager"
              role="navigation"
              aria-label="队列翻页"
            >
              <button
                type="button"
                className="enrich-live__pager-btn"
                disabled={pageShown <= 1 || queuePaging || queueScanning}
                onClick={() => goQueuePage(pageShown - 1)}
              >
                上一页
              </button>
              <span className="enrich-live__pager-meta">
                <span className="enrich-live__pager-page">
                  {pageShown}
                  <span className="enrich-live__pager-slash">/</span>
                  {queuePageTotal}
                </span>
                <span className="enrich-live__pager-total">
                  {(
                    (pageShown - 1) * QUEUE_PAGE_SIZE +
                    1
                  ).toLocaleString()}
                  –
                  {Math.min(
                    pageShown * QUEUE_PAGE_SIZE,
                    queueTotalForTab,
                  ).toLocaleString()}
                  <span className="enrich-live__pager-of">/</span>
                  {queueTotalForTab.toLocaleString()}
                  {queuePaging ? (
                    <span className="enrich-live__pager-loading">加载中</span>
                  ) : null}
                </span>
              </span>
              <button
                type="button"
                className="enrich-live__pager-btn"
                disabled={
                  pageShown >= queuePageTotal || queuePaging || queueScanning
                }
                onClick={() => goQueuePage(pageShown + 1)}
              >
                下一页
              </button>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}
