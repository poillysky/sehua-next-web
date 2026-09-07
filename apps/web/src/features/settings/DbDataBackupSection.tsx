'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AppFootnote } from '@/components/ui/AppMsg';
import type { ResourceDbBackupItem } from '@/lib/api';

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function DbDataBackupSection({
  dirHint,
  disabled,
  listBackups,
  exportBackup,
  uploadImportBackup,
  onMessage,
  onBusyChange,
}: {
  dirHint: string;
  disabled?: boolean;
  listBackups: () => Promise<ResourceDbBackupItem[]>;
  exportBackup: () => Promise<{
    filename: string;
    bytes: number;
    elapsedMs: number;
  }>;
  uploadImportBackup: (file: File) => Promise<{
    filename: string;
    bytes?: number;
    elapsedMs: number;
    tables: Array<{ name: string; rows: number }>;
  }>;
  onMessage: (text: string) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [backups, setBackups] = useState<ResourceDbBackupItem[]>([]);

  function setBusyBoth(next: boolean) {
    setBusy(next);
    onBusyChange?.(next);
  }

  const refresh = useCallback(async () => {
    try {
      setBackups(await listBackups());
    } catch {
      /* ignore list errors */
    }
  }, [listBackups]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onExport() {
    setBusyBoth(true);
    onMessage(`正在导出资源数据到 ${dirHint}…`);
    try {
      const r = await exportBackup();
      await refresh();
      const sec = (r.elapsedMs / 1000).toFixed(1);
      onMessage(`已导出 ${r.filename}（${formatBytes(r.bytes)}，${sec}s）`);
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '导出失败');
    } finally {
      setBusyBoth(false);
    }
  }

  async function onPickFile(file: File | null) {
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) {
      onMessage('请选择 .zip 备份文件');
      return;
    }
    if (
      !window.confirm(
        `将上传并导入 ${file.name}，覆盖当前资源表数据（不可撤销）。确认继续？`,
      )
    ) {
      if (fileRef.current) fileRef.current.value = '';
      return;
    }
    setBusyBoth(true);
    onMessage(`正在上传并导入 ${file.name}…`);
    try {
      const r = await uploadImportBackup(file);
      await refresh();
      const sec = (r.elapsedMs / 1000).toFixed(1);
      onMessage(`已导入 ${r.filename}（${r.tables.length} 张表，${sec}s）`);
    } catch (e) {
      onMessage(e instanceof Error ? e.message : '导入失败');
    } finally {
      setBusyBoth(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  const locked = Boolean(disabled) || busy;

  return (
    <>
      <p className="settings-group-label">资源数据备份</p>
      <div className="app-actions">
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked}
          onClick={() => void onExport()}
        >
          {busy ? '处理中…' : '导出 zip'}
        </button>
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked}
          onClick={() => fileRef.current?.click()}
        >
          导入 zip
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => void onPickFile(e.target.files?.[0] || null)}
        />
        <button
          type="button"
          className="app-btn-secondary"
          disabled={locked}
          onClick={() => void refresh()}
        >
          刷新列表
        </button>
      </div>
      {backups.length > 0 ? (
        <ul className="settings-group" style={{ marginTop: 8 }}>
          {backups.map((b) => (
            <li key={b.filename}>
              <div className="settings-kv" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="allow-select" style={{ wordBreak: 'break-all' }}>
                    {b.filename}
                  </div>
                  <div className="settings-nav__status" style={{ marginTop: 2 }}>
                    {formatBytes(b.bytes)} · {b.mtime.replace('T', ' ').replace('Z', ' UTC')}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <AppFootnote>尚无备份。导出或导入后会出现在 {dirHint}。</AppFootnote>
      )}
    </>
  );
}
