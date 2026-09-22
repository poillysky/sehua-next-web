'use client';

export function MakersPager({
  page,
  totalPages,
  onPrev,
  onNext,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="media-chart__pager">
      <button
        type="button"
        className="media-chart__page-btn"
        disabled={page <= 1}
        onClick={onPrev}
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
        onClick={onNext}
      >
        下一页
      </button>
    </div>
  );
}
