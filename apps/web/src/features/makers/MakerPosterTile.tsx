'use client';

import { useEffect, useState } from 'react';
import { CroppedCoverImg } from '@/components/cover/CroppedCoverImg';
import { scrapeExportFileUrl } from '@/lib/api';
import {
  ensurePosterCropLoaded,
  frameAspectForCropMode,
  getPosterCropCached,
  isPortraitCropMode,
  cropModeForRegion,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import { prefixHasCover, type MakerFsPrefixCover } from '@/lib/makerFsUi';

export type MakerPosterTileItem = MakerFsPrefixCover & {
  key: string;
  label: string;
  sub?: string;
  title?: string;
  onClick: () => void;
};

function useRegionPosterFrame(regionId: string) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setTick((n) => n + 1));
  }, []);
  void tick;
  const cropMode = cropModeForRegion(regionId);
  return {
    tileAspect: frameAspectForCropMode(cropMode, getPosterCropCached().ratio),
    gridCols: isPortraitCropMode(cropMode) ? '3' : '2',
  };
}

function PosterCover({
  cover,
  label,
  regionId,
  loading,
}: {
  cover: MakerFsPrefixCover;
  label: string;
  regionId: string;
  loading: 'lazy' | 'eager';
}) {
  const local = String(cover.posterLocal || '').trim()
    ? scrapeExportFileUrl(String(cover.posterLocal), cover.posterRev)
    : '';
  const remotes = [
    ...(cover.coverUrls || []),
    cover.coverUrl,
  ].filter((u): u is string => Boolean(String(u || '').trim()));
  return (
    <CroppedCoverImg
      src={local || remotes[0] || null}
      srcs={local ? remotes : remotes.slice(1)}
      region={regionId}
      alt={label}
      loading={loading}
    />
  );
}

function MakerPosterTile({
  item,
  regionId,
  tileAspect,
  loading,
  overlay,
}: {
  item: MakerPosterTileItem;
  regionId: string;
  tileAspect: string;
  loading: 'lazy' | 'eager';
  overlay: 'bottom' | 'center';
}) {
  const hasCover = prefixHasCover(item);
  const overlayClass =
    overlay === 'center'
      ? 'prefix-tile__overlay prefix-tile__overlay--center'
      : 'prefix-tile__overlay';
  return (
    <button type="button" className="prefix-tile" onClick={item.onClick} title={item.label}>
      <span
        className={
          hasCover
            ? 'prefix-tile__media'
            : 'prefix-tile__media prefix-tile__media--nocover'
        }
        style={{ aspectRatio: tileAspect }}
      >
        {hasCover ? (
          <>
            <PosterCover
              cover={item}
              label={item.label}
              regionId={regionId}
              loading={loading}
            />
            <span className={overlayClass}>
              {item.sub ? (
                <span className="prefix-tile__actors allow-select" title={item.sub}>
                  {item.sub}
                </span>
              ) : null}
              <span className="prefix-tile__code allow-select">{item.label}</span>
            </span>
          </>
        ) : (
          <span className="prefix-tile__code prefix-tile__code--solo allow-select">
            {item.label}
          </span>
        )}
      </span>
      {item.title ? (
        <span className="prefix-tile__meta">
          <span className="prefix-tile__title allow-select" title={item.title}>
            {item.title}
          </span>
        </span>
      ) : null}
    </button>
  );
}

/** 厂牌 / 前缀浏览格：与番号 prefix-tile 同一套封面卡片 */
export function MakerPosterGrid({
  regionId,
  items,
  overlay = 'bottom',
}: {
  regionId: string;
  items: MakerPosterTileItem[];
  overlay?: 'bottom' | 'center';
}) {
  const { tileAspect, gridCols } = useRegionPosterFrame(regionId);
  return (
    <div
      className={`prefix-grid mk-browse-grid${overlay === 'center' ? ' mk-browse-grid--center' : ''}`}
      data-cols={gridCols}
    >
      {items.map((it, index) => (
        <MakerPosterTile
          key={it.key}
          item={it}
          regionId={regionId}
          tileAspect={tileAspect}
          loading={index < 8 ? 'eager' : 'lazy'}
          overlay={overlay}
        />
      ))}
    </div>
  );
}
