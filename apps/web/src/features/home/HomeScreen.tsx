'use client';

import { AppPush } from '@/components/ui/AppPush';
import { P115PastePanel } from './P115PastePanel';
import { AiSearchChatPanel } from './AiSearchChatPanel';
import { BoardsScreen } from '@/features/boards/BoardsScreen';
import { ResourceDetailBody } from './ResourceDetailBody';
import { BitmagnetDetailBody } from '@/features/magnet/BitmagnetDetailBody';
import { useHomeScreen } from './useHomeScreen';
import { HomeLanding } from './HomeLanding';
import { HomeResults } from './HomeResults';

/**
 * 搜索页 — 色花堂 / Bitmagnet 分来源；仅当前来源发起搜索，切换后再搜另一库
 * 影视入口优先 Bitmagnet，片商入口优先色花堂
 */
export function HomeScreen() {
  const h = useHomeScreen();

  return (
    <div className="app-stack-root">
      <div {...h.mainCover}>
        {h.mode === 'landing' ? <HomeLanding h={h} /> : <HomeResults h={h} />}
      </div>

      {h.detailHash ? (
        <AppPush
          title="详情"
          scrollKey={`home-detail-${h.detailSource}-${h.detailHash}`}
          scrollMode="top"
          onBack={h.closeDetail}
        >
          {h.detailSource === 'bitmagnet' ? (
            <BitmagnetDetailBody hash={h.detailHash} />
          ) : (
            <ResourceDetailBody hash={h.detailHash} />
          )}
        </AppPush>
      ) : null}

      {h.pasteOpen ? <P115PastePanel onBack={() => h.setPasteOpen(false)} /> : null}
      {h.chatOpen ? <AiSearchChatPanel onBack={() => h.setChatOpen(false)} /> : null}
      {h.boardsOpen ? (
        <BoardsScreen onClose={() => h.setBoardsOpen(false)} />
      ) : null}
    </div>
  );
}
