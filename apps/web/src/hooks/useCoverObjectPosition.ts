'use client';

import { useEffect, useState } from 'react';
import type { PosterCropMode } from '@/lib/api';
import {
  resolveFaceObjectPosition,
  staticObjectPositionForMode,
} from '@/lib/coverFaceFocus';

/** 按取景模式解析 object-position；face 会异步检测人脸/肤色重心 */
export function useCoverObjectPosition(
  mode: PosterCropMode | undefined,
  src: string | null | undefined,
): string {
  const fallback = staticObjectPositionForMode(mode);
  const [pos, setPos] = useState(fallback);

  useEffect(() => {
    setPos(fallback);
    if (mode !== 'face') return;
    const url = String(src || '').trim();
    if (!url) return;
    let cancelled = false;
    void resolveFaceObjectPosition(url).then((next) => {
      if (!cancelled) setPos(next);
    });
    return () => {
      cancelled = true;
    };
  }, [mode, src, fallback]);

  return pos;
}
