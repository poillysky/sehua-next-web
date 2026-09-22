import { cn } from '@/lib/utils';
import { SegTwo } from './ui';
import type { EnrichStrategyForm } from './useEnrichStrategyForm';

export function CoverSection({
  busy,
  cfg,
  onRecompressPosters,
  patch,
  recompressBusy,
  recompressHint,
  regions,
  setCoverRatio,
  setRegionCoverCrop,
}: EnrichStrategyForm) {
    if (!cfg) return null;
    const ratio = cfg.cover?.cropRatio === 'emby' ? 'emby' : 'full';
    const ratioHint =
      ratio === 'emby' ? '按 Emby 常见 2:3 裁切' : '保留完整海报比例 2.12:3';
    const cropOpts = cfg.coverCropOptions?.length
      ? cfg.coverCropOptions.filter(
          (o) => o.id === 'right' || o.id === 'face' || o.id === 'none',
        )
      : [
          { id: 'right', label: '右裁' },
          { id: 'face', label: '人脸' },
          { id: 'none', label: '不裁剪' },
        ];
    const enhance = cfg.coverEnhance === 'official' ? 'official' : 'off';
    const enhanceOpts = cfg.coverEnhanceOptions?.length
      ? cfg.coverEnhanceOptions
      : [
          { id: 'off', label: '关闭' },
          { id: 'official', label: '官网/官方CDN' },
        ];

    return (
      <>
        <p className="settings-group-label">落盘规则</p>
        <ul className="settings-group enrich-strategy__fill-group">
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">图片质量</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  固定省盘；只留 poster.jpg。右裁/人脸：pl 优先，ps
                  过小丢弃后横图裁（不改高度）；不裁剪：只要网站横图
                </span>
              </span>
              <div className="enrich-strategy__chips" role="group" aria-label="图片质量">
                <span className="enrich-strategy__chip enrich-strategy__chip--on">
                  省盘
                </span>
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row">
              <span className="settings-nav__main">
                <span className="settings-kv__key">裁剪比例</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {ratioHint}
                </span>
              </span>
              <SegTwo
                ariaLabel="裁剪比例"
                value={ratio}
                left={{ id: 'full', label: '完整' }}
                right={{ id: 'emby', label: 'Emby' }}
                disabled={busy}
                onChange={(id) =>
                  setCoverRatio(id === 'emby' ? 'emby' : 'full')
                }
              />
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">官方升清</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  短边不达标时试官网/官方 CDN（不开 Amazon/Google）
                </span>
              </span>
              <div
                className="enrich-strategy__chips"
                role="radiogroup"
                aria-label="官方升清"
              >
                {enhanceOpts.map((opt) => {
                  const on = enhance === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        'enrich-strategy__chip',
                        on && 'enrich-strategy__chip--on',
                      )}
                      disabled={busy}
                      role="radio"
                      aria-checked={on}
                      onClick={() =>
                        patch({
                          coverEnhance:
                            opt.id === 'official' ? 'official' : 'off',
                        })
                      }
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </li>
          <li>
            <div className="settings-kv enrich-strategy__fill-row enrich-strategy__fill-row--stack">
              <span className="settings-nav__main">
                <span className="settings-kv__key">批量重压海报</span>
                <span className="settings-nav__desc enrich-strategy__mode-desc">
                  {recompressHint ||
                    '按省盘重压已落盘 poster.jpg，不改构图；体积几乎不降则跳过'}
                </span>
              </span>
              <div className="enrich-strategy__chips" role="group">
                <button
                  type="button"
                  className="enrich-strategy__chip"
                  disabled={busy || recompressBusy}
                  onClick={() => void onRecompressPosters(true)}
                >
                  预览
                </button>
                <button
                  type="button"
                  className="enrich-strategy__chip enrich-strategy__chip--on"
                  disabled={busy || recompressBusy}
                  onClick={() => void onRecompressPosters(false)}
                >
                  {recompressBusy ? '处理中…' : '开始重压'}
                </button>
              </div>
            </div>
          </li>
        </ul>

        <p className="settings-group-label settings-group-label--spaced">
          六区封面逻辑
        </p>
        <div className="enrich-strategy__cover-regions">
          {regions.map((region) => {
            const raw = cfg.cover?.regionCrop?.[region.id] || 'right';
            const cropMode =
              raw === 'face' ? 'face' : raw === 'none' ? 'none' : 'right';
            const activeOpt = cropOpts.find((o) => o.id === cropMode);
            return (
              <section
                key={`cover-${region.id}`}
                className="enrich-strategy__region"
                aria-label={`${region.label} 封面`}
              >
                <header className="enrich-strategy__region-head">
                  <div className="enrich-strategy__region-head-main">
                    <h3 className="enrich-strategy__region-title">
                      {region.label}
                      {region.coverHint ? (
                        <span className="enrich-strategy__region-hint">
                          {region.coverHint}
                        </span>
                      ) : null}
                    </h3>
                  </div>
                  <span className="enrich-strategy__region-count enrich-strategy__region-count--on">
                    {activeOpt?.label || '右裁'}
                  </span>
                </header>
                <div
                  className="enrich-strategy__chips"
                  role="radiogroup"
                  aria-label={`${region.label} 封面裁剪`}
                >
                  {cropOpts.map((opt) => {
                    const on = cropMode === opt.id;
                    return (
                      <button
                        key={`${region.id}-${opt.id}`}
                        type="button"
                        className={cn(
                          'enrich-strategy__chip',
                          on && 'enrich-strategy__chip--on',
                        )}
                        disabled={busy}
                        role="radio"
                        aria-checked={on}
                        onClick={() => setRegionCoverCrop(region.id, opt.id)}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </>
    );
  }
