'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import {
  fetchMediaDiscover,
  fetchMediaGenres,
  type MediaGenre,
  type MediaItem,
} from '@/lib/api';
import { MediaPosterCard } from './MediaPosterCard';
import { cn } from '@/lib/utils';

type MediaKind = 'movie' | 'tv';

const KINDS: Array<{ id: MediaKind; label: string }> = [
  { id: 'movie', label: '电影' },
  { id: 'tv', label: '电视剧' },
];

const SORT_MOVIE: Array<{ id: string; label: string }> = [
  { id: 'popularity.desc', label: '热门' },
  { id: 'vote_average.desc', label: '高分' },
  { id: 'primary_release_date.desc', label: '最新' },
  { id: 'revenue.desc', label: '票房' },
  { id: 'vote_count.desc', label: '热议' },
];

const SORT_TV: Array<{ id: string; label: string }> = [
  { id: 'popularity.desc', label: '热门' },
  { id: 'vote_average.desc', label: '高分' },
  { id: 'first_air_date.desc', label: '最新' },
  { id: 'vote_count.desc', label: '热议' },
];

function buildYearOptions(): Array<{ id: string; label: string }> {
  const y = new Date().getFullYear();
  const out: Array<{ id: string; label: string }> = [{ id: '', label: '全部' }];
  for (let i = 0; i < 5; i += 1) {
    out.push({ id: String(y - i), label: String(y - i) });
  }
  return out;
}

function ChipRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="media-explore__block">
      <p className="media-explore__label">{label}</p>
      <div className="media-explore__row" role="tablist" aria-label={label}>
        {children}
      </div>
    </div>
  );
}

export function MediaExploreBody({
  onOpen,
}: {
  onOpen: (item: MediaItem) => void;
}) {
  const [mediaType, setMediaType] = useState<MediaKind>('movie');
  const [genre, setGenre] = useState('');
  const [sortBy, setSortBy] = useState('popularity.desc');
  const [year, setYear] = useState('');
  const [genres, setGenres] = useState<MediaGenre[]>([]);
  const [items, setItems] = useState<MediaItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const [loading, setLoading] = useState(true);
  const [genresLoading, setGenresLoading] = useState(true);
  const [err, setErr] = useState('');

  const sorts = mediaType === 'movie' ? SORT_MOVIE : SORT_TV;
  const years = buildYearOptions();
  const genreName = genre
    ? genres.find((g) => String(g.id) === genre)?.name || null
    : null;

  useEffect(() => {
    let cancelled = false;
    setGenresLoading(true);
    void (async () => {
      try {
        const list = await fetchMediaGenres({ mediaType });
        if (cancelled) return;
        setGenres(list);
        setGenre('');
      } catch {
        if (!cancelled) setGenres([]);
      } finally {
        if (!cancelled) setGenresLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mediaType]);

  useEffect(() => {
    const allowed = (mediaType === 'movie' ? SORT_MOVIE : SORT_TV).map((s) => s.id);
    if (!allowed.includes(sortBy)) {
      setSortBy(allowed[0] || 'popularity.desc');
    }
    setPage(1);
  }, [mediaType]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const data = await fetchMediaDiscover({
        mediaType,
        genre: genre || undefined,
        sortBy,
        year: year || undefined,
        page,
      });
      setItems(data.items || []);
      setTotalPages(Math.max(1, Number(data.totalPages || 1)));
      setTotalResults(Math.max(0, Number(data.totalResults || 0)));
    } catch (e) {
      setItems([]);
      setTotalResults(0);
      setErr(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [mediaType, genre, sortBy, year, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const sortLabel = sorts.find((s) => s.id === sortBy)?.label || '热门';

  return (
    <div className="media-explore">
      <div className="media-explore__filters">
        <div className="media-explore__seg" role="tablist" aria-label="类型">
          {KINDS.map((k) => (
            <button
              key={k.id}
              type="button"
              role="tab"
              aria-selected={mediaType === k.id}
              className={cn(
                'media-explore__seg-btn',
                mediaType === k.id && 'is-active',
              )}
              onClick={() => {
                setMediaType(k.id);
                setPage(1);
              }}
            >
              {k.label}
            </button>
          ))}
        </div>

        <ChipRow label="排序">
          {sorts.map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={sortBy === s.id}
              className={cn('media-explore__chip', sortBy === s.id && 'is-active')}
              onClick={() => {
                setSortBy(s.id);
                setPage(1);
              }}
            >
              {s.label}
            </button>
          ))}
        </ChipRow>

        <ChipRow label="年份">
          {years.map((y) => (
            <button
              key={y.id || 'all'}
              type="button"
              role="tab"
              aria-selected={year === y.id}
              className={cn('media-explore__chip', year === y.id && 'is-active')}
              onClick={() => {
                setYear(y.id);
                setPage(1);
              }}
            >
              {y.label}
            </button>
          ))}
        </ChipRow>

        <ChipRow label="题材">
          <button
            type="button"
            role="tab"
            aria-selected={!genre}
            className={cn('media-explore__chip', !genre && 'is-active')}
            onClick={() => {
              setGenre('');
              setPage(1);
            }}
          >
            全部
          </button>
          {genresLoading
            ? Array.from({ length: 8 }).map((_, i) => (
                <span key={i} className="media-explore__chip-skel" aria-hidden />
              ))
            : genres.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  role="tab"
                  aria-selected={genre === String(g.id)}
                  className={cn(
                    'media-explore__chip',
                    genre === String(g.id) && 'is-active',
                  )}
                  onClick={() => {
                    setGenre(String(g.id));
                    setPage(1);
                  }}
                >
                  {g.name}
                </button>
              ))}
        </ChipRow>
      </div>

      <div className="media-explore__meta">
        <span className="media-explore__meta-text allow-select">
          {[
            mediaType === 'movie' ? '电影' : '电视剧',
            sortLabel,
            year || null,
            genreName,
            !loading && totalResults > 0 ? `${totalResults.toLocaleString('zh-CN')} 部` : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>

      {loading ? (
        <div className="media-wall media-wall--skel" aria-hidden>
          {Array.from({ length: 9 }).map((_, i) => (
            <span key={i} className="media-poster-skel media-poster-skel--wall" />
          ))}
        </div>
      ) : null}

      {!loading && err ? <p className="media-empty allow-select">{err}</p> : null}

      {!loading && !err && items.length === 0 ? (
        <p className="media-empty">没有符合筛选的结果</p>
      ) : null}

      {!loading && !err && items.length > 0 ? (
        <div className="media-wall">
          {items.map((item) => (
            <MediaPosterCard
              key={`${item.source}-${item.id}`}
              item={item}
              category={mediaType}
              size="md"
              onClick={() => onOpen(item)}
            />
          ))}
        </div>
      ) : null}

      {!loading && !err && totalPages > 1 ? (
        <div className="media-chart__pager">
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span className="media-chart__page-meta">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="media-chart__page-btn"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
