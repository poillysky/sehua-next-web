'use client';

/**
 * Spec-driven connection panel shell (TMDB / PanSou / CloudSaver 等共用骨架)。
 * 具体字段与 get/put/test 仍由各面板传入，避免行为漂移。
 */

import type { ReactNode } from 'react';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';

export function ConnectionPanelShell({
  title,
  onBack,
  msg,
  onDismissMsg,
  loading,
  busy,
  onTest,
  onSave,
  testLabel = '测试连接',
  saveLabel = '保存',
  saveDisabled,
  children,
}: {
  title: string;
  onBack: () => void;
  msg: string;
  onDismissMsg: () => void;
  loading?: boolean;
  busy: boolean;
  onTest: () => void;
  onSave: () => void;
  testLabel?: string;
  saveLabel?: string;
  saveDisabled?: boolean;
  children: ReactNode;
}) {
  return (
    <AppPush title={title} onBack={onBack}>
      {loading ? (
        <p className="settings-group-label">加载中…</p>
      ) : (
        children
      )}
      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={busy || loading}
          onClick={onTest}
        >
          {testLabel}
        </button>
        <button
          type="button"
          className="app-btn-primary"
          style={{ flex: 1 }}
          disabled={busy || loading || saveDisabled}
          onClick={onSave}
        >
          {busy ? '保存中…' : saveLabel}
        </button>
      </div>
      {msg ? (
        <AppMsg allowSelect onDismiss={onDismissMsg}>
          {msg}
        </AppMsg>
      ) : null}
    </AppPush>
  );
}
