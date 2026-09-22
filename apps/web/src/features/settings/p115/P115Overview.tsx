'use client';

import { FolderOpen, KeyRound, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { folderDisplayName, SAVE_SOURCES } from './format';
import type { P115PanelState } from './useP115Panel';

export function P115Overview({ p }: { p: P115PanelState }) {
  const {
    quotaLoading,
    locked,
    refreshStatus,
    quotaRatio,
    quotaLow,
    quota,
    quotaTotal,
    quotaError,
    spaceRatio,
    spaceRemainText,
    spaceUsedText,
    spaceTotalText,
    hint,
    targets,
    setTab,
    subsFolder,
    subsLayered,
  } = p;

  return (
    <div className="p115-console__pane">
      <section className="p115-stats" aria-label="115 概览">
        <div className="p115-stats__head">
          <span className="p115-stats__badge p115-stats__badge--ok">已就绪</span>
          <button
            type="button"
            className="p115-stats__refresh"
            disabled={quotaLoading || locked}
            onClick={() => void refreshStatus()}
          >
            <RefreshCw
              size={13}
              strokeWidth={2.25}
              className={cn(quotaLoading && 'p115-spin')}
              aria-hidden
            />
            刷新状态
          </button>
        </div>

        <div className="p115-stats__grid">
          <div className="p115-stat">
            <div className="p115-stat__top">
              <span className="p115-stat__label">云转存</span>
              <span className={cn('p115-stat__pct', quotaLow ? 'is-warn' : 'is-ok')}>
                {quotaRatio != null ? `${Math.round(quotaRatio * 100)}%` : ''}
              </span>
            </div>
            <div className="p115-stat__value allow-select">
              {quotaLoading && quota == null ? (
                <span className="p115-stat__muted">读取中…</span>
              ) : quota != null ? (
                <>
                  <strong>{quota}</strong>
                  {quotaTotal != null ? (
                    <span className="p115-stat__den"> / {quotaTotal}</span>
                  ) : null}
                </>
              ) : (
                <span className="p115-stat__muted">{quotaError || '暂无数据'}</span>
              )}
            </div>
            {quotaRatio != null ? (
              <div
                className={cn('p115-quota-bar', quotaLow && 'p115-quota-bar--low')}
                role="meter"
                aria-valuemin={0}
                aria-valuemax={quotaTotal ?? 0}
                aria-valuenow={quota ?? 0}
                aria-label="云转存剩余额度"
              >
                <span style={{ width: `${Math.round(quotaRatio * 100)}%` }} />
              </div>
            ) : (
              <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                <span style={{ width: '0%' }} />
              </div>
            )}
            <p className="p115-stat__hint">剩余任务额度</p>
          </div>

          <div className="p115-stat">
            <div className="p115-stat__top">
              <span className="p115-stat__label">网盘空间</span>
              <span className="p115-stat__pct is-mute">
                {spaceRatio != null ? `${Math.round(spaceRatio * 100)}%` : ''}
              </span>
            </div>
            <div className="p115-stat__value allow-select">
              {spaceRemainText ? (
                <>
                  <strong>{spaceRemainText}</strong>
                  <span className="p115-stat__den"> 剩余</span>
                </>
              ) : spaceUsedText && spaceTotalText ? (
                <span className="p115-stat__muted">
                  {spaceUsedText} / {spaceTotalText}
                </span>
              ) : (
                <span className="p115-stat__muted">暂无数据</span>
              )}
            </div>
            {spaceRatio != null ? (
              <div
                className="p115-quota-bar p115-quota-bar--space"
                role="meter"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(spaceRatio * 100)}
                aria-label="网盘已用空间"
              >
                <span style={{ width: `${Math.round(spaceRatio * 100)}%` }} />
              </div>
            ) : (
              <div className="p115-quota-bar p115-quota-bar--empty" aria-hidden>
                <span style={{ width: '0%' }} />
              </div>
            )}
            <p className="p115-stat__hint allow-select">
              {spaceUsedText && spaceTotalText
                ? `已用 ${spaceUsedText} · 共 ${spaceTotalText}`
                : '容量占用'}
            </p>
          </div>
        </div>
      </section>

      <ul className="settings-group">
        <li>
          <div className="settings-nav">
            <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
              <KeyRound size={14} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">登录态</span>
              <span className="settings-nav__desc allow-select">
                {hint || '已配置 Cookie'}
              </span>
            </span>
            <button
              type="button"
              className="settings-inline-action"
              onClick={() => setTab('config')}
            >
              管理
            </button>
          </div>
        </li>
      </ul>

      <p className="settings-group-label" style={{ marginTop: 12 }}>
        转存目录
      </p>
      <ul className="settings-group">
        {SAVE_SOURCES.filter((s) =>
          s.key === 'warehouse' || s.key === 'movie' || s.key === 'tv',
        ).map((src) => {
          const t = targets[src.key];
          return (
            <li key={src.key}>
              <div className="settings-nav">
                <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
                  <FolderOpen size={14} strokeWidth={2.25} />
                </span>
                <span className="settings-nav__main">
                  <span className="settings-nav__title">{src.label}</span>
                  <span className="settings-nav__desc allow-select">
                    {folderDisplayName(t)} · CID {t.folderCid || '0'}
                  </span>
                </span>
                <button
                  type="button"
                  className="settings-inline-action"
                  onClick={() => setTab('config')}
                >
                  更改
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="settings-group-label" style={{ marginTop: 12 }}>
        片商分区
      </p>
      <ul className="settings-group">
        {SAVE_SOURCES.filter(
          (s) =>
            s.key !== 'warehouse' && s.key !== 'movie' && s.key !== 'tv',
        ).map((src) => {
          const t = targets[src.key];
          return (
            <li key={src.key}>
              <div className="settings-nav">
                <span className="settings-nav__icon settings-nav__icon--orange" aria-hidden>
                  <FolderOpen size={14} strokeWidth={2.25} />
                </span>
                <span className="settings-nav__main">
                  <span className="settings-nav__title">{src.label}</span>
                  <span className="settings-nav__desc allow-select">
                    {folderDisplayName(t)} · CID {t.folderCid || '0'}
                  </span>
                </span>
                <button
                  type="button"
                  className="settings-inline-action"
                  onClick={() => setTab('config')}
                >
                  更改
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="settings-group-label" style={{ marginTop: 12 }}>
        字幕
      </p>
      <ul className="settings-group">
        <li>
          <div className="settings-nav">
            <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
              <FolderOpen size={14} strokeWidth={2.25} />
            </span>
            <span className="settings-nav__main">
              <span className="settings-nav__title">字幕</span>
              <span className="settings-nav__desc allow-select">
                {subsFolder.folderName
                  ? `${folderDisplayName(subsFolder)} · CID ${subsFolder.folderCid || '0'}`
                  : '未配置（须先选择目录）'}
                {subsLayered ? ' · 按分区分层' : ' · 扁平'}
              </span>
            </span>
            <button
              type="button"
              className="settings-inline-action"
              onClick={() => setTab('config')}
            >
              更改
            </button>
          </div>
        </li>
      </ul>
    </div>
  );
}
