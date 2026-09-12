'use client';

import { useEffect, useRef } from 'react';

function scrollLogToEnd(list: HTMLElement) {
  if (list.scrollHeight > list.clientHeight + 1) {
    list.scrollTop = list.scrollHeight;
    return;
  }
  let p: HTMLElement | null = list.parentElement;
  while (p) {
    const oy = getComputedStyle(p).overflowY;
    if (
      (oy === 'auto' || oy === 'scroll' || oy === 'overlay') &&
      p.scrollHeight > p.clientHeight + 1
    ) {
      p.scrollTop = p.scrollHeight;
      return;
    }
    p = p.parentElement;
  }
}

/** 日志列表：有新行或重新打开时滚到最新 */
export function AutoscrollLogList({
  lines,
  className,
  empty = '暂无日志',
  active = true,
}: {
  lines: string[];
  className?: string;
  empty?: string;
  /** 弹层打开时为 true，用于首次滚到底 */
  active?: boolean;
}) {
  const listRef = useRef<HTMLUListElement>(null);
  const lastLine = lines.length ? lines[lines.length - 1] : '';

  useEffect(() => {
    if (!active) return;
    const list = listRef.current;
    if (!list) return;
    const run = () => scrollLogToEnd(list);
    run();
    const id = requestAnimationFrame(run);
    return () => cancelAnimationFrame(id);
  }, [active, lines.length, lastLine]);

  return (
    <ul ref={listRef} className={className}>
      {lines.length === 0 ? (
        <li className="makers-manage__scan-log-modal--empty">{empty}</li>
      ) : (
        lines.map((line, i) => <li key={`${i}-${line}`}>{line}</li>)
      )}
    </ul>
  );
}
