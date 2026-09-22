'use client';

import { scrapeJobsLocked } from './helpers';
import type { MakersManagePanelState } from './useMakersManagePanel';

/** NFO 映射修正 */
export function ScrapeHubNfoOpt({ p }: { p: MakersManagePanelState }) {
  const locked = scrapeJobsLocked(p);
  return (
    <>
      <p className="settings-group-label">NFO优化</p>
      <ul className="settings-group makers-manage__rise">
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">映射修正 NFO</span>
              <span className="settings-nav__desc">
                {p.nfoOptBusy
                  ? p.nfoOptPhase || '优化中…'
                  : '用本地标题/女优/标签/片商映射扫一遍磁盘 NFO · 增量仅写有变 · 全量强制覆盖'}
              </span>
            </span>
            <span className="makers-manage__status-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onNfoOptimize(false)}
              >
                {p.nfoOptBusy
                  ? p.nfoOptPct != null
                    ? `${Math.round(p.nfoOptPct)}%`
                    : '优化中…'
                  : '增量优化'}
              </button>
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onNfoOptimize(true)}
              >
                {p.nfoOptBusy ? '…' : '全量优化'}
              </button>
            </span>
          </div>
          {p.nfoOptBusy || p.nfoOptProgress || p.nfoOptLog.length > 0 ? (
            <div className="makers-manage__scan-progress" aria-live="polite">
              {p.nfoOptBusy || p.nfoOptProgress ? (
                <div
                  className="makers-manage__scan-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    p.nfoOptPct != null ? Math.round(p.nfoOptPct) : 0
                  }
                  aria-label="NFO 优化进度"
                >
                  <span
                    style={{
                      width: `${p.nfoOptPct != null ? p.nfoOptPct : 0}%`,
                    }}
                  />
                </div>
              ) : null}
              <div className="makers-manage__scan-meta">
                <span>
                  {p.nfoOptBusy || p.nfoOptProgress
                    ? p.nfoOptProgress?.stage === 'done'
                      ? '完成'
                      : p.nfoOptProgress?.stage === 'write'
                        ? '写入'
                        : p.nfoOptProgress?.stage === 'scan'
                          ? '扫描'
                          : '准备'
                    : '已完成'}
                  {p.nfoOptCountLabel ? ` · ${p.nfoOptCountLabel}` : ''}
                </span>
                <span className="makers-manage__scan-meta-actions">
                  {p.nfoOptLog.length > 0 ? (
                    <button
                      type="button"
                      className="makers-manage__log-btn"
                      onClick={() => p.setScanLogModal('nfoOpt')}
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
