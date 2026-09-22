'use client';

import { scrapeJobsLocked } from './helpers';
import type { MakersManagePanelState } from './useMakersManagePanel';

/** 向量入库：同步数据库 + 数据库向量化 */
export function ScrapeHubEmbed({ p }: { p: MakersManagePanelState }) {
  const locked = scrapeJobsLocked(p);
  return (
    <>
      <p className="settings-group-label">向量入库</p>
      <ul className="settings-group makers-manage__rise">
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">同步数据库</span>
              <span className="settings-nav__desc">
                {p.scrapBusy && p.scrapJobMode === 'meta'
                  ? p.scrapPhase || '同步中…'
                  : '本地 NFO→元库 · 增量跳过未变 · 全量重写（磁盘无则删库）· 不编码向量'}
              </span>
            </span>
            <span className="makers-manage__status-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onScrapEmbedSync(false, 'meta')}
              >
                {p.scrapBusy && p.scrapJobMode === 'meta'
                  ? p.scrapPct != null
                    ? `${Math.round(p.scrapPct)}%`
                    : '同步中…'
                  : '增量同步'}
              </button>
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onScrapEmbedSync(true, 'meta')}
              >
                {p.scrapBusy && p.scrapJobMode === 'meta' ? '…' : '全量同步'}
              </button>
            </span>
          </div>
          {(p.scrapJobMode === 'meta' || p.scrapJobMode === 'full') &&
          (p.scrapBusy || p.scrapProgress || p.scrapLog.length > 0) ? (
            <div className="makers-manage__scan-progress" aria-live="polite">
              {p.scrapBusy || p.scrapProgress ? (
                <div
                  className="makers-manage__scan-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={p.scrapPct != null ? Math.round(p.scrapPct) : 0}
                  aria-label="同步数据库进度"
                >
                  <span
                    style={{
                      width: `${p.scrapPct != null ? p.scrapPct : 0}%`,
                    }}
                  />
                </div>
              ) : null}
              <div className="makers-manage__scan-meta">
                <span>
                  {p.scrapBusy || p.scrapProgress
                    ? p.scrapProgress?.stage === 'scan'
                      ? '扫描'
                      : p.scrapProgress?.stage === 'diff'
                        ? '比对'
                        : p.scrapProgress?.stage === 'covers'
                          ? '封面'
                          : p.scrapProgress?.stage === 'done'
                            ? '完成'
                            : '准备'
                    : '已完成'}
                  {p.scrapCountLabel ? ` · ${p.scrapCountLabel}` : ''}
                </span>
                <span className="makers-manage__scan-meta-actions">
                  {p.scrapPct != null && (p.scrapBusy || p.scrapProgress) ? (
                    <span className="makers-manage__scan-pct">
                      {`${Math.round(p.scrapPct)}%`}
                    </span>
                  ) : null}
                  {p.scrapLog.length > 0 ? (
                    <button
                      type="button"
                      className="makers-manage__log-btn"
                      onClick={() => p.setScanLogModal('scrap')}
                    >
                      日志
                    </button>
                  ) : null}
                </span>
              </div>
            </div>
          ) : null}
        </li>
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">数据库向量化</span>
              <span className="settings-nav__desc">
                {p.scrapBusy && p.scrapJobMode === 'embed'
                  ? p.scrapPhase || '向量化中…'
                  : '对元库零向量/待嵌条目编码写入 · 增量只补缺 · 全量重嵌'}
              </span>
            </span>
            <span className="makers-manage__status-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onScrapEmbedSync(false, 'embed')}
              >
                {p.scrapBusy && p.scrapJobMode === 'embed'
                  ? p.scrapPct != null
                    ? `${Math.round(p.scrapPct)}%`
                    : '向量化…'
                  : '增量向量化'}
              </button>
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onScrapEmbedSync(true, 'embed')}
              >
                {p.scrapBusy && p.scrapJobMode === 'embed' ? '…' : '全量向量化'}
              </button>
            </span>
          </div>
          {p.scrapJobMode === 'embed' &&
          (p.scrapBusy || p.scrapProgress || p.scrapLog.length > 0) ? (
            <div className="makers-manage__scan-progress" aria-live="polite">
              {p.scrapBusy || p.scrapProgress ? (
                <div
                  className="makers-manage__scan-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={p.scrapPct != null ? Math.round(p.scrapPct) : 0}
                  aria-label="数据库向量化进度"
                >
                  <span
                    style={{
                      width: `${p.scrapPct != null ? p.scrapPct : 0}%`,
                    }}
                  />
                </div>
              ) : null}
              <div className="makers-manage__scan-meta">
                <span>
                  {p.scrapBusy || p.scrapProgress
                    ? p.scrapProgress?.stage === 'embed'
                      ? '编码'
                      : p.scrapProgress?.stage === 'diff'
                        ? '筛选'
                        : p.scrapProgress?.stage === 'done'
                          ? '完成'
                          : '准备'
                    : '已完成'}
                  {p.scrapCountLabel ? ` · ${p.scrapCountLabel}` : ''}
                </span>
                <span className="makers-manage__scan-meta-actions">
                  {p.scrapPct != null && (p.scrapBusy || p.scrapProgress) ? (
                    <span className="makers-manage__scan-pct">
                      {`${Math.round(p.scrapPct)}%`}
                    </span>
                  ) : null}
                  {p.scrapLog.length > 0 ? (
                    <button
                      type="button"
                      className="makers-manage__log-btn"
                      onClick={() => p.setScanLogModal('scrap')}
                    >
                      日志
                    </button>
                  ) : null}
                </span>
              </div>
            </div>
          ) : null}
        </li>
      </ul>
    </>
  );
}
