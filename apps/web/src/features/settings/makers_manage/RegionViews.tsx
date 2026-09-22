'use client';

import { ChevronRight } from 'lucide-react';
import { AppMsg } from '@/components/ui/AppMsg';
import type { MakersManagePanelState } from './useMakersManagePanel';

export function RegionViews({
  level,
  p,
}: {
  level: 'prefix' | 'region';
  p: MakersManagePanelState;
}) {
  if (level === 'prefix') {
    return (
        <div className="makers-manage makers-manage--detail">
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">厂牌</span>
                <span className="settings-kv__val allow-select">
                  {(p.catalogDetail?.maker || '')
                    .split('/')
                    .map((s) => s.trim())
                    .filter(Boolean)
                    .slice(0, 2)
                    .join(' / ') || (p.catalogBusy ? '…' : '—')}
                </span>
              </div>
            </li>
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">番号</span>
                <span className="settings-kv__val">
                  {p.catalogBusy
                    ? '…'
                    : `${p.catalogDetail?.code_count ?? 0} 条`}
                </span>
              </div>
            </li>
          </ul>
          <p className="settings-group-label">真实番号</p>
          {(p.catalogDetail?.codes || []).length ? (
            <>
              <ul className="settings-group makers-manage__codes">
                {(p.catalogDetail?.codes || []).map((code) => (
                  <li key={code}>
                    <div className="settings-kv">
                      <span className="settings-kv__key allow-select makers-manage__code">
                        {code}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
              {p.codePages > 1 ? (
                <div className="media-chart__pager">
                  <button
                    type="button"
                    className="media-chart__page-btn"
                    disabled={p.catalogBusy || p.catalogCodePage <= 1}
                    onClick={() => {
                      if (!p.catalogNav || p.catalogNav.level !== 'prefix') return;
                      void p.loadCatalogCodes(
                        p.catalogNav.regionId,
                        p.catalogNav.prefix,
                        p.catalogCodePage - 1,
                      );
                    }}
                  >
                    上一页
                  </button>
                  <span className="media-chart__page-meta">
                    {p.catalogCodePage} / {p.codePages}
                  </span>
                  <button
                    type="button"
                    className="media-chart__page-btn"
                    disabled={p.catalogBusy || p.catalogCodePage >= p.codePages}
                    onClick={() => {
                      if (!p.catalogNav || p.catalogNav.level !== 'prefix') return;
                      void p.loadCatalogCodes(
                        p.catalogNav.regionId,
                        p.catalogNav.prefix,
                        p.catalogCodePage + 1,
                      );
                    }}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <p className="makers-manage__sites-empty">
              {p.catalogBusy ? '加载中…' : '暂无已验证番号'}
            </p>
          )}
          <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
            {p.msg}
          </AppMsg>
        </div>
    );
  }
  return (
        <div className="makers-manage makers-manage--detail">
          <p className="settings-group-label">前缀</p>
          {p.catalogPrefixes.length ? (
            <ul className="settings-group">
              {p.catalogPrefixes.map((row) => (
                <li key={row.prefix}>
                  <button
                    type="button"
                    className="settings-nav makers-manage__catalog-row"
                    disabled={p.catalogBusy}
                    onClick={() => {
                      if (!p.catalogNav || p.catalogNav.level !== 'region') return;
                      void p.openCatalogPrefix(
                        p.catalogNav.regionId,
                        p.catalogNav.label,
                        row.prefix,
                      );
                    }}
                  >
                    <span className="settings-nav__main">
                      <span className="settings-nav__title allow-select">
                        {row.prefix}
                      </span>
                      <span className="settings-nav__desc">
                        {row.maker
                          ? `${row.maker.split('/').map((s) => s.trim()).filter(Boolean).slice(0, 2).join(' / ')} · ${row.code_count} 番号`
                          : `${row.code_count} 番号`}
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
          ) : (
            <p className="makers-manage__sites-empty">
              {p.catalogBusy ? '加载中…' : '暂无前缀'}
            </p>
          )}
          <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
            {p.msg}
          </AppMsg>
        </div>
  );
}
