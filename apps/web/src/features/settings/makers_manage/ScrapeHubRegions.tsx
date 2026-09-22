'use client';

import { MAKER_KIND_TABS } from '@/features/makers/makersUi';

import type { EnrichRegionRow } from './types';
import type { MakersManagePanelState } from './useMakersManagePanel';
import { ScrapeHubRegionRow } from './ScrapeHubRegionRow';

/** 六区刮削开关与进度 */
export function ScrapeHubRegions({ p }: { p: MakersManagePanelState }) {
  const regions: EnrichRegionRow[] = p.enrichRegions.length
    ? p.enrichRegions
    : MAKER_KIND_TABS.map((t) => ({
        id: t.id,
        label: t.label,
        enabled: false,
      }));

  return (
    <>
      <p className="settings-group-label">刮削分区</p>
      <ul className="settings-group makers-manage__rise" aria-label="六区刮削开关">
        {regions.map((region) => (
          <ScrapeHubRegionRow key={region.id} p={p} region={region} />
        ))}
      </ul>
    </>
  );
}
