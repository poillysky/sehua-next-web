'use client';

import { useCallback, useEffect, useState, type ComponentType } from 'react';
import {
  ChevronRight,
  Clapperboard,
  Cloud,
  Crop,
  Database,
  FolderTree,
  Image as ImageIcon,
  MessagesSquare,
  Network,
  UserRound,
  type LucideProps,
} from 'lucide-react';
import { useAuth } from '@/providers/AuthProvider';
import { useTabNavigation } from '@/shell';
import {
  fetchMakerFsManifest,
  fetchMakerFsStatus,
  fetchScrapeExportStatus,
  getP115,
  getResourceDb,
  getScrape,
  getTmdb,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import { UserManagePanel } from './UserManagePanel';
import { ResourceDbPanel } from './ResourceDbPanel';
import { P115Panel } from './P115Panel';
import { MakerFsPanel } from './MakerFsPanel';
import { TmdbPanel } from './TmdbPanel';
import { ScrapePanel } from './ScrapePanel';
import { FlareSolverrPanel } from './FlareSolverrPanel';
import { CoverCropPanel } from './CoverCropPanel';
import { ForumManagePanel } from './ForumManagePanel';

type Panel =
  | 'hub'
  | 'users'
  | 'db'
  | 'p115'
  | 'makerfs'
  | 'tmdb'
  | 'flare'
  | 'scrape'
  | 'covercrop'
  | 'forum';
type Tone = 'ok' | 'warn' | 'mute';
type Accent = 'violet' | 'blue' | 'orange' | 'teal';

type Entry = {
  id: Exclude<Panel, 'hub'>;
  title: string;
  desc: string;
  Icon: ComponentType<LucideProps>;
  accent: Accent;
};

const ENTRIES: Entry[] = [
  {
    id: 'users',
    title: '用户管理',
    desc: '账号 · 用户权限',
    Icon: UserRound,
    accent: 'violet',
  },
  {
    id: 'db',
    title: '资源数据库',
    desc: 'Postgres · 搜索库',
    Icon: Database,
    accent: 'blue',
  },
  {
    id: 'p115',
    title: '115网盘',
    desc: 'Cookie · 转存目录',
    Icon: Cloud,
    accent: 'orange',
  },
  {
    id: 'makerfs',
    title: '本地索引',
    desc: '目录 · 封面加速',
    Icon: FolderTree,
    accent: 'orange',
  },
  {
    id: 'covercrop',
    title: '图片裁剪',
    desc: '显示取景 · 刮削存原图',
    Icon: Crop,
    accent: 'teal',
  },
  {
    id: 'tmdb',
    title: 'TMDB',
    desc: '影视英文名翻译',
    Icon: Clapperboard,
    accent: 'blue',
  },
  {
    id: 'flare',
    title: '网络管理',
    desc: '过盾 · 代理',
    Icon: Network,
    accent: 'violet',
  },
  {
    id: 'scrape',
    title: '刮削端',
    desc: '配置 · 任务 · 详情 · 数据源',
    Icon: ImageIcon,
    accent: 'teal',
  },
  {
    id: 'forum',
    title: '论坛管理',
    desc: '色花堂 · 板块地区',
    Icon: MessagesSquare,
    accent: 'blue',
  },
];

const emptyMeta: Record<Exclude<Panel, 'hub'>, { text: string; tone: Tone }> = {
  users: { text: '…', tone: 'mute' },
  db: { text: '…', tone: 'mute' },
  p115: { text: '…', tone: 'mute' },
  makerfs: { text: '…', tone: 'mute' },
  covercrop: { text: '…', tone: 'mute' },
  tmdb: { text: '…', tone: 'mute' },
  flare: { text: '…', tone: 'mute' },
  scrape: { text: '…', tone: 'mute' },
  forum: { text: '…', tone: 'mute' },
};

export function SettingsScreen() {
  const { isAdmin, logout, status } = useAuth();
  const tabCtx = useTabNavigation();
  const [panel, setPanel] = useState<Panel>('hub');
  const [meta, setMeta] = useState(emptyMeta);

  const setEntryStatus = useCallback((id: Exclude<Panel, 'hub'>, text: string, tone: Tone) => {
    setMeta((m) => ({ ...m, [id]: { text, tone } }));
  }, []);

  const refreshHub = useCallback(async () => {
    setEntryStatus(
      'users',
      status === 'authenticated' ? (isAdmin ? '管理员' : '已登录') : '未登录',
      status === 'authenticated' ? 'ok' : 'warn',
    );

    try {
      const cfg = await getResourceDb();
      if (cfg.enabled && cfg.dsn) setEntryStatus('db', '已启用', 'ok');
      else if (cfg.dsn) setEntryStatus('db', '未启用', 'warn');
      else setEntryStatus('db', '未配置', 'warn');
    } catch {
      setEntryStatus('db', '异常', 'warn');
    }

    try {
      const p = await getP115();
      setEntryStatus('p115', p.configured ? '已就绪' : '未配置', p.configured ? 'ok' : 'warn');
    } catch {
      setEntryStatus('p115', '异常', 'warn');
    }

    try {
      const [m, s] = await Promise.all([fetchMakerFsManifest(), fetchMakerFsStatus()]);
      if (s.running) setEntryStatus('makerfs', '构建中', 'mute');
      else setEntryStatus('makerfs', m.ready ? '已就绪' : '未构建', m.ready ? 'ok' : 'warn');
    } catch {
      setEntryStatus('makerfs', '异常', 'warn');
    }

    try {
      const t = await getTmdb();
      setEntryStatus(
        'tmdb',
        t.configured ? (t.fromEnv ? '环境变量' : '已就绪') : '未配置',
        t.configured ? 'ok' : 'warn',
      );
    } catch {
      setEntryStatus('tmdb', '异常', 'warn');
    }

    try {
      const sc = await getScrape();
      const flareUrl = (sc.flareSolverrUrl || '').trim();
      const proxyUrl = (sc.proxyUrl || '').trim();
      if (flareUrl && proxyUrl) setEntryStatus('flare', '已就绪', 'ok');
      else if (flareUrl) setEntryStatus('flare', '过盾已配', 'ok');
      else if (proxyUrl) setEntryStatus('flare', '代理已配', 'ok');
      else setEntryStatus('flare', '未配置', 'warn');
      setEntryStatus(
        'scrape',
        sc.online ? '已在线' : sc.configured ? '离线' : '未配置',
        sc.online ? 'ok' : 'warn',
      );
      try {
        const st = await fetchScrapeExportStatus();
        if (st.running) {
          setEntryStatus('scrape', st.paused ? '已暂停' : '刮削中', st.paused ? 'warn' : 'mute');
        }
      } catch {
        /* ignore */
      }
      setEntryStatus('covercrop', sc.posterCrop ? '已就绪' : '默认', 'ok');
    } catch {
      setEntryStatus('flare', '异常', 'warn');
      setEntryStatus('scrape', '异常', 'warn');
      setEntryStatus('covercrop', '异常', 'warn');
    }

    setEntryStatus('forum', '色花堂', 'ok');
  }, [isAdmin, setEntryStatus, status]);

  useEffect(() => {
    if (panel === 'hub') void refreshHub();
  }, [panel, refreshHub]);

  // 再次点「设置」：回到 Hub（iOS 习惯）；切走不强制清栈
  useEffect(() => {
    if (!tabCtx || tabCtx.activeTab !== '/settings') return;
    if (tabCtx.tabReselect > 0) setPanel('hub');
  }, [tabCtx?.tabReselect]);

  async function onLogout() {
    await logout();
    setPanel('hub');
  }

  return (
    <div className="settings-screen-root">
      <div className="settings-hub" aria-hidden={panel !== 'hub'}>
        <div className="settings-hub__scroll">
          <h1 className="settings-hub__title">设置</h1>
          <ul className="settings-group">
            {ENTRIES.map((item) => {
              const Icon = item.Icon;
              const st = meta[item.id];
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className="settings-nav"
                    onClick={() => setPanel(item.id)}
                  >
                    <span
                      className={`settings-nav__icon settings-nav__icon--${item.accent}`}
                      aria-hidden
                    >
                      <Icon size={16} strokeWidth={2.25} />
                    </span>
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{item.title}</span>
                      <span className="settings-nav__desc">{item.desc}</span>
                    </span>
                    <span
                      className={cn(
                        'settings-nav__status',
                        st.tone === 'ok' && 'settings-nav__status--ok',
                        st.tone === 'warn' && 'settings-nav__status--warn',
                      )}
                    >
                      {st.text}
                    </span>
                    <ChevronRight className="settings-nav__chev" size={18} strokeWidth={2.25} />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {panel === 'users' ? (
        <UserManagePanel onBack={() => setPanel('hub')} onLogout={() => void onLogout()} />
      ) : null}
      {panel === 'db' ? (
        <ResourceDbPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('db', text, tone)}
        />
      ) : null}
      {panel === 'p115' ? (
        <P115Panel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('p115', text, tone)}
        />
      ) : null}
      {panel === 'makerfs' ? (
        <MakerFsPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('makerfs', text, tone)}
        />
      ) : null}
      {panel === 'tmdb' ? (
        <TmdbPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('tmdb', text, tone)}
        />
      ) : null}
      {panel === 'flare' ? (
        <FlareSolverrPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('flare', text, tone)}
        />
      ) : null}
      {panel === 'covercrop' ? (
        <CoverCropPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('covercrop', text, tone)}
        />
      ) : null}
      {panel === 'scrape' ? (
        <ScrapePanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('scrape', text, tone)}
        />
      ) : null}
      {panel === 'forum' ? (
        <ForumManagePanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('forum', text, tone)}
        />
      ) : null}
    </div>
  );
}
