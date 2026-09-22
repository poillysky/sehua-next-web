'use client';

import type { Dispatch, SetStateAction } from 'react';
import { ChevronRight, Search, X } from 'lucide-react';
import type {
  MakerCatalogSourceId,
  ScrapLibraryEmbedFacet,
  ScrapLibraryEmbedItem,
  ScrapLibraryEmbedPrefix,
} from '@/lib/api';
import { AppPush } from '@/components/ui/AppPush';
import { SEARCH_KEYWORD_LENGTH_MIN } from '@/config/search';
import { makerSourceLabel } from './makersUi';
import type { Stack } from './makersTypes';
import { MakersItemWall } from './MakersItemWall';

export function MakersSearchPush({
  hubTab,
  searchDraft,
  setSearchDraft,
  searchHits,
  searchStudios,
  searchPrefixes,
  searchLoading,
  searchDone,
  runSemanticSearch,
  clearSearchResults,
  setStack,
  openItem,
}: {
  hubTab: MakerCatalogSourceId;
  searchDraft: string;
  setSearchDraft: (v: string) => void;
  searchHits: ScrapLibraryEmbedItem[];
  searchStudios: ScrapLibraryEmbedFacet[];
  searchPrefixes: ScrapLibraryEmbedPrefix[];
  searchLoading: boolean;
  searchDone: boolean;
  runSemanticSearch: (raw: string) => void | Promise<void>;
  clearSearchResults: () => void;
  setStack: Dispatch<SetStateAction<Stack>>;
  openItem: (item: ScrapLibraryEmbedItem) => void;
}) {
  const searchQuery = searchDraft.trim();
  const searchNavTotal =
    searchStudios.length + searchPrefixes.length + searchHits.length;
  const searchStatusParts = [
    searchStudios.length ? `${searchStudios.length} 厂牌` : '',
    searchPrefixes.length ? `${searchPrefixes.length} 前缀` : '',
    searchHits.length ? `${searchHits.length} 影片` : '',
  ].filter(Boolean);

  return (
    <AppPush
      title="搜索"
      scrollKey={`makers-search-${hubTab}`}
      onBack={() => {
        clearSearchResults();
        setStack({ kind: 'hub' });
      }}
      skipEnterAnimation
    >
      <div className="makers-search-panel">
        <form
          className="makers-search"
          onSubmit={(e) => {
            e.preventDefault();
            void runSemanticSearch(searchDraft);
          }}
        >
          <label className="makers-search__field">
            <Search
              className="makers-search__icon"
              size={17}
              strokeWidth={2.25}
              aria-hidden
            />
            <input
              className="makers-search__input"
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder={`${makerSourceLabel(hubTab)} · 番号 / 厂牌 / 前缀`}
              autoFocus
              enterKeyHint="search"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
            />
            {searchDraft ? (
              <button
                type="button"
                className="makers-search__clear"
                aria-label="清除"
                onClick={() => {
                  setSearchDraft('');
                  clearSearchResults();
                }}
              >
                <X size={15} strokeWidth={2.35} aria-hidden />
              </button>
            ) : null}
          </label>
          <button
            type="submit"
            className="makers-search__go"
            disabled={
              searchLoading || searchQuery.length < SEARCH_KEYWORD_LENGTH_MIN
            }
          >
            {searchLoading ? '…' : '搜索'}
          </button>
        </form>

        {searchLoading || (searchDone && searchNavTotal > 0) ? (
          <p className="makers-search__status allow-select" aria-live="polite">
            {searchLoading ? '搜索中…' : searchStatusParts.join(' · ')}
          </p>
        ) : null}

        {!searchLoading && !searchDone && searchNavTotal === 0 ? (
          <div className="makers-search-empty allow-select">
            <span className="makers-search-empty__icon" aria-hidden>
              <Search size={28} strokeWidth={1.75} />
            </span>
            <p className="makers-search-empty__title">搜番号、厂牌或前缀</p>
            <p className="makers-search-empty__hint">
              例如 SSIS-001、S1、SSIS
            </p>
          </div>
        ) : !searchLoading && searchDone && searchNavTotal === 0 ? (
          <div className="makers-search-empty allow-select">
            <span className="makers-search-empty__icon" aria-hidden>
              <Search size={28} strokeWidth={1.75} />
            </span>
            <p className="makers-search-empty__title">无匹配结果</p>
            <p className="makers-search-empty__hint">换个关键字再试试</p>
          </div>
        ) : (
          <div className="makers-search-results">
            {searchStudios.length > 0 ? (
              <section className="makers-search-nav">
                <h3 className="makers-search-nav__title">厂牌</h3>
                <ul className="makers-prefix-list">
                  {searchStudios.map((s) => (
                    <li key={`studio-${s.name}`}>
                      <button
                        type="button"
                        className="makers-prefix-list__row"
                        onClick={() =>
                          setStack({
                            kind: 'folderStudio',
                            studio: s.name,
                          })
                        }
                      >
                        <span className="makers-prefix-list__main">
                          <span className="makers-prefix-list__prefix">
                            {s.name}
                          </span>
                          {s.blurb ? (
                            <span className="makers-prefix-list__maker">
                              {s.blurb}
                            </span>
                          ) : null}
                        </span>
                        <span className="makers-search-nav__count allow-select">
                          {s.count}
                        </span>
                        <ChevronRight size={16} strokeWidth={2.2} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {searchPrefixes.length > 0 ? (
              <section className="makers-search-nav">
                <h3 className="makers-search-nav__title">前缀</h3>
                <ul className="makers-prefix-list">
                  {searchPrefixes.map((p) => {
                    const studio = String(p.studio || p.prefix || '').trim();
                    return (
                      <li key={`prefix-${p.prefix}`}>
                        <button
                          type="button"
                          className="makers-prefix-list__row"
                          onClick={() =>
                            setStack({
                              kind: 'folderPrefix',
                              studio: studio || p.prefix,
                              prefix: p.prefix,
                            })
                          }
                        >
                          <span className="makers-prefix-list__main">
                            <span className="makers-prefix-list__prefix">
                              {p.prefix}
                            </span>
                            {p.studio || p.blurb ? (
                              <span className="makers-prefix-list__maker">
                                {p.studio || p.blurb}
                              </span>
                            ) : null}
                          </span>
                          <span className="makers-search-nav__count allow-select">
                            {p.count}
                          </span>
                          <ChevronRight
                            size={16}
                            strokeWidth={2.2}
                            aria-hidden
                          />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}
            {searchHits.length > 0 || searchLoading ? (
              <section className="makers-search-nav">
                {searchStudios.length > 0 || searchPrefixes.length > 0 ? (
                  <h3 className="makers-search-nav__title">影片</h3>
                ) : null}
                <MakersItemWall
                  items={searchHits}
                  empty="无匹配结果"
                  loading={searchLoading}
                  region={hubTab}
                  onOpenItem={openItem}
                />
              </section>
            ) : null}
          </div>
        )}
      </div>
    </AppPush>
  );
}
