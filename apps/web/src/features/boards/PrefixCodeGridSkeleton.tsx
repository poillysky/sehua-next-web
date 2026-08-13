import { findMakerByPrefix, resolveCoverDisplay } from '@/config/av-makers';

/** 番号前缀网格骨架 */
export function PrefixCodeGridSkeleton({
  prefix,
  count = 12,
}: {
  prefix?: string;
  count?: number;
}) {
  const display = findMakerByPrefix(prefix || '')
    ? resolveCoverDisplay(prefix || '')
    : resolveCoverDisplay('');

  return (
    <div
      className="prefix-grid"
      data-cols={display.preferLandscape ? '2' : '3'}
      aria-busy
      aria-hidden
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="prefix-tile prefix-tile--skeleton">
          <span
            className="prefix-tile__media"
            style={{ aspectRatio: display.aspectRatio }}
          >
            <span className="prefix-tile__skel" />
            <span className="prefix-tile__skel-code" />
          </span>
          <span className="prefix-tile__meta">
            <span className="prefix-tile__skel-title" />
          </span>
        </div>
      ))}
    </div>
  );
}
