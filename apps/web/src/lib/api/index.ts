/**
 * API 客户端 barrel：按域拆分后的统一出口。
 *
 * 现有 `from '@/lib/api'` 经 lib/api.ts（重导出壳）转发到本文件，路径零改动。
 */

export * from './client';
export * from './auth';
export * from './resource';
export * from './magnet';
export * from './settings-db';
export * from './settings';
export * from './ai';
export * from './scrap-embed';
export * from './scrap-jobs';
export * from './scrap-enrich';
export * from './scrap-enrich-control';
export * from './scrap-subtitle';
export * from './scrap-library';
export * from './ai-chat';
export * from './p115';
export * from './media';
export * from './makers';
export * from './prefix';
export * from './sources';
