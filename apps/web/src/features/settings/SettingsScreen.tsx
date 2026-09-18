'use client';

import { useCallback, useEffect, useState, type ComponentType } from 'react';
import {
  ChevronRight,
  Clapperboard,
  Cloud,
  Database,
  HardDrive,
  MessagesSquare,
  Building2,
  Search,
  Sparkles,
  UserRound,
  Wifi,
  type LucideProps,
} from 'lucide-react';
import { useAuth } from '@/providers/AuthProvider';
import { useTabNavigation } from '@/shell';
import {
  getP115,
  getResourceDb,
  getBitmagnetDb,
  getTmdb,
  getAiLlm,
  getAiEmbed,
  getNetwork,
  getMakersCatalog,
  getScrapeSources,
  getPansouSettings,
  getCloudSaverSettings,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import { useStackCover } from '@/hooks/useStackCover';
import { UserManagePanel } from './UserManagePanel';
import { ResourceDbPanel } from './ResourceDbPanel';
import { BitmagnetDbPanel } from './BitmagnetDbPanel';
import { P115Panel } from './P115Panel';
import { TmdbPanel } from './TmdbPanel';
import { ForumManagePanel } from './ForumManagePanel';
import { AiModelsPanel, aiModelsHubStatus } from './AiModelsPanel';
import { NetworkPanel } from './NetworkPanel';
import { MakersManagePanel } from './MakersManagePanel';
import { PansouPanel } from './PansouPanel';
import { CloudSaverPanel } from './CloudSaverPanel';
import {
  getCachedSettingsHubMeta,
  isSettingsHubMetaFresh,
  setCachedSettingsHubMeta,
  type SettingsHubMeta,
} from './settingsHubCache';

type Panel =
  | 'hub'
  | 'users'
  | 'db'
  | 'bitmagnet'
  | 'p115'
  | 'network'
  | 'tmdb'
  | 'pansou'
  | 'cloudsaver'
  | 'forum'
  | 'ai'
  | 'makers';
type Tone = 'ok' | 'warn' | 'mute';
type Accent = 'blue' | 'orange' | 'teal' | 'indigo' | 'green';

type Entry = {
  id: Exclude<Panel, 'hub'>;
  title: string;
  desc: string;
  Icon: ComponentType<LucideProps>;
  accent: Accent;
};

type Section = {
  id: string;
  label: string;
  items: Entry[];
};

const SECTIONS: Section[] = [
  {
    id: 'account',
    label: '账号',
    items: [
      {
        id: 'users',
        title: '用户管理',
        desc: '登录账号与权限',
        Icon: UserRound,
        accent: 'blue',
      },
    ],
  },
  {
    id: 'data',
    label: '资源库',
    items: [
      {
        id: 'db',
        title: '色花资源库',
        desc: 'Sehua · 仓库搜索',
        Icon: Database,
        accent: 'indigo',
      },
      {
        id: 'bitmagnet',
        title: 'Bitmagnet',
        desc: '磁力索引资源库',
        Icon: HardDrive,
        accent: 'teal',
      },
    ],
  },
  {
    id: 'storage',
    label: '连接',
    items: [
      {
        id: 'p115',
        title: '115 转存',
        desc: '按入口分目录转存',
        Icon: Cloud,
        accent: 'orange',
      },
      {
        id: 'network',
        title: '网络代理',
        desc: '出站 HTTP 代理',
        Icon: Wifi,
        accent: 'teal',
      },
      {
        id: 'tmdb',
        title: 'TMDB',
        desc: '影视元数据',
        Icon: Clapperboard,
        accent: 'blue',
      },
      {
        id: 'pansou',
        title: '盘搜 PanSou',
        desc: '网盘资源搜索 API',
        Icon: Search,
        accent: 'orange',
      },
      {
        id: 'cloudsaver',
        title: 'CloudSaver',
        desc: '账号登录与资源搜索',
        Icon: Cloud,
        accent: 'green',
      },
    ],
  },
  {
    id: 'media',
    label: '内容',
    items: [
      {
        id: 'ai',
        title: 'AI 模型',
        desc: '聊天与向量嵌入',
        Icon: Sparkles,
        accent: 'green',
      },
      {
        id: 'makers',
        title: '片商管理',
        desc: '数据源与链接配置',
        Icon: Building2,
        accent: 'orange',
      },
      {
        id: 'forum',
        title: '论坛管理',
        desc: '色花堂 · 板块地区',
        Icon: MessagesSquare,
        accent: 'blue',
      },
    ],
  },
];

const emptyMeta: SettingsHubMeta = {
  users: { text: '…', tone: 'mute' },
  db: { text: '…', tone: 'mute' },
  bitmagnet: { text: '…', tone: 'mute' },
  p115: { text: '…', tone: 'mute' },
  network: { text: '…', tone: 'mute' },
  tmdb: { text: '…', tone: 'mute' },
  pansou: { text: '…', tone: 'mute' },
  cloudsaver: { text: '…', tone: 'mute' },
  ai: { text: '…', tone: 'mute' },
  forum: { text: '…', tone: 'mute' },
  makers: { text: '…', tone: 'mute' },
};

export function SettingsScreen() {
  const { isAdmin, logout, status } = useAuth();
  const tabCtx = useTabNavigation();
  const [panel, setPanel] = useState<Panel>('hub');
  const [meta, setMeta] = useState<SettingsHubMeta>(
    () => ({ ...emptyMeta, ...(getCachedSettingsHubMeta() || {}) }),
  );
  const hubCover = useStackCover(panel !== 'hub', 'settings-hub', 'settings-hub');

  const setEntryStatus = useCallback((id: Exclude<Panel, 'hub'>, text: string, tone: Tone) => {
    setMeta((m) => {
      const next = { ...m, [id]: { text, tone } };
      setCachedSettingsHubMeta(next);
      return next;
    });
  }, []);

  const refreshHub = useCallback(async () => {
    setEntryStatus(
      'users',
      status === 'authenticated' ? (isAdmin ? '管理员' : '已登录') : '未登录',
      status === 'authenticated' ? 'ok' : 'warn',
    );
    setEntryStatus('forum', '色花堂', 'ok');

    // 并行刷新：避免某一个慢接口把后面条目长时间卡在「…」
    // 超时只标「超时」，勿全员「异常」（影视 TMDB 外连拖慢 API 时易误报）
    const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T> =>
      new Promise((resolve, reject) => {
        const t = window.setTimeout(() => reject(new Error('timeout')), ms);
        p.then(
          (v) => {
            window.clearTimeout(t);
            resolve(v);
          },
          (e) => {
            window.clearTimeout(t);
            reject(e);
          },
        );
      });
    const failStatus = (e: unknown): { text: string; tone: Tone } =>
      e instanceof Error && e.message === 'timeout'
        ? { text: '超时', tone: 'mute' }
        : { text: '异常', tone: 'warn' };

    await Promise.all([
      (async () => {
        try {
          const cfg = await withTimeout(getResourceDb(), 12000);
          if (cfg.enabled && cfg.dsn) setEntryStatus('db', '已启用', 'ok');
          else if (cfg.dsn) setEntryStatus('db', '未启用', 'warn');
          else setEntryStatus('db', '未配置', 'warn');
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('db', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const cfg = await withTimeout(getBitmagnetDb(), 12000);
          if (cfg.enabled && cfg.dsn) setEntryStatus('bitmagnet', '已启用', 'ok');
          else if (cfg.dsn) setEntryStatus('bitmagnet', '未启用', 'warn');
          else setEntryStatus('bitmagnet', '未配置', 'warn');
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('bitmagnet', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const p = await withTimeout(getP115(), 12000);
          setEntryStatus('p115', p.configured ? '已就绪' : '未配置', p.configured ? 'ok' : 'warn');
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('p115', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const n = await withTimeout(getNetwork(), 12000);
          const proxyOn = Boolean(n.configured);
          const flareOn = Boolean(n.flareSolverrConfigured);
          setEntryStatus(
            'network',
            proxyOn && flareOn
              ? '代理 · Flare'
              : proxyOn
                ? '代理已启用'
                : flareOn
                  ? 'Flare 已启用'
                  : '未启用',
            proxyOn || flareOn ? 'ok' : 'warn',
          );
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('network', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const t = await withTimeout(getTmdb(), 12000);
          setEntryStatus(
            'tmdb',
            t.configured && !t.fromEnv ? '已配置' : '未配置',
            t.configured && !t.fromEnv ? 'ok' : 'warn',
          );
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('tmdb', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const p = await withTimeout(getPansouSettings(), 12000);
          if (p.enabled && p.baseUrl) setEntryStatus('pansou', '已启用', 'ok');
          else if (p.baseUrl) setEntryStatus('pansou', '未启用', 'warn');
          else setEntryStatus('pansou', '未配置', 'warn');
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('pansou', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const c = await withTimeout(getCloudSaverSettings(), 12000);
          if (c.enabled && c.username && c.hasPassword) {
            setEntryStatus('cloudsaver', '已配置', 'ok');
          } else if (c.username || c.hasPassword || c.baseUrl) {
            setEntryStatus('cloudsaver', '未完整', 'warn');
          } else {
            setEntryStatus('cloudsaver', '未配置', 'warn');
          }
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('cloudsaver', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const [llm, embed] = await withTimeout(Promise.all([getAiLlm(), getAiEmbed()]), 12000);
          const text = aiModelsHubStatus(llm, embed);
          setEntryStatus('ai', text, text === '未配置' ? 'warn' : 'ok');
        } catch (e) {
          const f = failStatus(e);
          setEntryStatus('ai', f.text, f.tone);
        }
      })(),
      (async () => {
        try {
          const scrape = await withTimeout(getScrapeSources(), 12000);
          const enabled = (scrape.sources || []).filter((s) => s.enabled).length;
          setEntryStatus(
            'makers',
            enabled ? '已就绪' : '未启用',
            enabled ? 'ok' : 'warn',
          );
        } catch (e) {
          try {
            const mcfg = await withTimeout(getMakersCatalog(), 8000);
            const text = mcfg.hubStatus || (mcfg.configured ? '已就绪' : '未启用');
            setEntryStatus('makers', text, mcfg.configured ? 'ok' : 'warn');
          } catch {
            const f = failStatus(e);
            setEntryStatus('makers', f.text, f.tone);
          }
        }
      })(),
    ]);
  }, [isAdmin, setEntryStatus, status]);

  useEffect(() => {
    if (panel !== 'hub') return;
    // 登录态本地即可更新，不必等全量接口
    setEntryStatus(
      'users',
      status === 'authenticated' ? (isAdmin ? '管理员' : '已登录') : '未登录',
      status === 'authenticated' ? 'ok' : 'warn',
    );
    setEntryStatus('forum', '色花堂', 'ok');
    // 有未过期缓存则跳过全量刷新（子页 onStatus 已即时改单项）
    if (isSettingsHubMetaFresh()) return;
    void refreshHub();
  }, [panel, refreshHub, setEntryStatus, status, isAdmin]);

  // 再次点「更多」：回到 Hub（iOS 习惯）；切走不强制清栈
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
      <div {...hubCover}>
        <div className="settings-hub__top">
          <h1 className="settings-hub__title">更多</h1>
        </div>
        <div className="settings-hub__scroll">
          {SECTIONS.map((section) => (
            <section key={section.id} className="settings-hub__section">
              <h2 className="settings-group-label">{section.label}</h2>
              <ul className="settings-group">
                {section.items.map((item) => {
                  const Icon = item.Icon;
                  const st = meta[item.id] || { text: '…', tone: 'mute' as Tone };
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
                          <Icon size={17} strokeWidth={2.2} />
                        </span>
                        <span className="settings-nav__main">
                          <span className="settings-nav__title">{item.title}</span>
                          <span className="settings-nav__desc">{item.desc}</span>
                        </span>
                        <span className="settings-nav__trail">
                          <span
                            className={cn(
                              'settings-nav__status',
                              st.tone === 'ok' && 'settings-nav__status--ok',
                              st.tone === 'warn' && 'settings-nav__status--warn',
                              st.tone === 'mute' && 'settings-nav__status--mute',
                            )}
                          >
                            {st.text}
                          </span>
                          <ChevronRight
                            className="settings-nav__chev"
                            size={17}
                            strokeWidth={2.4}
                            aria-hidden
                          />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
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
      {panel === 'bitmagnet' ? (
        <BitmagnetDbPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('bitmagnet', text, tone)}
        />
      ) : null}
      {panel === 'p115' ? (
        <P115Panel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('p115', text, tone)}
        />
      ) : null}
      {panel === 'network' ? (
        <NetworkPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('network', text, tone)}
        />
      ) : null}
      {panel === 'tmdb' ? (
        <TmdbPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('tmdb', text, tone)}
        />
      ) : null}
      {panel === 'pansou' ? (
        <PansouPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('pansou', text, tone)}
        />
      ) : null}
      {panel === 'cloudsaver' ? (
        <CloudSaverPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('cloudsaver', text, tone)}
        />
      ) : null}
      {panel === 'forum' ? (
        <ForumManagePanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('forum', text, tone)}
        />
      ) : null}
      {panel === 'ai' ? (
        <AiModelsPanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('ai', text, tone)}
        />
      ) : null}
      {panel === 'makers' ? (
        <MakersManagePanel
          onBack={() => setPanel('hub')}
          onStatus={(text, tone) => setEntryStatus('makers', text, tone)}
        />
      ) : null}
    </div>
  );
}
