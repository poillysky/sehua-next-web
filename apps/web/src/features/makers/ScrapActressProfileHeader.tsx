'use client';

import { useEffect, useState } from 'react';
import {
  lookupScrapActressAvatarUrls,
  peekActressAvatarPosterApi,
  rememberActressAvatarPosterApis,
  type ScrapActressProfile,
} from '@/lib/api';
import { SoftImg } from '@/components/SoftImg';
import { useScrapLocalCover } from './useScrapLocalCover';
const PROFILE_FACT_SLOTS = [
  { key: 'age', label: '年龄' },
  { key: 'height', label: '身高' },
  { key: 'cup', label: '罩杯' },
  { key: 'birthday', label: '生日' },
  { key: 'career', label: '生涯', optional: true },
] as const;

function SkelBar({ size }: { size: 'sm' | 'md' | 'lg' }) {
  return (
    <span
      className={`makers-actress-profile__skel makers-actress-profile__skel--${size}`}
      aria-hidden
    />
  );
}

function isActressAvatarApi(api?: string): boolean {
  const s = String(api || '');
  return (
    s.includes('/_actress/') ||
    s.includes('%2F_actress%2F') ||
    s.includes('%2f_actress%2f')
  );
}

function pickActressAvatarApi(
  name: string,
  ...apis: Array<string | undefined>
): string {
  for (const api of apis) {
    if (isActressAvatarApi(api)) return String(api);
  }
  return peekActressAvatarPosterApi(name);
}

export function ScrapActressProfileHeader({
  name,
  posterApi,
  loading,
  profile,
}: {
  name: string;
  count?: number;
  aliases?: string[]; // 兼容旧调用，界面不再展示
  posterApi?: string;
  loading?: boolean;
  profile?: ScrapActressProfile | null;
}) {
  const profileApi = profile?.posterApi;
  const seedApi = pickActressAvatarApi(name, posterApi, profileApi);
  const [avatarApi, setAvatarApi] = useState(seedApi);

  useEffect(() => {
    const next = pickActressAvatarApi(name, posterApi, profileApi);
    setAvatarApi(next);
    // 已有确切头像路径则不必再查
    if (isActressAvatarApi(posterApi) || isActressAvatarApi(profileApi)) {
      return;
    }
    const n = String(name || '').trim();
    if (!n) return;
    let cancelled = false;
    void lookupScrapActressAvatarUrls([n])
      .then((m) => {
        if (cancelled) return;
        rememberActressAvatarPosterApis(m || {});
        const hit = String((m || {})[n] || '').trim();
        if (hit) setAvatarApi(hit);
      })
      .catch(() => {
        /* keep peek */
      });
    return () => {
      cancelled = true;
    };
  }, [name, posterApi, profileApi]);

  const { src, onError } = useScrapLocalCover({
    posterApi: avatarApi || undefined,
    prefer: 'poster',
    w: 360,
    rp: false,
  });

  const birthday = String(profile?.birthday || '').trim();
  const age = typeof profile?.age === 'number' ? profile.age : null;
  const height = profile?.height;
  const cup = String(profile?.cup || '').trim();
  const career = String(profile?.careerPeriod || '').trim();

  const values: Record<string, string> = {};
  if (age != null) values.age = `${age} 岁`;
  if (height != null) values.height = `${height} cm`;
  if (cup) values.cup = cup;
  if (birthday) values.birthday = birthday;
  if (career) values.career = career;

  const rows = PROFILE_FACT_SLOTS.filter((slot) => {
    if (loading) {
      return slot.key !== 'career' || Boolean(values.career);
    }
    return Boolean(values[slot.key]);
  });

  const showEmpty = !loading && rows.length === 0;
  const skelSize = (key: string): 'sm' | 'md' | 'lg' => {
    if (key === 'cup' || key === 'age') return 'sm';
    if (key === 'career') return 'lg';
    return 'md';
  };

  return (
    <section
      className="makers-actress-profile"
      aria-label={`${name} 基本信息`}
      data-loading={loading ? '1' : undefined}
    >
      <div
        className="makers-actress-profile__avatar"
        data-avatar={src ? '1' : undefined}
      >
        <span className="makers-actress-profile__ph">
          {name.slice(0, 1) || '女'}
        </span>
        {src ? (
          <SoftImg
            key={avatarApi || src}
            src={src}
            loading="eager"
            fetchPriority="high"
            onError={onError}
          />
        ) : null}
      </div>

      <div className="makers-actress-profile__meta">
        <h2 className="makers-actress-profile__name allow-select">{name}</h2>

        {rows.length > 0 ? (
          <dl className="makers-actress-profile__facts allow-select">
            {rows.map((slot) => {
              const value = values[slot.key];
              return (
                <div
                  key={slot.key}
                  className="makers-actress-profile__fact"
                  data-field={slot.key === 'career' ? 'career' : undefined}
                >
                  <dt>{slot.label}</dt>
                  <dd>
                    {loading && !value ? (
                      <SkelBar size={skelSize(slot.key)} />
                    ) : (
                      value
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        ) : showEmpty ? (
          <p className="makers-actress-profile__hint allow-select">
            暂无详细资料
          </p>
        ) : null}
      </div>
    </section>
  );
}
