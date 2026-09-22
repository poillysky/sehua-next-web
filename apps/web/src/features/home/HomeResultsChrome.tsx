'use client';

import { HomeSearchField } from './HomeSearchField';
import type { HomeScreenState } from './useHomeScreen';

type Props = {
  h: HomeScreenState;
};

/** 结果页顶栏：品牌回首页 + 搜索框 */
export function HomeResultsChrome({ h }: Props) {
  return (
    <header className="home-results-header">
      <button
        type="button"
        className="home-results-brand"
        onClick={h.goLanding}
        aria-label="回资源仓库首页"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          className="home-results-brand__logo"
          src="/brand/logo.png"
          alt=""
          width={44}
          height={44}
          decoding="async"
        />
      </button>
      <HomeSearchField
        draft={h.draft}
        size="compact"
        busy={h.activeLoading && !h.activeLoadingMore}
        onDraftChange={h.setDraft}
        onSubmit={() => h.submitSearch()}
        onClear={() => {
          h.setDraft('');
          if (!h.browsing) h.goLanding();
        }}
      />
    </header>
  );
}
