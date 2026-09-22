'use client';

import { ChevronRight } from 'lucide-react';
import type { MakersManagePanelState } from './useMakersManagePanel';

/** 调度入口 + 刮削产物目录 */
export function ScrapeHubSchedule({ p }: { p: MakersManagePanelState }) {
  return (
    <>
      <p className="settings-group-label">调度</p>
      <ul className="settings-group makers-manage__rise">
        <li>
          <button
            type="button"
            className="settings-nav makers-manage__catalog-row"
            onClick={() => p.setEnrichStrategyOpen(true)}
          >
            <span className="settings-nav__main">
              <span className="settings-nav__title">刮削策略</span>
              <span className="settings-nav__desc">
                增量/覆盖 · 头像模式 · 调度 · 六区数据源
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
      </ul>

      <p className="settings-group-label">刮削产物</p>
      <ul className="settings-group makers-manage__rise">
        <li>
          <div className="settings-nav makers-manage__status">
            <span className="settings-nav__main">
              <span className="settings-nav__title">刮削目录</span>
              <span className="settings-nav__desc allow-select">
                {p.scrapRoot
                  ? `media/${p.scrapRoot} · NFO / 封面`
                  : 'media/scrap-library · NFO / 封面'}
              </span>
            </span>
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={p.strmBusy || p.localIndexBusy || p.scrapBusy || p.enrichBusy}
              onClick={() => void p.openScrapBrowse()}
            >
              选择
            </button>
          </div>
        </li>
      </ul>
    </>
  );
}
