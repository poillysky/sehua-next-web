'use client';

import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, KeyRound, LogOut, Trash2, Users } from 'lucide-react';
import { useAuth } from '@/providers/AuthProvider';
import {
  adminCreateUser,
  adminDeleteUser,
  adminResetUserPassword,
  authChangePassword,
  listUsers,
} from '@/lib/api';
import type { AuthUser } from '@/types/resource';
import { AppPush } from '@/components/ui/AppPush';
import { AppFootnote, AppMsg } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';

type Sub =
  | null
  | 'password'
  | 'users'
  | 'create'
  | { kind: 'detail'; user: AuthUser };

export function UserManagePanel({
  onBack,
  onLogout,
}: {
  onBack: () => void;
  onLogout: () => void;
}) {
  const { user, isAdmin } = useAuth();
  const [sub, setSub] = useState<Sub>(null);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [listMsg, setListMsg] = useState('');
  const [listLoading, setListLoading] = useState(false);

  const [currentPwd, setCurrentPwd] = useState('');
  const [nextPwd, setNextPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [createMsg, setCreateMsg] = useState('');

  const [resetPwd, setResetPwd] = useState('');
  const [detailMsg, setDetailMsg] = useState('');

  const initial = (user?.username || '?').slice(0, 1).toUpperCase();

  const refreshUsers = useCallback(async () => {
    if (!isAdmin) return;
    setListLoading(true);
    setListMsg('');
    try {
      setUsers(await listUsers());
    } catch (e) {
      setListMsg(e instanceof Error ? e.message : '加载失败');
    } finally {
      setListLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (sub === 'users' || sub === 'create') void refreshUsers();
  }, [sub, refreshUsers]);

  async function onChangePassword() {
    setPwdMsg('');
    if (nextPwd.length < 8) {
      setPwdMsg('新密码至少 8 位');
      return;
    }
    if (nextPwd !== confirmPwd) {
      setPwdMsg('两次输入不一致');
      return;
    }
    setBusy(true);
    try {
      await authChangePassword(currentPwd, nextPwd);
      setCurrentPwd('');
      setNextPwd('');
      setConfirmPwd('');
      setPwdMsg('密码已更新');
      setSub(null);
    } catch (e) {
      setPwdMsg(e instanceof Error ? e.message : '修改失败');
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    setCreateMsg('');
    if (!newName.trim()) {
      setCreateMsg('请填写用户名');
      return;
    }
    if (newPwd.length < 8) {
      setCreateMsg('密码至少 8 位');
      return;
    }
    setBusy(true);
    try {
      await adminCreateUser(newName.trim(), newPwd);
      setNewName('');
      setNewPwd('');
      setCreateMsg('已创建');
      await refreshUsers();
      setSub('users');
    } catch (e) {
      setCreateMsg(e instanceof Error ? e.message : '创建失败');
    } finally {
      setBusy(false);
    }
  }

  async function onReset(target: AuthUser) {
    setDetailMsg('');
    if (resetPwd.length < 8) {
      setDetailMsg('新密码至少 8 位');
      return;
    }
    setBusy(true);
    try {
      await adminResetUserPassword(target.id, resetPwd);
      setResetPwd('');
      setDetailMsg('密码已重置');
    } catch (e) {
      setDetailMsg(e instanceof Error ? e.message : '重置失败');
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(target: AuthUser) {
    if (!window.confirm(`确定删除用户「${target.username}」？`)) return;
    setBusy(true);
    setDetailMsg('');
    try {
      await adminDeleteUser(target.id);
      setSub('users');
      await refreshUsers();
    } catch (e) {
      setDetailMsg(e instanceof Error ? e.message : '删除失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AppPush title="用户管理" onBack={onBack}>
        <div className="user-card">
          <span className="user-card__avatar" aria-hidden>
            {initial}
          </span>
          <div className="user-card__main">
            <div className="user-card__name">{user?.username || '未登录'}</div>
            <div className="user-card__meta">
              <span className={cn('user-card__badge', !isAdmin && 'user-card__badge--mute')}>
                {isAdmin ? '管理员' : '普通用户'}
              </span>
              {user?.created_at ? (
                <span className="user-card__date">加入 {user.created_at}</span>
              ) : null}
            </div>
          </div>
        </div>

        <p className="settings-group-label">账号</p>
        <ul className="settings-group">
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">用户名</span>
              <span className="settings-kv__val">{user?.username || '—'}</span>
            </div>
          </li>
          <li>
            <div className="settings-kv">
              <span className="settings-kv__key">角色</span>
              <span className="settings-kv__val">{isAdmin ? '管理员' : '普通用户'}</span>
            </div>
          </li>
        </ul>

        {isAdmin ? (
          <>
            <p className="settings-group-label">权限管理</p>
            <ul className="settings-group">
              <li>
                <button type="button" className="settings-nav" onClick={() => setSub('users')}>
                  <span className="settings-nav__icon settings-nav__icon--blue" aria-hidden>
                    <Users size={14} strokeWidth={2.25} />
                  </span>
                  <span className="settings-nav__main">
                    <span className="settings-nav__title">用户管理</span>
                    <span className="settings-nav__desc">查看 · 创建 · 重置密码 · 删除</span>
                  </span>
                  <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
                </button>
              </li>
            </ul>
          </>
        ) : null}

        <p className="settings-group-label">安全</p>
        <ul className="settings-group">
          <li>
            <button type="button" className="settings-nav" onClick={() => setSub('password')}>
              <span className="settings-nav__icon settings-nav__icon--violet" aria-hidden>
                <KeyRound size={14} strokeWidth={2.25} />
              </span>
              <span className="settings-nav__main">
                <span className="settings-nav__title">修改密码</span>
                <span className="settings-nav__desc">定期更换更安全</span>
              </span>
              <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
            </button>
          </li>
        </ul>

        <ul className="settings-group">
          <li>
            <button type="button" className="settings-nav settings-nav--danger" onClick={onLogout}>
              <span className="settings-nav__icon settings-nav__icon--danger" aria-hidden>
                <LogOut size={14} strokeWidth={2.25} />
              </span>
              <span className="settings-nav__main">
                <span className="settings-nav__title">退出登录</span>
              </span>
            </button>
          </li>
        </ul>
      </AppPush>

      {sub === 'password' ? (
        <AppPush title="修改密码" onBack={() => setSub(null)}>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">当前</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  placeholder="当前密码"
                  value={currentPwd}
                  onChange={(e) => setCurrentPwd(e.target.value)}
                />
              </label>
              <label className="app-field">
                <span className="app-label">新密码</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="至少 8 位"
                  value={nextPwd}
                  onChange={(e) => setNextPwd(e.target.value)}
                />
              </label>
              <label className="app-field">
                <span className="app-label">确认</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="再输入一次"
                  value={confirmPwd}
                  onChange={(e) => setConfirmPwd(e.target.value)}
                />
              </label>
            </div>
          </section>
          <div className="app-actions">
            <button
              type="button"
              className="app-btn-primary app-btn-block"
              disabled={busy}
              onClick={() => void onChangePassword()}
            >
              更新密码
            </button>
          </div>
          <AppMsg onDismiss={() => setPwdMsg('')}>{pwdMsg}</AppMsg>
        </AppPush>
      ) : null}

      {sub === 'users' ? (
        <AppPush
          title="用户管理"
          onBack={() => setSub(null)}
          right={
            <button
              type="button"
              className="app-push__back"
              style={{ justifySelf: 'end', fontSize: 15 }}
              onClick={() => setSub('create')}
            >
              创建
            </button>
          }
        >
          {listLoading ? (
            <p className="app-loading">加载中…</p>
          ) : listMsg ? (
            <div className="app-error">{listMsg}</div>
          ) : users.length === 0 ? (
            <p className="app-empty">暂无用户</p>
          ) : (
            <ul className="settings-group">
              {users.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    className="settings-nav"
                    onClick={() => {
                      setDetailMsg('');
                      setResetPwd('');
                      setSub({ kind: 'detail', user: u });
                    }}
                  >
                    <span className="settings-nav__avatar" aria-hidden>
                      {u.username.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">{u.username}</span>
                      <span className="settings-nav__desc">
                        {u.is_admin ? '管理员' : '普通用户'}
                        {u.created_at ? ` · ${u.created_at}` : ''}
                      </span>
                    </span>
                    <ChevronRight className="settings-nav__chev" size={16} strokeWidth={2.25} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </AppPush>
      ) : null}

      {sub === 'create' ? (
        <AppPush title="创建普通用户" onBack={() => setSub('users')}>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">用户名</span>
                <input
                  autoComplete="off"
                  placeholder="新用户名"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
              </label>
              <label className="app-field">
                <span className="app-label">密码</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="至少 8 位"
                  value={newPwd}
                  onChange={(e) => setNewPwd(e.target.value)}
                />
              </label>
            </div>
          </section>
          <AppFootnote>新账号固定为普通用户，不可在此提升为管理员。</AppFootnote>
          <div className="app-actions">
            <button
              type="button"
              className="app-btn-primary app-btn-block"
              disabled={busy}
              onClick={() => void onCreate()}
            >
              创建
            </button>
          </div>
          <AppMsg onDismiss={() => setCreateMsg('')}>{createMsg}</AppMsg>
        </AppPush>
      ) : null}

      {sub && typeof sub === 'object' && sub.kind === 'detail' ? (
        <AppPush title={sub.user.username} onBack={() => setSub('users')}>
          <ul className="settings-group">
            <li>
              <div className="settings-kv">
                <span className="settings-kv__key">角色</span>
                <span className="settings-kv__val">
                  {sub.user.is_admin ? '管理员' : '普通用户'}
                </span>
              </div>
            </li>
            {sub.user.created_at ? (
              <li>
                <div className="settings-kv">
                  <span className="settings-kv__key">创建</span>
                  <span className="settings-kv__val">{sub.user.created_at}</span>
                </div>
              </li>
            ) : null}
          </ul>

          <p className="settings-group-label">重置密码</p>
          <section className="app-section">
            <div className="app-section-body">
              <label className="app-field">
                <span className="app-label">新密码</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="至少 8 位"
                  value={resetPwd}
                  onChange={(e) => setResetPwd(e.target.value)}
                />
              </label>
            </div>
          </section>
          <div className="app-actions">
            <button
              type="button"
              className="app-btn-primary app-btn-block"
              disabled={busy}
              onClick={() => void onReset(sub.user)}
            >
              重置密码
            </button>
          </div>

          {user?.id !== sub.user.id ? (
            <>
              <p className="settings-group-label" style={{ marginTop: 28 }}>
                危险操作
              </p>
              <ul className="settings-group">
                <li>
                  <button
                    type="button"
                    className="settings-nav settings-nav--danger"
                    disabled={busy}
                    onClick={() => void onDelete(sub.user)}
                  >
                    <span className="settings-nav__icon settings-nav__icon--danger" aria-hidden>
                      <Trash2 size={14} strokeWidth={2.25} />
                    </span>
                    <span className="settings-nav__main">
                      <span className="settings-nav__title">删除用户</span>
                    </span>
                  </button>
                </li>
              </ul>
            </>
          ) : null}
          <AppMsg onDismiss={() => setDetailMsg('')}>{detailMsg}</AppMsg>
        </AppPush>
      ) : null}
    </>
  );
}
