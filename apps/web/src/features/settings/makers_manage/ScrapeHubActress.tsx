'use client';

import { scrapeJobsLocked } from './helpers';
import type { MakersManagePanelState } from './useMakersManagePanel';

/** 女优元数据/头像刮削 + 向量名对齐 */
export function ScrapeHubActress({ p }: { p: MakersManagePanelState }) {
  const locked = scrapeJobsLocked(p);
  return (
    <>
      <p className="settings-group-label">女优</p>
      <ul
        className="settings-group makers-manage__rise"
        aria-label="女优元数据与头像"
      >
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">
                刮削女优元数据和头像
              </span>
              <span className="settings-nav__desc">
                {p.actressAvatarBusy
                  ? p.actressAvatarPhase || '刮削中…'
                  : '从向量库取女优名 · 头像/资料落本地与 Meta · 增量跳过已有 · 全量覆盖'}
              </span>
            </span>
            <span className="makers-manage__status-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onActressAvatarScrape(false)}
              >
                {p.actressAvatarBusy
                  ? typeof p.actressAvatarProgress?.percent === 'number'
                    ? `${Math.round(p.actressAvatarProgress.percent)}%`
                    : '刮削中…'
                  : '增量刮削'}
              </button>
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onActressAvatarScrape(true)}
              >
                {p.actressAvatarBusy ? '…' : '全量覆盖'}
              </button>
            </span>
          </div>
          {p.actressAvatarBusy ||
          p.actressAvatarProgress ||
          p.actressAvatarLog.length > 0 ? (
            <div
              className="makers-manage__scan-progress makers-manage__scan-progress--meta-first"
              aria-live="polite"
            >
              <div className="makers-manage__scan-meta">
                <span>
                  {p.actressAvatarBusy || p.actressAvatarProgress
                    ? p.actressAvatarProgress?.stage === 'done'
                      ? '完成'
                      : p.actressAvatarProgress?.stage === 'download'
                        ? '下载头像'
                        : p.actressAvatarProgress?.stage === 'bio'
                          ? '补资料'
                          : p.actressAvatarProgress?.stage === 'embed'
                            ? '写向量'
                            : p.actressAvatarProgress?.stage === 'scan'
                              ? '索引'
                              : '准备'
                    : '已完成'}
                  {typeof p.actressAvatarProgress?.done === 'number' &&
                  typeof p.actressAvatarProgress?.total === 'number' &&
                  p.actressAvatarProgress.total > 0
                    ? ` · ${p.actressAvatarProgress.done.toLocaleString()} / ${p.actressAvatarProgress.total.toLocaleString()}`
                    : ''}
                </span>
                <span className="makers-manage__scan-meta-actions">
                  {p.actressAvatarLog.length > 0 ? (
                    <button
                      type="button"
                      className="makers-manage__log-btn"
                      onClick={() => p.setScanLogModal('actressAvatar')}
                    >
                      日志
                    </button>
                  ) : null}
                </span>
              </div>
              {p.actressAvatarBusy || p.actressAvatarProgress ? (
                <div
                  className="makers-manage__scan-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    typeof p.actressAvatarProgress?.percent === 'number'
                      ? Math.round(p.actressAvatarProgress.percent)
                      : 0
                  }
                  aria-label="女优刮削进度"
                >
                  <span
                    style={{
                      width: `${
                        typeof p.actressAvatarProgress?.percent === 'number'
                          ? p.actressAvatarProgress.percent
                          : 0
                      }%`,
                    }}
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </li>
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">对齐向量库女优名</span>
              <span className="settings-nav__desc">
                {p.actressOptBusy
                  ? p.actressOptPhase || '对齐中…'
                  : '只改标题「女优：」标准名并重嵌 · 不含头像/资料 · 增量跳过已对齐'}
              </span>
            </span>
            <span className="makers-manage__status-actions">
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onActressOptimize(false)}
              >
                {p.actressOptBusy
                  ? p.actressOptPct != null
                    ? `${Math.round(p.actressOptPct)}%`
                    : '对齐中…'
                  : '增量对齐'}
              </button>
              <button
                type="button"
                className="makers-manage__probe-btn"
                disabled={locked}
                onClick={() => void p.onActressOptimize(true)}
              >
                {p.actressOptBusy ? '…' : '全量重嵌'}
              </button>
            </span>
          </div>
          {p.actressOptBusy ||
          p.actressOptProgress ||
          p.actressOptLog.length > 0 ? (
            <div className="makers-manage__scan-progress" aria-live="polite">
              {p.actressOptBusy || p.actressOptProgress ? (
                <div
                  className="makers-manage__scan-bar"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    p.actressOptPct != null ? Math.round(p.actressOptPct) : 0
                  }
                  aria-label="女优向量同步进度"
                >
                  <span
                    style={{
                      width: `${p.actressOptPct != null ? p.actressOptPct : 0}%`,
                    }}
                  />
                </div>
              ) : null}
              <div className="makers-manage__scan-meta">
                <span>
                  {p.actressOptBusy || p.actressOptProgress
                    ? p.actressOptProgress?.stage === 'done'
                      ? '完成'
                      : p.actressOptProgress?.stage === 'embed'
                        ? '重嵌'
                        : p.actressOptProgress?.stage === 'diff'
                          ? '比对'
                          : p.actressOptProgress?.stage === 'scan'
                            ? '扫描'
                            : '准备'
                    : '已完成'}
                  {p.actressOptCountLabel ? ` · ${p.actressOptCountLabel}` : ''}
                </span>
                <span className="makers-manage__scan-meta-actions">
                  {p.actressOptLog.length > 0 ? (
                    <button
                      type="button"
                      className="makers-manage__log-btn"
                      onClick={() => p.setScanLogModal('actress')}
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
