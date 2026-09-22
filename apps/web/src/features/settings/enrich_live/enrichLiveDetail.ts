'use client';

import type { Dispatch, SetStateAction } from 'react';
import {
  getScrapLibraryEnrichQueueLog,
  listScrapLibraryEmbedItems,
  type ScrapLibraryEnrichCurrent,
  type ScrapLibraryEnrichQueueItem,
} from '@/lib/api';
import { ensurePosterField, fieldsFromSourceText } from './cover';
import { rowKey, rowStatus } from './queueFormat';
import { displayHitSource } from './sourceMeta';

export type EnrichLiveDetailHydrateDeps = {
  regionId: string;
  selectedRow: ScrapLibraryEnrichQueueItem | ScrapLibraryEnrichCurrent | null;
  setQueueItems: Dispatch<SetStateAction<ScrapLibraryEnrichQueueItem[]>>;
  setDbDetail: Dispatch<SetStateAction<ScrapLibraryEnrichCurrent | null>>;
};

/** 成功/失败点进详情：优先队列表已落库字段；空壳再从向量库补。Call in useEffect. */
export function attachEnrichLiveDetailHydrate(d: EnrichLiveDetailHydrateDeps) {
  const { regionId, selectedRow, setQueueItems, setDbDetail } = d;
  if (!selectedRow) return;
  const stt = rowStatus(selectedRow.status);
  if (stt !== 'done' && stt !== 'fail') return;
  const code = String(selectedRow.code || '').trim();
  const iid = String(selectedRow.itemId || '').trim();
  if (!code && !iid) return;

  // 已有带选用源的字段 / 源耗时：不必再打向量库
  const hasRichFields = (selectedRow.fields || []).some(
    (f) => String(f.source || '').trim().length > 0,
  );
  if (
    hasRichFields ||
    (selectedRow.sourceTimings || []).length > 0 ||
    ((selectedRow.fields || []).length > 0 &&
      displayHitSource(selectedRow.source))
  ) {
    return;
  }

  let alive = true;
  void (async () => {
    try {
      // 按番号拉一条：服务端会对空壳做 NFO 回填（比整页 limit=80 更稳）
      const page = await getScrapLibraryEnrichQueueLog({
        region: regionId,
        code: code || undefined,
        limit: 8,
      });
      if (!alive) return;
      const hitQ =
        (page.items || []).find(
          (it) =>
            (iid && it.itemId === iid) ||
            (code &&
              String(it.code || '').toUpperCase() === code.toUpperCase()),
        ) || null;
      if (hitQ && (hitQ.fields || []).length > 0) {
        const merged = {
          ...selectedRow,
          ...hitQ,
          fields: hitQ.fields,
          sourceTimings: hitQ.sourceTimings || selectedRow.sourceTimings,
          detailTitle: hitQ.detailTitle || selectedRow.detailTitle,
          posterDownloaded:
            typeof hitQ.posterDownloaded === 'boolean'
              ? hitQ.posterDownloaded
              : selectedRow.posterDownloaded,
          vectorSynced:
            typeof hitQ.vectorSynced === 'boolean'
              ? hitQ.vectorSynced
              : selectedRow.vectorSynced,
        };
        setQueueItems((prev) =>
          prev.map((r) =>
            rowKey(r) === rowKey(selectedRow) ? { ...r, ...merged } : r,
          ),
        );
        setDbDetail({
          code: merged.code || code,
          itemId: merged.itemId || iid,
          detailTitle: merged.detailTitle || '',
          status: merged.status,
          fields: merged.fields,
          posterDownloaded: merged.posterDownloaded,
          vectorSynced: merged.vectorSynced,
          vectorSkipped: merged.vectorSkipped,
          // 保留 scan 供向量文案判断；命中源展示仍走 displayHitSource
          source: merged.source || selectedRow.source,
          sourceTimings: merged.sourceTimings,
          gaps: merged.gaps,
          error: merged.error,
        });
        return;
      }

      if ((selectedRow.fields || []).length > 0) return;

      const pageEmbed = await listScrapLibraryEmbedItems({
        q: code || iid,
        limit: 8,
      });
      if (!alive) return;
      const hit =
        (pageEmbed.items || []).find(
          (it) =>
            (iid && it.itemId === iid) ||
            (code &&
              String(it.code || '').toUpperCase() === code.toUpperCase()),
        ) || (pageEmbed.items || [])[0];
      if (!hit) return;
      const src = String(hit.sourceText || '');
      setDbDetail({
        code: hit.code || code,
        itemId: hit.itemId || iid,
        detailTitle: hit.title || selectedRow.detailTitle || '',
        status: selectedRow.status,
        fields: ensurePosterField(fieldsFromSourceText(src), {
          posterDownloaded: Boolean(hit.posterApi || hit.thumbApi),
        }),
        // 仅补字段展示；不要把「库里有向量行」当成「本步已同步」
        vectorSynced: selectedRow.vectorSkipped
          ? false
          : selectedRow.vectorSynced,
        vectorSkipped: selectedRow.vectorSkipped,
        posterDownloaded: Boolean(hit.posterApi || hit.thumbApi),
        source: displayHitSource(selectedRow.source) || undefined,
        sourceTimings: selectedRow.sourceTimings,
      });
    } catch {
      /* ignore */
    }
  })();
  return () => {
    alive = false;
  };
}
