'use client';

import { HomeResultsChrome } from './HomeResultsChrome';
import { HomeResultsBody } from './HomeResultsBody';
import type { HomeScreenState } from './useHomeScreen';

type Props = {
  h: HomeScreenState;
};

export function HomeResults({ h }: Props) {
  return (
    <div className="home-search-screen" aria-hidden={h.detailHash != null}>
      <HomeResultsChrome h={h} />
      <HomeResultsBody h={h} />
    </div>
  );
}
