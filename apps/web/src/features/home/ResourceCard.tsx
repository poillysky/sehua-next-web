'use client';

import { useEffect, useState } from 'react';
import { ImageOff } from 'lucide-react';
import type { ResourceItem } from '@/types/resource';
import { formatByteSize, formatDate, parseHighlight } from '@/lib/format';
import { normalizeResourceView } from '@/lib/resourceView';
import {
  cropModeForRegion,
  ensurePosterCropLoaded,
  getPosterCropCached,
  isPortraitCropMode,
  objectFitForCropMode,
  objectPositionForRegion,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import { useCoverObjectPosition } from '@/hooks/useCoverObjectPosition';
import type { PosterCropMode } from '@/lib/api';
import { proxiedCoverUrl } from '@/lib/api';

const LINK_KIND_LABEL: Record<string, string> = {
  magnet: '磁力',
  ed2k: 'ed2k',
  share115: '115',
  '115share': '115',
  unavailable: '占位',
  stub: '占位',
};

function Thumb({
  srcs,
  cropMode,
  fallbackPosition,
  ratio,
}: {
  srcs: string[];
  cropMode?: PosterCropMode;
  fallbackPosition?: string;
  ratio?: string;
}) {
  const [idx, setIdx] = useState(0);
  const [gone, setGone] = useState(false);
  const src = srcs[idx];
  const facePos = useCoverObjectPosition(cropMode, gone ? null : src);
  const objectPosition =
    cropMode === 'face' ? facePos : fallbackPosition || facePos;
  const objectFit = objectFitForCropMode(cropMode);

  if (!srcs.length || gone || !src) {
    return (
      <div
        className="resource-thumb-wrap resource-thumb--empty"
        data-ratio={ratio || 'full'}
        data-crop={isPortraitCropMode(cropMode) ? 'portrait' : 'full'}
        aria-hidden
      >
        <ImageOff size={18} strokeWidth={1.75} />
      </div>
    );
  }
  return (
    <div
      className="resource-thumb-wrap"
      data-ratio={ratio || 'full'}
      data-crop={isPortraitCropMode(cropMode) ? 'portrait' : 'full'}
      aria-hidden
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="resource-thumb"
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        style={{ objectPosition, objectFit }}
        onError={() => {
          if (idx + 1 < srcs.length) setIdx(idx + 1);
          else setGone(true);
        }}
      />
    </div>
  );
}

export function ResourceCard({
  item,
  keywords = [],
  onOpen,
  cropRegion,
}: {
  item: ResourceItem;
  keywords?: string[];
  onOpen: (hash: string) => void;
  /** 七区 id，用于封面 object-position */
  cropRegion?: string;
}) {
  const view = normalizeResourceView(item);
  const title = view.title || view.name || view.hash;
  const srcs = (view.preview_images || [])
    .map((u) => proxiedCoverUrl(u))
    .filter(Boolean);
  const kindLabel = LINK_KIND_LABEL[view.link_kind] || '';
  const sizeText = formatByteSize(view.size);
  const [mode, setMode] = useState<PosterCropMode | undefined>(() =>
    cropRegion ? cropModeForRegion(cropRegion) : undefined,
  );
  const [pos, setPos] = useState(() =>
    cropRegion ? objectPositionForRegion(cropRegion) : 'center top',
  );
  const [ratio, setRatio] = useState(() => getPosterCropCached().ratio || 'full');

  useEffect(() => {
    const sync = () => {
      setMode(cropRegion ? cropModeForRegion(cropRegion) : undefined);
      setPos(cropRegion ? objectPositionForRegion(cropRegion) : 'center top');
      setRatio(getPosterCropCached().ratio || 'full');
    };
    void ensurePosterCropLoaded().then(sync);
    return subscribePosterCrop(sync);
  }, [cropRegion]);

  return (
    <article className="resource-card resource-card--row">
      <button
        type="button"
        className="resource-card__hit"
        onClick={() => onOpen(view.hash)}
      >
        <Thumb
          srcs={srcs}
          cropMode={mode}
          fallbackPosition={pos}
          ratio={ratio}
        />
        <div className="resource-meta">
          <div
            className="resource-title allow-select"
            dangerouslySetInnerHTML={{
              __html: parseHighlight(title, keywords),
            }}
          />
          <div className="resource-foot">
            {sizeText ? (
              <span className="resource-chip resource-chip--size">{sizeText}</span>
            ) : null}
            {kindLabel ? (
              <span className="resource-chip resource-chip--kind">{kindLabel}</span>
            ) : null}
            {view.board_name ? (
              <span className="resource-chip resource-chip--board">{view.board_name}</span>
            ) : null}
            {view.created_at ? (
              <time className="resource-date">{formatDate(view.created_at)}</time>
            ) : null}
          </div>
        </div>
      </button>
    </article>
  );
}
