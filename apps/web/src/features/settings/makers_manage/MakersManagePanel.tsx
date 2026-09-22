'use client';

import { AppPush } from '@/components/ui/AppPush';
import { ScrapeSourcesSection } from '@/features/settings/ScrapeSourcesSection';
import { EnrichStrategyPanel } from '@/features/settings/EnrichStrategyPanel';
import { EnrichLivePanel } from '@/features/settings/EnrichLivePanel';
import { normalizeEnrichFillMode } from './helpers';
import { useMakersManagePanel } from './useMakersManagePanel';
import { StrmBrowseView } from './StrmBrowseView';
import { ScrapeHub } from './ScrapeHub';
import { RegionViews } from './RegionViews';
import { JobsStrm } from './JobsStrm';
import { CatalogHome } from './CatalogHome';
import { ScanLogModalView } from './ScanLogModal';

export function MakersManagePanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const p = useMakersManagePanel({ onBack, onStatus });

  if (p.sourcesOpen) {
    return (
      <ScrapeSourcesSection
        onBack={() => p.setSourcesOpen(false)}
        onStatus={p.onStatus}
      />
    );
  }

  if (p.enrichStrategyOpen) {
    return (
      <EnrichStrategyPanel
        onBack={() => p.setEnrichStrategyOpen(false)}
        onStatus={p.onStatus}
        onSaved={(saved) => {
          p.setEnrichMode(normalizeEnrichFillMode(saved.fillMode));
          p.setActressAvatarMode(
            saved.actressAvatarMode === 'overwrite'
              ? 'overwrite'
              : 'incremental',
          );
        }}
      />
    );
  }

  if (p.enrichLive) {
    return (
      <EnrichLivePanel
        regionId={p.enrichLive.regionId}
        label={p.enrichLive.label}
        initialStatus={p.enrichLive.initialStatus}
        initialLogs={p.enrichLive.initialLogs}
        onBack={() => p.setEnrichLive(null)}
        onStatus={p.onStatus}
      />
    );
  }

  if (p.strmBrowseOpen) {
    return <StrmBrowseView p={p} />;
  }

  return (
    <AppPush
      title={p.catalogPushTitle}
      onBack={p.catalogPushBack}
      skipEnterAnimation={Boolean(p.catalogNav) || p.scrapHubOpen}
      scrollKey={p.catalogScrollKey}
    >
      {p.scrapHubOpen ? (
        <ScrapeHub p={p} />
      ) : p.catalogNav?.level === 'prefix' ? (
        <RegionViews level="prefix" p={p} />
      ) : p.catalogNav?.level === 'region' ? (
        <RegionViews level="region" p={p} />
      ) : p.catalogNav?.level === 'regions' ? (
        <JobsStrm p={p} />
      ) : (
        <CatalogHome p={p} />
      )}

      <ScanLogModalView p={p} />
    </AppPush>
  );
}
