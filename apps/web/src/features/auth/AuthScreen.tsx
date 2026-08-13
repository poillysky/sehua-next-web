'use client';

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import Image from 'next/image';
import { Eye, EyeOff } from 'lucide-react';
import { BackButton } from '@/components/ui/BackButton';
import { useAuth } from '@/providers/AuthProvider';
import './login.css';

type Phase = 'gate' | 'login' | 'register';
type NavDir = 'push' | 'pop';

const PUSH_MS = 360;
const BRAND = '资源仓库';

/**
 * 色花登录：门闸 → Push 登录/注册（Cookie 会话认证）
 */
export function AuthScreen() {
  const { status, user, login, register, logout, isAdmin } = useAuth();
  const [phase, setPhase] = useState<Phase>('gate');
  const [prevPhase, setPrevPhase] = useState<Phase | null>(null);
  const [navDir, setNavDir] = useState<NavDir | null>(null);
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [agreed, setAgreed] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [gateActionsSettled, setGateActionsSettled] = useState(false);
  const animatingRef = useRef(false);
  const timerRef = useRef<number | null>(null);

  const isForm = phase === 'login' || phase === 'register';
  const showBack = isForm || prevPhase === 'login' || prevPhase === 'register';

  useEffect(() => {
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (gateActionsSettled || phase !== 'gate') return;
    const id = window.setTimeout(() => setGateActionsSettled(true), 800);
    return () => window.clearTimeout(id);
  }, [phase, gateActionsSettled]);

  function requireAgree() {
    if (!agreed) {
      setError('请先阅读并同意用户协议与隐私政策');
      return false;
    }
    return true;
  }

  function navigate(next: Phase, direction: NavDir) {
    if (animatingRef.current || next === phase) return;
    if (phase === 'gate') setGateActionsSettled(true);
    animatingRef.current = true;
    setPrevPhase(phase);
    setNavDir(direction);
    setPhase(next);
    setError('');
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      setPrevPhase(null);
      setNavDir(null);
      animatingRef.current = false;
      timerRef.current = null;
    }, PUSH_MS);
  }

  function openForm(next: 'login' | 'register') {
    if (!requireAgree()) return;
    setShowPassword(false);
    setShowConfirmPassword(false);
    if (next === 'register') setConfirmPassword('');
    navigate(next, 'push');
  }

  function goBack() {
    if (phase === 'login' || phase === 'register' || prevPhase === 'login' || prevPhase === 'register') {
      if (animatingRef.current) {
        if (timerRef.current != null) window.clearTimeout(timerRef.current);
        timerRef.current = null;
        animatingRef.current = false;
        setPrevPhase(null);
        setNavDir(null);
      }
      if (phase !== 'gate') navigate('gate', 'pop');
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!requireAgree()) return;
    if (phase === 'register' && password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      if (phase === 'register') await register(account.trim(), password);
      else await login(account.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  function renderGate() {
    return (
      <div className="login-gate">
        <div className="login-gate-brand">
          <div className="login-app-icon" aria-hidden>
            <Image
              src="/brand/logo.png"
              alt=""
              width={144}
              height={144}
              className="login-app-icon-img"
              priority
            />
          </div>
          <h1 className="login-brand">{BRAND}</h1>
          <p className="login-tagline">资源检索 · 磁力收藏</p>
        </div>
        <div className="login-gate-spacer" aria-hidden />
        <div
          className={
            gateActionsSettled
              ? 'login-gate-actions login-gate-actions--settled'
              : 'login-gate-actions'
          }
        >
          {error ? <p className="login-error login-error-gate">{error}</p> : null}
          <button
            type="button"
            className="login-btn-primary"
            disabled={submitting}
            onClick={() => openForm('login')}
          >
            账号登录
          </button>
          <button
            type="button"
            className="login-btn-secondary"
            disabled={submitting}
            onClick={() => openForm('register')}
          >
            注册账号
          </button>
          <label className="login-terms">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
            />
            <span>
              已阅读并同意{' '}
              <button type="button" className="login-terms-link">
                用户协议
              </button>{' '}
              &{' '}
              <button type="button" className="login-terms-link">
                隐私政策
              </button>
            </span>
          </label>
        </div>
      </div>
    );
  }

  function renderForm(formPhase: 'login' | 'register') {
    return (
      <>
        <div className="login-form-head">
          <h2 className="login-title">
            {formPhase === 'login' ? '账号登录' : '注册账号'}
          </h2>
        </div>
        <div className="login-scroll">
          <form className="login-form" onSubmit={(e) => void handleSubmit(e)}>
            <label className="login-field">
              <span className="login-label">账号</span>
              <input
                type="text"
                name="account"
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder="字母、数字或下划线"
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                required
                minLength={3}
                maxLength={32}
              />
            </label>
            <label className="login-field">
              <span className="login-label">密码</span>
              <div className="login-password-row">
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  autoComplete={
                    formPhase === 'login' ? 'current-password' : 'new-password'
                  }
                  placeholder={formPhase === 'login' ? '请输入密码' : '至少 8 位'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  maxLength={128}
                />
                <button
                  type="button"
                  className="login-eye"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? (
                    <EyeOff size={18} strokeWidth={1.75} />
                  ) : (
                    <Eye size={18} strokeWidth={1.75} />
                  )}
                </button>
              </div>
            </label>
            {formPhase === 'register' ? (
              <label className="login-field">
                <span className="login-label">确认密码</span>
                <div className="login-password-row">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    name="confirmPassword"
                    autoComplete="new-password"
                    placeholder="再次输入"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={8}
                    maxLength={128}
                  />
                  <button
                    type="button"
                    className="login-eye"
                    onClick={() => setShowConfirmPassword((v) => !v)}
                    aria-label={
                      showConfirmPassword ? '隐藏确认密码' : '显示确认密码'
                    }
                  >
                    {showConfirmPassword ? (
                      <EyeOff size={18} strokeWidth={1.75} />
                    ) : (
                      <Eye size={18} strokeWidth={1.75} />
                    )}
                  </button>
                </div>
              </label>
            ) : null}
            {error ? <p className="login-error">{error}</p> : null}
            <button
              type="submit"
              className="login-btn-primary login-form-submit"
              disabled={submitting}
            >
              {submitting
                ? '请稍候…'
                : formPhase === 'login'
                  ? '登录'
                  : '注册并登录'}
            </button>
          </form>
          <p className="login-switch">
            {formPhase === 'login' ? (
              <>
                还没有账号？
                <button
                  type="button"
                  onClick={() => {
                    setConfirmPassword('');
                    setShowConfirmPassword(false);
                    setError('');
                    setPhase('register');
                  }}
                >
                  立即注册
                </button>
              </>
            ) : (
              <>
                已有账号？
                <button
                  type="button"
                  onClick={() => {
                    setError('');
                    setPhase('login');
                  }}
                >
                  去登录
                </button>
              </>
            )}
          </p>
        </div>
      </>
    );
  }

  function renderPhase(p: Phase): ReactNode {
    if (p === 'gate') return renderGate();
    return renderForm(p);
  }

  function layerClass(role: 'current' | 'prev'): string {
    const parts = ['login-layer'];
    if (!navDir) return parts.join(' ');
    if (role === 'current') parts.push(`login-layer--enter-${navDir}`);
    else parts.push(`login-layer--exit-${navDir}`);
    return parts.join(' ');
  }

  if (status === 'authenticated' && user) {
    return (
      <div className="login-screen">
        <div className="login-gate">
          <div className="login-gate-brand">
            <div className="login-app-icon" aria-hidden>
              <Image
                src="/brand/logo.png"
                alt=""
                width={144}
                height={144}
                className="login-app-icon-img"
                priority
              />
            </div>
            <h1 className="login-brand">{BRAND}</h1>
            <p className="login-tagline">
              已登录 · {user.username}
              {isAdmin ? ' · 管理员' : ' · 普通用户'}
            </p>
          </div>
          <div className="login-gate-spacer" aria-hidden />
          <div className="login-gate-actions login-gate-actions--settled">
            <button
              type="button"
              className="login-btn-secondary"
              onClick={() => void logout()}
            >
              退出登录
            </button>
          </div>
        </div>
      </div>
    );
  }

  const currentKey = isForm ? 'form' : 'gate';
  const prevKey =
    prevPhase == null ? null : prevPhase === 'gate' ? 'gate' : 'form';

  return (
    <div className="login-screen">
      <header className="login-top">
        {showBack ? (
          <BackButton
            iconOnly
            className="login-back"
            onClick={goBack}
            aria-label="返回"
          />
        ) : null}
      </header>
      <div className="login-stack">
        {prevPhase != null && prevKey != null ? (
          <div className={layerClass('prev')} key={`prev-${prevKey}`} aria-hidden>
            {renderPhase(prevPhase)}
          </div>
        ) : null}
        <div className={layerClass('current')} key={`cur-${currentKey}`}>
          {renderPhase(phase)}
        </div>
      </div>
    </div>
  );
}
