'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CloudUpload,
  Folder,
  KeyRound,
  Link2,
  Loader2,
} from 'lucide-react';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import { getP115, type P115Config, type P115SaveSource } from '@/lib/api';
import { extractPasteLinks, extractPastePassword } from '@/lib/p115Paste';
import { runP115Save } from '@/lib/p115SaveClient';
import { readInheritedSaveSource, P115_SOURCE_LABEL, P115_SOURCE_ORDER } from '@/lib/p115Source';
import { isArchiveDownloadLink, linkKindOf } from '@/lib/detailResource';
import { useTabNavigation } from '@/shell';

type FolderHint = {
  configured: boolean;
  folderCid: string;
  folderName: string;
};

/** 可存目录来源（仓库 / 影视 / 片商六区） */
const PASTE_SOURCES: Array<{ id: P115SaveSource; label: string }> =
  P115_SOURCE_ORDER.map((id) => ({ id, label: P115_SOURCE_LABEL[id] }));

/** 从 115 配置里取某来源的目录（warehouse 兼容顶层旧字段） */
function folderFor(
  data: P115Config,
  source: P115SaveSource,
): FolderHint | null {
  const configured = Boolean(data.configured);
  if (source === 'warehouse') {
    const t = data.targets?.warehouse;
    return {
      configured,
      folderCid: String(t?.folderCid || data.folderCid || '0'),
      folderName: String(t?.folderName || data.folderName || ''),
    };
  }
  const t = data.targets?.[source];
  if (!t) return { configured, folderCid: '0', folderName: '' };
  return {
    configured,
    folderCid: String(t.folderCid || '0'),
    folderName: String(t.folderName || ''),
  };
}

/** 粘贴转存 115 — 全屏 push，非弹窗（仓库入口） */
export function P115PastePanel({ onBack }: { onBack: () => void }) {
  const tabCtx = useTabNavigation();
  const [paste, setPaste] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [folder, setFolder] = useState<FolderHint | null>(null);
  const [msg, setMsg] = useState('');
  // 落点来源：默认继承影视(movie/tv)/片商六区跳转上下文（惰性初始化，SSR 安全）；
  // 否则回退仓库。避免从影视/片商"在资源库搜索"跳转而来时补粘磁力误存仓库。
  const [source, setSource] = useState<P115SaveSource>(
    () => readInheritedSaveSource() ?? 'warehouse',
  );

  // 载入当前来源目录并展示（含挂载与切换来源时）
  useEffect(() => {
    let cancelled = false;
    void getP115()
      .then((data) => {
        if (cancelled) return;
        setFolder(folderFor(data, source));
      })
      .catch(() => {
        if (!cancelled) setFolder(null);
      });
    return () => {
      cancelled = true;
    };
  }, [source]);

  const links = useMemo(() => extractPasteLinks(paste), [paste]);
  const inferredPassword = useMemo(() => extractPastePassword(paste), [paste]);
  const effectivePassword = password.trim() || inferredPassword || '';
  const shareCount = links.filter((u) => linkKindOf(u) === '115share').length;
  const offlineCount = links.length - shareCount;
  const willExtract =
    offlineCount > 0 &&
    (Boolean(effectivePassword) ||
      links.some((u) => linkKindOf(u) !== '115share' && isArchiveDownloadLink(u)));

  const hasCookie = Boolean(folder?.configured);
  // 非仓库来源若未单独配目录，后端会回退到仓库目录——这里如实提示
  const srcConfigured =
    source === 'warehouse'
      ? hasCookie
      : hasCookie && Boolean(folder?.folderName);
  const folderOk = srcConfigured;
  const fallbackToWarehouse = source !== 'warehouse' && !srcConfigured && hasCookie;
  const folderLabel = hasCookie
    ? folder?.folderName ||
      (folder?.folderCid === '0' ? '根目录' : `CID ${folder?.folderCid}`)
    : '未配置';

  const onSubmit = useCallback(async () => {
    if (!links.length) {
      setMsg('请粘贴磁力 / ED2K / 115 分享链接');
      return;
    }
    setLoading(true);
    try {
      const result = await runP115Save({
        urls: links,
        password: effectivePassword || undefined,
        source,
      });
      if (!result.ok) {
        setMsg(result.message);
        if (result.needConfig) {
          window.setTimeout(() => {
            onBack();
            tabCtx?.scrollToTab('/settings');
          }, 400);
        }
        return;
      }
      setMsg(result.message || '转存成功');
      window.setTimeout(() => onBack(), 700);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '转存失败');
    } finally {
      setLoading(false);
    }
  }, [effectivePassword, links, onBack, tabCtx, source]);

  return (
    <AppPush title="115 转存" onBack={onBack}>
      <div className="p115-paste-page">
        {msg ? <AppMsg onDismiss={() => setMsg('')}>{msg}</AppMsg> : null}

        <p className="p115-paste__section">保存到</p>
        <div className="p115-paste__src" role="radiogroup" aria-label="115 保存目录">
          {PASTE_SOURCES.map((s) => (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={source === s.id}
              className={`p115-paste__src-btn${source === s.id ? ' is-active' : ''}`}
              onClick={() => setSource(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <p className="p115-paste__section">目标目录</p>
        <div className={`p115-paste__card${folderOk ? '' : ' is-warn'}`}>
          <div className="p115-paste__dir">
            <span
              className={`p115-paste__ico${folderOk ? ' p115-paste__ico--orange' : ' p115-paste__ico--mute'}`}
              aria-hidden
            >
              <Folder size={18} strokeWidth={2.2} />
            </span>
            <div className="p115-paste__dir-main">
              <span className="p115-paste__dir-title">{folderLabel}</span>
              <span className="p115-paste__dir-sub">
                {!hasCookie
                  ? '请到更多 → 115 填写 Cookie / 目录'
                  : fallbackToWarehouse
                    ? '未单独配置，将沿用「仓库」目录'
                    : willExtract
                      ? `${P115_SOURCE_LABEL[source]}目录 · 转存后自动云解压`
                      : `${P115_SOURCE_LABEL[source]}目录 · 离线 / 分享转存`}
              </span>
            </div>
            <span className={`p115-paste__badge${folderOk ? ' is-ok' : ' is-warn'}`}>
              {folderOk ? '已就绪' : '需配置'}
            </span>
          </div>
        </div>

        <p className="p115-paste__section">粘贴内容</p>
        <div className="p115-paste__card">
          <label className="p115-paste__row p115-paste__row--stack">
            <span className="p115-paste__row-label">
              <Link2 size={14} strokeWidth={2.2} aria-hidden />
              链接
            </span>
            <textarea
              className="p115-paste__textarea allow-select"
              rows={3}
              value={paste}
              placeholder={'magnet / ed2k / 115 分享\n可附带：解压密码：xxxx'}
              enterKeyHint="done"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => setPaste(e.target.value)}
            />
          </label>
          <label className="p115-paste__row">
            <span className="p115-paste__row-label">
              <KeyRound size={14} strokeWidth={2.2} aria-hidden />
              密码
            </span>
            <input
              className="p115-paste__input allow-select"
              value={password}
              placeholder={
                inferredPassword
                  ? `已识别：${inferredPassword}`
                  : '可选 · 解压 / 访问码'
              }
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        </div>

        {links.length > 0 ? (
          <div className="p115-paste__chips" aria-live="polite">
            <span className="p115-paste__chip">{links.length} 条链接</span>
            {shareCount ? (
              <span className="p115-paste__chip p115-paste__chip--share">
                分享 {shareCount}
              </span>
            ) : null}
            {offlineCount ? (
              <span className="p115-paste__chip p115-paste__chip--offline">
                离线 {offlineCount}
              </span>
            ) : null}
            {willExtract ? (
              <span className="p115-paste__chip p115-paste__chip--extract">云解压</span>
            ) : null}
          </div>
        ) : paste.trim() ? (
          <p className="p115-paste__meta p115-paste__meta--warn">未识别到可用链接</p>
        ) : null}

        <div className="p115-paste-page__cta">
          <button
            type="button"
            className="p115-paste-page__submit"
            disabled={loading || !links.length}
            onClick={() => void onSubmit()}
          >
            {loading ? (
              <Loader2 size={18} strokeWidth={2.2} className="p115-paste__spin" aria-hidden />
            ) : (
              <CloudUpload size={18} strokeWidth={2.2} aria-hidden />
            )}
            <span>
              {loading
                ? '转存中…'
                : willExtract
                  ? `转存到 ${P115_SOURCE_LABEL[source]}并云解压`
                  : `转存到 ${P115_SOURCE_LABEL[source]}`}
            </span>
          </button>
        </div>
      </div>
    </AppPush>
  );
}
