'use client';

import { useAppViewport } from '@/hooks/useAppViewport';

/** 全局视口 / 键盘钉住（登录页与主壳共用） */
export function AppViewport() {
  useAppViewport();
  return null;
}
