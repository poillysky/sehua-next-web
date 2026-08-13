'use client';

import { useEffect, useState } from 'react';
import {
  getBrowsePreferences,
  saveBrowsePreferences,
  type BrowsePreferences,
} from '@/hooks/useBrowsePreferences';
import { cn } from '@/lib/utils';

function PrefChip({
  active,
  label,
  title,
  compact,
  onClick,
}: {
  active: boolean;
  label: string;
  title: string;
  compact?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      title={title}
      className={cn('board-pref-chip', compact && 'board-pref-chip--nav')}
      data-active={active ? '1' : '0'}
      onClick={onClick}
    >
      <span className="board-pref-chip__dot" aria-hidden />
      {label}
    </button>
  );
}

/** 搜片倾向：中文 / 破解（localStorage，搜索硬过滤） */
export function BrowsePrefToggles({
  onChange,
  compact = false,
}: {
  onChange?: (prefs: BrowsePreferences) => void;
  /** 顶栏右上角紧凑样式 */
  compact?: boolean;
}) {
  const [prefs, setPrefs] = useState<BrowsePreferences>({
    preferChinese: false,
    preferCrack: false,
  });
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setPrefs(getBrowsePreferences());
    setReady(true);
  }, []);

  function toggle(key: keyof BrowsePreferences) {
    const next = saveBrowsePreferences({ [key]: !prefs[key] });
    setPrefs(next);
    onChange?.(next);
  }

  return (
    <div
      className={cn('board-prefs', compact && 'board-prefs--nav')}
      data-ready={ready ? '1' : '0'}
      role="group"
      aria-label="搜片倾向"
    >
      <PrefChip
        compact={compact}
        active={prefs.preferChinese}
        label="中文"
        title="优先：高清中文字幕板 / 番号尾 C·CX / 含「字幕」或「中文」（排除无字幕）"
        onClick={() => toggle('preferChinese')}
      />
      <PrefChip
        compact={compact}
        active={prefs.preferCrack}
        label="破解"
        title="优先：U/UC/CX、破解、马赛克破坏；含无码高清/流出/破解板"
        onClick={() => toggle('preferCrack')}
      />
    </div>
  );
}
