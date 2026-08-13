'use client';

import { useEffect, useState } from 'react';
import {
  DEFAULT_POSTER_CROP,
  getPosterCrop,
  putPosterCrop,
  type PosterCropConfig,
  type PosterCropMode,
} from '@/lib/api';
import {
  getPosterCropCached,
  POSTER_CROP_KIND_ROWS,
  setPosterCropCached,
} from '@/lib/coverCropPrefs';
import { makerFsRegionMark } from '@/lib/makerFsUi';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

const MODE_SEGMENTS: Array<{ value: PosterCropMode; label: string }> = [
  { value: 'right', label: '右侧' },
  { value: 'none', label: '不裁' },
  { value: 'face', label: '人脸' },
];

export function CoverCropPanel({
  onBack,
  onStatus,
}: {
  onBack: () => void;
  onStatus: (text: string, tone: 'ok' | 'warn' | 'mute') => void;
}) {
  const [crop, setCrop] = useState<PosterCropConfig>(() => getPosterCropCached());
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    onStatus('已就绪', 'ok');
    let cancelled = false;
    void (async () => {
      try {
        const next = await getPosterCrop();
        if (cancelled) return;
        setCrop(next);
        setPosterCropCached(next);
      } catch (e) {
        if (cancelled) return;
        setMsg(e instanceof Error ? e.message : '读取失败');
        onStatus('异常', 'warn');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setMode(regionId: string, mode: PosterCropMode) {
    setCrop((prev) => ({
      ...prev,
      byKind: { ...prev.byKind, [regionId]: mode },
    }));
  }

  async function onSave() {
    setBusy(true);
    setMsg('');
    try {
      const payload: PosterCropConfig = {
        ...crop,
        cropDownloadedPoster: false,
        preferCropIfBetter: false,
      };
      const saved = await putPosterCrop(payload);
      setCrop(saved);
      setPosterCropCached(saved);
      setMsg('已保存');
      onStatus('已就绪', 'ok');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '保存失败');
      onStatus('异常', 'warn');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppPush title="图片裁剪" onBack={onBack}>
      <div className="cover-crop-panel">
        <p className="settings-group-label">七区取景</p>
        <ul className="settings-group cover-crop-list">
          {POSTER_CROP_KIND_ROWS.map((row) => {
            const mode = crop.byKind[row.id] || DEFAULT_POSTER_CROP.byKind[row.id] || 'right';
            return (
              <li key={row.id}>
                <div className="cover-crop-row">
                  <span className="cover-crop-row__mark" aria-hidden>
                    {makerFsRegionMark(row.id)}
                  </span>
                  <span className="cover-crop-row__title">{row.label}</span>
                  <div
                    className="cover-crop-seg"
                    role="radiogroup"
                    aria-label={`${row.label}取景`}
                  >
                    {MODE_SEGMENTS.map((seg) => {
                      const on = mode === seg.value;
                      return (
                        <button
                          key={seg.value}
                          type="button"
                          role="radio"
                          aria-checked={on}
                          className={cn(
                            'cover-crop-seg__btn',
                            on && 'cover-crop-seg__btn--on',
                          )}
                          disabled={busy}
                          onClick={() => setMode(row.id, seg.value)}
                        >
                          {seg.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="cover-crop-actions">
          <button
            type="button"
            className="app-btn-primary"
            disabled={busy}
            onClick={() => void onSave()}
          >
            {busy ? '保存中…' : '保存'}
          </button>
        </div>
        <AppMsg allowSelect onDismiss={() => setMsg('')}>
          {msg}
        </AppMsg>
      </div>
    </AppPush>
  );
}
