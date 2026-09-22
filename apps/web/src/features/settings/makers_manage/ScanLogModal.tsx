'use client';

import {
  getScrapLibraryQualityGate,
  getScrapLibraryQualityItems,
} from '@/lib/api';
import { AppCenterModal } from '@/components/ui/AppCenterModal';
import { AutoscrollLogList } from '../AutoscrollLogList';

import type { MakersManagePanelState } from './useMakersManagePanel';

export function ScanLogModalView({ p }: { p: MakersManagePanelState }) {
  return (
      <AppCenterModal
        open={p.scanLogModal != null}
        title={
          p.qualityDetailModal
            ? `${p.qualityDetailModal.label} · 缺口详情`
            : p.scanLogModal === 'strm'
            ? 'STRM 同步日志'
            : p.scanLogModal === 'scrap'
              ? p.scrapJobMode === 'embed'
                ? '数据库向量化日志'
                : p.scrapJobMode === 'meta'
                  ? '同步数据库日志'
                  : '刮削库同步日志'
                : p.scanLogModal === 'actress'
                  ? '女优同步向量日志'
                  : p.scanLogModal === 'nfoOpt'
                    ? 'NFO 优化日志'
                  : p.scanLogModal === 'actressAvatar'
                    ? '女优刮削日志'
              : p.scanLogModal === 'enrich'
                    ? '刮削补齐日志'
                  : '双库扫描日志'
        }
        onClose={() => p.setScanLogModal(null)}
        cardClassName="makers-manage__log-modal"
      >
        {p.qualityDetailModal ? (
          p.qualityDetail ? (
          <div className="makers-manage__quality-detail allow-select">
            <ul className="settings-group">
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">条目总数</span>
                  <span className="settings-kv__val">
                    {p.qualityDetail.total.toLocaleString()}
                  </span>
                </div>
                <div className="settings-kv">
                  <span className="settings-kv__key">向量库 / 空壳</span>
                  <span className="settings-kv__val">
                    {p.qualityDetail.embedTotal.toLocaleString()} /{' '}
                    {p.qualityDetail.shells.toLocaleString()}
                  </span>
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">已齐</span>
                  <span className="settings-kv__val">
                    {p.qualityDetail.done.toLocaleString()}
                  </span>
                </div>
              </li>
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">还剩（任一缺口）</span>
                  <span className="settings-kv__val">
                    {p.qualityDetail.remain.toLocaleString()}
                  </span>
                </div>
              </li>
            </ul>
            <p className="settings-group-label">分项缺口</p>
            <ul className="settings-group">
              {p.qualityDetail.rows.map((row) => (
                <li key={row.label}>
                  <div className="settings-kv">
                    <span className="settings-kv__key">{row.label}</span>
                    <span className="settings-kv__val">
                      {row.value.toLocaleString()}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <p className="settings-group-label settings-group-label--spaced">
              质量门禁抽检
            </p>
            <ul className="settings-group">
              <li>
                <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
                  <span className="settings-nav__main">
                    <span className="settings-kv__key">抽样检查</span>
                    <span className="settings-nav__desc">
                      {p.gateSummary ||
                        '从缺口队列抽 12 条跑 G34 门禁（标题/海报/剧情）'}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="makers-manage__probe-btn"
                    disabled={p.gateBusy}
                    onClick={() => {
                      void (async () => {
                        if (!p.qualityDetailModal) return;
                        p.setGateBusy(true);
                        p.setGateSummary('抽检中…');
                        try {
                          const page = await getScrapLibraryQualityItems({
                            region: p.qualityDetailModal.qualityRegion,
                            kind: 'thin_title',
                            limit: 12,
                          });
                          const items = page.items || [];
                          if (!items.length) {
                            p.setGateSummary('缺口队列为空，跳过抽检');
                            return;
                          }
                          let pass = 0;
                          let fail = 0;
                          const samples: string[] = [];
                          for (const it of items) {
                            try {
                              const g = await getScrapLibraryQualityGate({
                                itemId: String(it.itemId || ''),
                                code: String(it.code || ''),
                                relPath: String(it.relPath || ''),
                              });
                              if (g.ok) pass += 1;
                              else {
                                fail += 1;
                                const reason = (g.hardFail || g.soft || [])
                                  .slice(0, 2)
                                  .join('/');
                                if (samples.length < 3 && it.code) {
                                  samples.push(
                                    `${it.code}${reason ? ` (${reason})` : ''}`,
                                  );
                                }
                              }
                            } catch {
                              fail += 1;
                            }
                          }
                          p.setGateSummary(
                            `抽检 ${items.length}：通过 ${pass} · 未过 ${fail}` +
                              (samples.length
                                ? ` · 例 ${samples.join('、')}`
                                : ''),
                          );
                        } catch (e) {
                          p.setGateSummary(
                            e instanceof Error ? e.message : '抽检失败',
                          );
                        } finally {
                          p.setGateBusy(false);
                        }
                      })();
                    }}
                  >
                    {p.gateBusy ? '…' : '抽检'}
                  </button>
                </div>
              </li>
            </ul>
          </div>
          ) : (
            <p className="makers-manage__log-empty">统计加载中…</p>
          )
        ) : (
        <AutoscrollLogList
          className="makers-manage__scan-log-modal allow-select"
          active={p.scanLogModal != null && !p.qualityDetailModal}
          lines={
            p.scanLogModal === 'strm'
              ? p.strmLog
              : p.scanLogModal === 'scrap'
                ? p.scrapLog
                : p.scanLogModal === 'actress'
                  ? p.actressOptLog
                  : p.scanLogModal === 'nfoOpt'
                    ? p.nfoOptLog
                  : p.scanLogModal === 'actressAvatar'
                    ? p.actressAvatarLog
                    : p.scanLogModal === 'enrich'
                      ? p.enrichLog
                        : p.localIndexLog
          }
        />
        )}
      </AppCenterModal>
  );
}
