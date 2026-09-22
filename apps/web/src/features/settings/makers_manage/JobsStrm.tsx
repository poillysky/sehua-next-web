'use client';

import { ChevronRight } from 'lucide-react';
import { AppMsg } from '@/components/ui/AppMsg';

import type { MakersManagePanelState } from './useMakersManagePanel';

export function JobsStrm({ p }: { p: MakersManagePanelState }) {
  return (
        <div className="makers-manage makers-manage--detail">
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">双库扫描</span>
                  <span className="settings-nav__desc">
                    {p.localIndexBusy
                      ? p.localIndexPhase || '扫描中…'
                      : 'Sehua · Bitmagnet 合并去脏 · 扫完删骨架按目录重建进向量'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={p.localIndexBusy || p.catalogBusy || p.strmBusy || p.scrapBusy}
                  onClick={() => void p.onLocalIndexScan()}
                >
                  {p.localIndexBusy
                    ? p.localIndexPct != null
                      ? `${Math.round(p.localIndexPct)}%`
                      : '扫描中…'
                    : '开始扫描'}
                </button>
              </div>
              {p.localIndexBusy || p.localIndexLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {p.localIndexBusy || p.localIndexProgress ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={
                        p.localIndexPct != null ? Math.round(p.localIndexPct) : 0
                      }
                      aria-label="双库扫描进度"
                    >
                      <span
                        style={{
                          width: `${p.localIndexPct != null ? p.localIndexPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {p.localIndexBusy || p.localIndexProgress
                        ? p.localIndexProgress?.stage === 'sehua'
                          ? '色花堂'
                          : p.localIndexProgress?.stage === 'bitmagnet'
                            ? 'Bitmagnet'
                            : p.localIndexProgress?.stage === 'write'
                              ? '写回'
                              : p.localIndexProgress?.stage === 'skeleton'
                                ? '番号骨架'
                              : p.localIndexProgress?.stage === 'done'
                                ? '完成'
                                : '准备'
                        : '已完成'}
                      {p.localIndexCountLabel ? ` · ${p.localIndexCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {p.localIndexPct != null &&
                      (p.localIndexBusy || p.localIndexProgress) ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(p.localIndexPct)}%`}
                        </span>
                      ) : null}
                      {p.localIndexLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => p.setScanLogModal('local')}
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

          <p className="settings-group-label">本地 STRM</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">输出目录</span>
                  <span className="settings-nav__desc allow-select">
                    {p.strmRoot
                      ? `media/${p.strmRoot}`
                      : 'media/strm-library（默认）'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={p.strmBusy || p.localIndexBusy || p.scrapBusy}
                  onClick={() => void p.openStrmBrowse()}
                >
                  选择
                </button>
              </div>
            </li>
            <li>
              <div className="settings-nav makers-manage__status">
                <span className="settings-nav__main">
                  <span className="settings-nav__title">同步本地文件夹</span>
                  <span className="settings-nav__desc">
                    {p.strmBusy
                      ? p.strmPhase || '同步中…'
                      : p.strmPhase === 'interrupted'
                        ? p.strmProgress?.label ||
                          '已中断，再点一次会跳过已有文件继续'
                        : '按六区少补多删 .strm · 只写本地文件夹，不碰向量库'}
                  </span>
                </span>
                <button
                  type="button"
                  className="makers-manage__probe-btn"
                  disabled={p.strmBusy || p.localIndexBusy || p.catalogBusy || p.scrapBusy}
                  onClick={() => void p.onStrmSync()}
                >
                  {p.strmBusy
                    ? p.strmPct != null
                      ? `${Math.round(p.strmPct)}%`
                      : '同步中…'
                    : p.strmPhase === 'interrupted'
                      ? '继续'
                      : '开始同步'}
                </button>
              </div>
              {p.strmBusy || p.strmLog.length > 0 ? (
                <div
                  className="makers-manage__scan-progress"
                  aria-live="polite"
                >
                  {p.strmBusy ? (
                    <div
                      className="makers-manage__scan-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={p.strmPct != null ? Math.round(p.strmPct) : 0}
                      aria-label="本地同步进度"
                    >
                      <span
                        style={{
                          width: `${p.strmPct != null ? p.strmPct : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  <div className="makers-manage__scan-meta">
                    <span>
                      {p.strmBusy
                        ? p.strmProgress?.stage === 'write'
                          ? '写入'
                          : p.strmProgress?.stage === 'prune'
                            ? '清理'
                          : p.strmProgress?.stage === 'done'
                            ? '完成'
                            : '准备'
                        : '已完成'}
                      {p.strmCountLabel ? ` · ${p.strmCountLabel}` : ''}
                    </span>
                    <span className="makers-manage__scan-meta-actions">
                      {p.strmPct != null && p.strmBusy ? (
                        <span className="makers-manage__scan-pct">
                          {`${Math.round(p.strmPct)}%`}
                        </span>
                      ) : null}
                      {p.strmLog.length > 0 ? (
                        <button
                          type="button"
                          className="makers-manage__log-btn"
                          onClick={() => p.setScanLogModal('strm')}
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

          <ul className="settings-group" aria-label="六区前缀番号">
            {p.catalogRegionRows.map((reg) => (
              <li key={reg.id}>
                <button
                  type="button"
                  className="settings-nav makers-manage__catalog-row"
                  disabled={p.catalogBusy || p.localIndexBusy || p.strmBusy}
                  onClick={() => void p.openCatalogRegion(reg.id, reg.label)}
                >
                <span className="settings-nav__main">
                    <span className="settings-nav__title">{reg.label}</span>
                  <span className="settings-nav__desc">
                      {p.formatCatalogRegionDesc(reg)}
                  </span>
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

          <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
            {p.msg}
          </AppMsg>
        </div>
  );
}
