'use client';

import { ChevronRight } from 'lucide-react';
import { AppMsg } from '@/components/ui/AppMsg';

import type { MakersManagePanelState } from './useMakersManagePanel';

export function CatalogHome({ p }: { p: MakersManagePanelState }) {
  return (
        <div className="makers-manage">
          <p className="settings-group-label">前缀目录</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={p.openCatalogRegions}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">六区目录</span>
                  <span className="settings-nav__desc">
                    {p.catalogSummary
                      ? `${p.catalogSummary.prefix_total} 前缀 · ${p.catalogSummary.scrap_prefix_total ?? 0} 有片 · ${p.catalogSummary.code_total} 番号`
                      : '前缀与真实番号'}
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

          <p className="settings-group-label">采集</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={() => p.setSourcesOpen(true)}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">数据源</span>
                  <span className="settings-nav__desc">
                    MDCS 全站目录 · 启用 / 地址 / 测链
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

          <p className="settings-group-label">刮削</p>
          <ul className="settings-group makers-manage__rise">
            <li>
              <button
                type="button"
                className="settings-nav makers-manage__catalog-row"
                onClick={() => {
                  p.setMsg('');
                  p.setScrapHubOpen(true);
                }}
              >
                <span className="settings-nav__main">
                  <span className="settings-nav__title">刮削库</span>
                  <span className="settings-nav__desc">
                    {p.scrapBusy
                      ? p.scrapPhase ||
                        (p.scrapJobMode === 'embed'
                          ? '向量化中…'
                          : p.scrapJobMode === 'meta'
                            ? '同步数据库中…'
                            : '向量入库中…')
                      : p.enrichBusy
                        ? p.enrichPhase || '刮削补齐中…'
                        : p.actressAvatarBusy
                          ? p.actressAvatarPhase || '女优刮削中…'
                          : '产物目录 · 刮削补齐 · 同步库 / 向量化'}
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

          <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
            {p.msg}
          </AppMsg>
        </div>
  );
}
