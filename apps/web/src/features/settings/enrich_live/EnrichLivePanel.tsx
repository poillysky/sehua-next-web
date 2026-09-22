'use client';

import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import type { ScrapLibraryEnrichJobStatus } from '@/lib/api';
import { EnrichItemDetail } from './EnrichItemDetail';
import { EnrichLiveMonitor } from './EnrichLiveMonitor';
import { EnrichLiveQueueList } from './EnrichLiveQueueList';
import { EnrichLiveSearchBar } from './EnrichLiveSearchBar';
import { EnrichLiveTabs } from './EnrichLiveTabs';
import { EnrichLiveToolbar } from './EnrichLiveToolbar';
import { useEnrichLivePanel } from './useEnrichLivePanel';

export function EnrichLivePanel({
  regionId,
  label,
  onBack,
  onStatus,
  initialStatus = null,
  initialLogs = [],
}: {
  regionId: string;
  label: string;
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
  initialStatus?: ScrapLibraryEnrichJobStatus | null;
  initialLogs?: string[];
}) {
  const live = useEnrichLivePanel({
    regionId,
    label,
    onBack,
    onStatus,
    initialStatus,
    initialLogs,
  });

  return (
    <AppPush
      title={
        live.selectedDetail?.code
          ? `${live.selectedDetail.code} · 详情`
          : `${label} · 刮削`
      }
      onBack={
        live.selectedKey
          ? () => {
              live.setSelectedKey(null);
              live.setDbDetail(null);
            }
          : onBack
      }
      scrollKey={
        live.selectedDetail?.code
          ? `enrich-live-detail-${live.selectedDetail.code}`
          : `enrich-live-${regionId}`
      }
      scrollMode="top"
      scrollPin="once"
      right={
        <EnrichLiveToolbar
          mode={live.selectedKey ? 'detail' : 'list'}
          running={Boolean(live.st?.running)}
          stopping={live.stopping}
          clearing={live.clearing}
          queueScanning={live.queueScanning}
          queueScanHere={Boolean(live.queueScanHere)}
          retryingFails={live.retryingFails}
          retryingSofts={live.retryingSofts}
          rescraping={live.rescraping}
          onPause={() => void live.onPause()}
          onClearAndScan={() => void live.onClearAndScan()}
          onRescrape={() => void live.onRescrapeSelected()}
        />
      }
    >
      <div
        className={cn(
          'makers-manage makers-manage--detail enrich-live',
          live.hydrated && 'enrich-live--ready',
        )}
      >
        {live.selectedDetail ? (
          <EnrichItemDetail
            detail={live.selectedDetail}
            regionId={regionId}
          />
        ) : (
          <>
        <div className="enrich-live__chrome">
              <EnrichLiveSearchBar
                codeQuery={live.codeQuery}
                onCodeQueryChange={live.setCodeQuery}
                searchActive={live.searchActive}
                searching={live.searching}
                clearing={live.clearing}
                onSubmit={() => void live.runCodeSearch()}
                onClear={() => live.clearCodeSearch()}
              />
              <EnrichLiveTabs
                tab={live.tab}
                tabCounts={live.tabCounts}
                searchActive={live.searchActive}
                onSelectTab={live.selectTab}
              />
          </div>
            <div className="enrich-live__pane" ref={live.queuePaneRef}>
              {!live.searchActive && live.tab === 'running' ? (
                <EnrichLiveMonitor
                  running={Boolean(live.st?.running)}
                  hasCheckpoint={live.hasCheckpoint}
                  monitor={live.monitor}
                  runningViewRows={live.runningViewRows}
                  hasRunningRows={live.hasRunningRows}
                  liveRunningPool={live.liveRunningPool}
                  queueItems={live.queueItems}
                  onOpenRow={(key) => {
                    live.setDbDetail(null);
                    live.setSelectedKey(key);
                  }}
                />
              ) : (
                <EnrichLiveQueueList
                  tab={live.tab}
                  searchActive={live.searchActive}
                  searching={live.searching}
                  searchCode={live.searchCode}
                  scanTip={live.scanTip || ''}
                  tabCounts={live.tabCounts}
                  filteredQueue={live.filteredQueue}
                  queuePaging={live.queuePaging}
                  queueScanning={live.queueScanning}
                  hydrated={live.hydrated}
                  running={Boolean(live.st?.running)}
                  retryingFails={live.retryingFails}
                  retryingSofts={live.retryingSofts}
                  clearing={live.clearing}
                  onRetryFails={() => void live.onRetryFails()}
                  onRetrySofts={() => void live.onRetrySofts()}
                  showQueuePager={live.showQueuePager}
                  pageShown={live.pageShown}
                  queuePageTotal={live.queuePageTotal}
                  queueTotalForTab={live.queueTotalForTab}
                  goQueuePage={live.goQueuePage}
                  onOpenRow={(key) => {
                    live.setDbDetail(null);
                    live.setSelectedKey(key);
                  }}
                />
          )}
        </div>
          </>
        )}

        {live.msg &&
        !live.queueScanning &&
        !live.queueScanHere &&
        !live.clearing ? (
          <AppMsg tone="info">{live.msg}</AppMsg>
        ) : null}
      </div>
    </AppPush>
  );
}
