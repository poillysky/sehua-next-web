'use client';

import { useEffect } from 'react';
import { AppShell, TabProvider, TabPane } from '@/shell';
import { HomeScreen } from '@/features/home/HomeScreen';
import { MediaScreen } from '@/features/media/MediaScreen';
import { MakersScreen } from '@/features/makers/MakersScreen';
import { BoardsScreen } from '@/features/boards/BoardsScreen';
import { SettingsScreen } from '@/features/settings/SettingsScreen';
import { registerServiceWorker } from '@/lib/pwa';
import { AuthGate } from '@/providers/AuthGate';
import { DeviceFrame } from '@/components/layout/DeviceFrame';

export default function HomePage() {
  useEffect(() => {
    registerServiceWorker();
  }, []);

  return (
    <AuthGate>
      <DeviceFrame label="资源仓库">
        <TabProvider>
          <AppShell>
            <TabPane>
              <HomeScreen />
            </TabPane>
            <TabPane>
              <MediaScreen />
            </TabPane>
            <TabPane>
              <MakersScreen />
            </TabPane>
            <TabPane>
              <BoardsScreen />
            </TabPane>
            <TabPane>
              <SettingsScreen />
            </TabPane>
          </AppShell>
        </TabProvider>
      </DeviceFrame>
    </AuthGate>
  );
}
