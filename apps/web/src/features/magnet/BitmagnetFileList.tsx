'use client';

import type { MagnetHit } from '@/lib/api';
import { TorrentFileList } from './TorrentFileList';

/** Bitmagnet 文件列表（共用图标树） */
export function BitmagnetFileList({
  torrent,
  highlight,
  max = -1,
  onMore,
  coreOnly = false,
}: {
  torrent: MagnetHit;
  highlight?: string | string[];
  max?: number;
  onMore?: () => void;
  coreOnly?: boolean;
}) {
  const hintText = [torrent.name, torrent.title].filter(Boolean).join('\n');
  return (
    <TorrentFileList
      files={torrent.files || []}
      filesCount={torrent.files_count ?? torrent.fileCount}
      highlight={highlight}
      max={max}
      onMore={onMore}
      coreOnly={coreOnly}
      hintText={hintText}
    />
  );
}
