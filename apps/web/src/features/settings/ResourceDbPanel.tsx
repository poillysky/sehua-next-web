'use client';

import { PostgresDbPanel, type PostgresDbSpec } from './PostgresDbPanel';
import type { StatusReporter } from '@/hooks/usePanelAction';
import {
  createResourceDbEmbedIndex,
  exportResourceDbBackup,
  getResourceDb,
  getResourceDbEmbedStats,
  getResourceDbEmbedStatus,
  listResourceDbBackups,
  putResourceDb,
  startResourceDbEmbed,
  stopResourceDbEmbed,
  testResourceDb,
  uploadImportResourceDbBackup,
} from '@/lib/api';

const RESOURCE_DB_SPEC: PostgresDbSpec = {
  title: '色花资源库',
  fallbackPort: '5435',
  fallbackDatabase: 'ed2k',
  dirHint: 'backups/resource-db/',
  footnote: '普通用户仅可查看连接状态。色花资源库与启动元库分开配置。',
  get: getResourceDb,
  put: putResourceDb,
  test: testResourceDb,
  listBackups: listResourceDbBackups,
  exportBackup: exportResourceDbBackup,
  uploadImportBackup: uploadImportResourceDbBackup,
  getEmbedStats: getResourceDbEmbedStats,
  getEmbedStatus: getResourceDbEmbedStatus,
  startEmbed: startResourceDbEmbed,
  stopEmbed: stopResourceDbEmbed,
  createEmbedIndex: createResourceDbEmbedIndex,
};

export function ResourceDbPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: StatusReporter;
}) {
  return (
    <PostgresDbPanel spec={RESOURCE_DB_SPEC} onBack={onBack} onStatus={onStatus} />
  );
}
