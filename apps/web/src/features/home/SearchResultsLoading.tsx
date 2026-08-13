/** 搜索首屏：转圈文案 + 资源行骨架 */
export function SearchResultsLoading({
  keyword,
  skeletonCount = 4,
}: {
  keyword?: string;
  skeletonCount?: number;
}) {
  const kw = String(keyword || '').trim();
  return (
    <div className="search-loading" aria-live="polite" aria-busy="true">
      <div className="search-loading__status">
        <span className="search-loading__spinner" aria-hidden />
        <span className="search-loading__text">
          正在搜索
          {kw ? (
            <>
              「
              <span className="search-loading__kw allow-select">{kw}</span>
              」
            </>
          ) : null}
          <span className="search-loading__dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
        </span>
      </div>
      <div className="search-skeleton" aria-hidden>
        {Array.from({ length: skeletonCount }, (_, i) => (
          <div
            key={i}
            className="search-skeleton__card"
            style={{ animationDelay: `${i * 90}ms` }}
          >
            <div className="search-skeleton__cover" />
            <div className="search-skeleton__body">
              <div className="search-skeleton__line search-skeleton__line--title" />
              <div className="search-skeleton__line search-skeleton__line--meta" />
              <div className="search-skeleton__line search-skeleton__line--short" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
