'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useOverlay, type ToastKind } from '@/components/overlay/OverlayContext';

export type AppMsgTone = 'ok' | 'err' | 'warn' | 'info';

const AUTO_HIDE_MS = 2200;

function inferTone(text: string): AppMsgTone {
  const t = text.trim();
  if (!t) return 'info';
  if (
    /失败|错误|无效|拒绝|超时|无法|不可|禁止|仅管理|请填写|请输入|不一致|至少/.test(t)
  ) {
    return /请填写|请输入|不一致|至少|仅管理|不可/.test(t) ? 'warn' : 'err';
  }
  if (
    /成功|已保存|已创建|已更新|已连接|连通|在线|已填入|已触发|已清空|验证成功|已转存|转存成功/.test(
      t,
    )
  ) {
    return 'ok';
  }
  return 'info';
}

function toToastKind(tone: AppMsgTone): ToastKind {
  if (tone === 'ok') return 'success';
  if (tone === 'err') return 'error';
  if (tone === 'warn') return 'warn';
  return 'info';
}

/** 页面提示：走全局 Toast 弹层，不再挤占正文布局 */
export function AppMsg({
  children,
  tone,
  className: _unusedClassName,
  allowSelect,
  onDismiss,
  duration = AUTO_HIDE_MS,
}: {
  children: string;
  tone?: AppMsgTone;
  className?: string;
  allowSelect?: boolean;
  onDismiss?: () => void;
  /** 自动消失毫秒，默认 2200；传 0 则不自动消失 */
  duration?: number;
}) {
  const { toast } = useOverlay();
  const text = children.trim();
  const lastKey = useRef('');
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;

  useEffect(() => {
    if (!text) {
      lastKey.current = '';
      return;
    }
    const key = `${tone ?? ''}|${duration}|${text}`;
    if (key === lastKey.current) return;
    lastKey.current = key;

    const resolved = tone ?? inferTone(text);
    toast(text, toToastKind(resolved), {
      duration,
      allowSelect,
      onDismiss: () => {
        lastKey.current = '';
        onDismissRef.current?.();
      },
    });
  }, [text, tone, duration, allowSelect, toast]);

  return null;
}

export function AppFootnote({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <p className={cn('app-footnote', className)}>{children}</p>;
}
