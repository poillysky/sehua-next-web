'use client';

export type StatusReporter = (text: string, tone: 'ok' | 'warn' | 'mute') => void;

export const CODES_PAGE_SIZE = 50;

export type ScanLogModal =
  | 'local'
  | 'strm'
  | 'scrap'
  | 'actress'
  | 'nfoOpt'
  | 'actressAvatar'
  | 'enrich'
  | { qualityRegion: string; label: string }
  | null;

export type CatalogNav =
  | { level: 'regions' }
  | { level: 'region'; regionId: string; label: string }
  | {
      level: 'prefix';
      regionId: string;
      regionLabel: string;
      prefix: string;
    };

export type EnrichRegionRow = { id: string; label: string; enabled: boolean };
