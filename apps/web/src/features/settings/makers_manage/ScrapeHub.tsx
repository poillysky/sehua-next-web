'use client';

import { AppMsg } from '@/components/ui/AppMsg';

import type { MakersManagePanelState } from './useMakersManagePanel';
import { ScrapeHubSchedule } from './ScrapeHubSchedule';
import { ScrapeHubRegions } from './ScrapeHubRegions';
import { ScrapeHubNfoOpt } from './ScrapeHubNfoOpt';
import { ScrapeHubEmbed } from './ScrapeHubEmbed';
import { ScrapeHubActress } from './ScrapeHubActress';

export function ScrapeHub({ p }: { p: MakersManagePanelState }) {
  return (
    <div className="makers-manage makers-manage--detail">
      <ScrapeHubSchedule p={p} />
      <ScrapeHubRegions p={p} />
      <ScrapeHubNfoOpt p={p} />
      <ScrapeHubEmbed p={p} />
      <ScrapeHubActress p={p} />

      <AppMsg allowSelect onDismiss={() => p.setMsg('')}>
        {p.msg}
      </AppMsg>
    </div>
  );
}
