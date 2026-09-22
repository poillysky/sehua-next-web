'use client';

import { ChevronRight, Folder, FolderPlus, RefreshCw } from 'lucide-react';
import { putPrefixCatalogStrmSyncSettings, putScrapLibraryEmbedSettings } from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { AppMsg } from '@/components/ui/AppMsg';
import type { MakersManagePanelState } from './useMakersManagePanel';

export function StrmBrowseView({ p }: { p: MakersManagePanelState }) {
  const {
    strmBrowse,
    strmBrowseKind,
    scrapRoot,
    strmRoot,
    strmBrowseLoading,
    strmNewFolder,
    setStrmNewFolder,
    strmBrowseMsg,
    setStrmBrowseMsg,
    setScrapRoot,
    setStrmRoot,
    setMsg,
    setStrmBrowseOpen,
    onStatus,
    loadStrmBrowse,
    onPickStrmDir,
    onCreateStrmFolder,
  } = p;

  const crumbs = strmBrowse?.crumbs || [];
  const folders = strmBrowse?.folders || [];
  const herePath = strmBrowse?.path || '';
  const hereName = crumbs.length ? crumbs[crumbs.length - 1]!.name : '';
  const activeRoot =
    strmBrowseKind === 'scrap'
      ? scrapRoot || 'scrap-library'
      : strmRoot || 'strm-library';
  const hereIsCurrent = !!herePath && activeRoot === herePath;
  const parentPath = herePath.includes('/')
    ? herePath.split('/').slice(0, -1).join('/')
    : '';
  const defaultName =
    strmBrowseKind === 'scrap' ? 'scrap-library' : 'strm-library';

  async function pickFolder(path: string) {
    try {
      if (strmBrowseKind === 'scrap') {
        const s = await putScrapLibraryEmbedSettings(path);
        setScrapRoot(s.root || path);
        setMsg(`已选择刮削库 · media/${s.root}`);
      } else {
        const s = await putPrefixCatalogStrmSyncSettings(path);
        setStrmRoot(s.root || path);
        setMsg(`已选择 · media/${s.root}`);
      }
      setStrmBrowseOpen(false);
      onStatus('目录已保存', 'ok');
    } catch (e) {
      setStrmBrowseMsg(e instanceof Error ? e.message : '保存失败');
    }
  }

  return (
      <AppPush
        title={
          hereName ||
          (strmBrowseKind === 'scrap' ? '选择刮削库目录' : '选择输出目录')
        }
        onBack={() => {
          if (herePath) {
            void loadStrmBrowse(parentPath);
            return;
          }
          setStrmBrowseOpen(false);
        }}
        scrollKey={
          strmBrowseKind === 'scrap' ? 'scrap-browse' : 'strm-browse'
        }
        right={
          <div className="strm-pick__nav-right">
            <button
              type="button"
              className="strm-pick__icon-btn"
              disabled={strmBrowseLoading}
              aria-label="刷新"
              onClick={() => void loadStrmBrowse(herePath)}
            >
              <RefreshCw
                size={15}
                strokeWidth={2.2}
                className={strmBrowseLoading ? 'strm-pick__spin' : undefined}
              />
            </button>
            <button
              type="button"
              className="makers-manage__probe-btn"
              disabled={strmBrowseLoading}
              onClick={() => void onPickStrmDir()}
            >
              选用此层
            </button>
          </div>
        }
      >
        <div className="makers-manage makers-manage--detail makers-manage--strm-pick">
          <div className="strm-pick">
            <p className="settings-group-label">文件夹</p>
            <ul className="settings-group makers-manage__rise strm-pick__list">
              {strmBrowseLoading && folders.length === 0 ? (
                <li>
                  <div className="strm-pick__empty">加载中…</div>
                </li>
              ) : folders.length === 0 ? (
                <li>
                  <div className="strm-pick__empty">
                    没有子文件夹 · 可点右上角「选用此层」
                  </div>
                </li>
              ) : (
                folders.map((f) => {
                  const selected = activeRoot === f.path;
                  const isDefault = f.name === defaultName;
                  return (
                    <li key={f.path}>
                      <div
                        className={
                          selected
                            ? 'strm-pick__row is-selected'
                            : 'strm-pick__row'
                        }
                      >
                        <button
                          type="button"
                          className="strm-pick__open"
                          disabled={strmBrowseLoading}
                          onClick={() => void loadStrmBrowse(f.path)}
                        >
                          <span
                            className={
                              isDefault
                                ? 'settings-nav__icon settings-nav__icon--blue'
                                : 'settings-nav__icon settings-nav__icon--orange'
                            }
                            aria-hidden
                          >
                            <Folder size={17} strokeWidth={2.2} />
                          </span>
                          <span className="strm-pick__meta">
                            <span className="strm-pick__name">{f.name}</span>
                            {selected ? (
                              <span className="strm-pick__badge">当前</span>
                            ) : isDefault ? (
                              <span className="strm-pick__badge strm-pick__badge--soft">
                                推荐
                              </span>
                            ) : null}
                          </span>
                          <ChevronRight
                            className="strm-pick__chev"
                            size={16}
                            strokeWidth={2.2}
                            aria-hidden
                          />
                        </button>
                        <button
                          type="button"
                          className="strm-pick__use"
                          disabled={strmBrowseLoading}
                          onClick={() => void pickFolder(f.path)}
                        >
                          选用
                        </button>
                      </div>
                    </li>
                  );
                })
              )}
            </ul>

            <p className="settings-group-label">新建</p>
            <ul className="settings-group makers-manage__rise">
              <li>
                <div className="strm-pick__mkdir">
                  <span
                    className="settings-nav__icon settings-nav__icon--green"
                    aria-hidden
                  >
                    <FolderPlus size={17} strokeWidth={2.2} />
                  </span>
                  <input
                    className="strm-pick__mkdir-input"
                    value={strmNewFolder}
                    disabled={strmBrowseLoading}
                    placeholder="文件夹名称"
                    onChange={(e) => setStrmNewFolder(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void onCreateStrmFolder();
                    }}
                  />
                  <button
                    type="button"
                    className="strm-pick__use"
                    disabled={strmBrowseLoading || !strmNewFolder.trim()}
                    onClick={() => void onCreateStrmFolder()}
                  >
                    创建
                  </button>
                </div>
              </li>
            </ul>

            {hereIsCurrent ? (
              <p className="strm-pick__foot">当前输出目录即此层</p>
            ) : (
              <p className="strm-pick__foot">
                点文件夹进入下级 · 或点「选用」设为输出目录
              </p>
            )}
            <AppMsg allowSelect onDismiss={() => setStrmBrowseMsg('')}>
              {strmBrowseMsg}
            </AppMsg>
          </div>
        </div>
      </AppPush>
  );
}
