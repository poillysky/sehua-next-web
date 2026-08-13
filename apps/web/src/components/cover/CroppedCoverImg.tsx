'use client';

import { useEffect, useState } from 'react';
import { useCoverObjectPosition } from '@/hooks/useCoverObjectPosition';
import { proxiedCoverUrl } from '@/lib/api';
import {
  cropModeForRegion,
  ensurePosterCropLoaded,
  frameAspectForCropMode,
  getPosterCropCached,
  isPortraitCropMode,
  objectFitForCropMode,
  objectPositionForCropMode,
  subscribePosterCrop,
} from '@/lib/coverCropPrefs';
import { cn } from '@/lib/utils';

type Props = {
  src?: string | null;
  /** 备用封面（加载失败时依次尝试） */
  srcs?: Array<string | null | undefined>;
  /** 七区 id / maker-fs region，决定裁剪模式 */
  region?: string | null;
  alt?: string;
  className?: string;
  emptyClassName?: string;
  /** 无图时的文案（否则空 span） */
  emptyLabel?: string;
  loading?: 'lazy' | 'eager';
  referrerPolicy?: React.HTMLAttributeReferrerPolicy;
  decoding?: 'async' | 'auto' | 'sync';
  style?: React.CSSProperties;
  /**
   * thumb：列表小图自适应框——裁剪用竖版，不裁剪用横版以露原图整幅结构
   */
  layout?: 'bare' | 'thumb';
  frameClassName?: string;
};

/**
 * 按「图片裁剪」分区设置显示封面（右侧 / 人脸 / 不裁剪）。
 * 不裁剪时一律横框 + contain，保留碟片封面左右结构。
 * 外链经 /cover-proxy（服务端用项目 proxyUrl），避免浏览器直连 CDN 失败。
 */
export function CroppedCoverImg({
  src,
  srcs,
  region,
  alt = '',
  className,
  emptyClassName,
  emptyLabel,
  loading = 'lazy',
  referrerPolicy = 'no-referrer',
  decoding = 'async',
  style,
  layout = 'bare',
  frameClassName,
}: Props) {
  const candidates = (() => {
    const out: string[] = [];
    const push = (u?: string | null) => {
      const s = proxiedCoverUrl(u);
      if (s && !out.includes(s)) out.push(s);
    };
    push(src);
    for (const u of srcs || []) push(u);
    return out;
  })();
  const [idx, setIdx] = useState(0);
  const [cropTick, setCropTick] = useState(0);
  const [gone, setGone] = useState(false);
  const active = candidates[idx] || '';

  useEffect(() => {
    void ensurePosterCropLoaded();
    return subscribePosterCrop(() => setCropTick((n) => n + 1));
  }, []);

  useEffect(() => {
    setIdx(0);
    setGone(false);
  }, [candidates.join('\0')]);

  const cropMode = (() => {
    void cropTick;
    return region ? cropModeForRegion(region) : undefined;
  })();
  const ratio = (() => {
    void cropTick;
    return getPosterCropCached().ratio;
  })();
  const fallbackPos = objectPositionForCropMode(cropMode);
  const facePos = useCoverObjectPosition(cropMode, gone ? null : active);
  const objectPosition = cropMode === 'face' ? facePos : fallbackPos;
  const objectFit = objectFitForCropMode(cropMode);
  const usePortraitFrame = isPortraitCropMode(cropMode);
  const thumbFrame =
    layout === 'thumb'
      ? {
          aspectRatio: frameAspectForCropMode(cropMode, ratio),
          crop: usePortraitFrame ? 'portrait' : 'full',
        }
      : null;

  const empty = (
    <span
      className={emptyClassName || className}
      aria-hidden={!emptyLabel}
      data-crop={thumbFrame?.crop}
    >
      {emptyLabel || null}
    </span>
  );

  if (!active || gone) {
    if (thumbFrame) {
      return (
        <span
          className={cn('cover-thumb-frame', frameClassName)}
          data-crop={thumbFrame.crop}
          style={{ aspectRatio: thumbFrame.aspectRatio }}
          aria-hidden={!emptyLabel}
        >
          {empty}
        </span>
      );
    }
    return empty;
  }

  const img = (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      src={active}
      alt={alt}
      loading={loading}
      decoding={decoding}
      referrerPolicy={referrerPolicy}
      style={{ objectPosition, objectFit, ...style }}
      onError={() => {
        if (idx + 1 < candidates.length) setIdx((n) => n + 1);
        else setGone(true);
      }}
    />
  );

  if (thumbFrame) {
    return (
      <span
        className={cn('cover-thumb-frame', frameClassName)}
        data-crop={thumbFrame.crop}
        style={{ aspectRatio: thumbFrame.aspectRatio }}
      >
        {img}
      </span>
    );
  }

  return img;
}
