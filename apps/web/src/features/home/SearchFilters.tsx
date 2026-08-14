"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { SEARCH_PARAMS } from "@/config/search";
import type {
  FilterSize,
  FilterTime,
  MatchMode,
  SortType,
} from "@/types/resource";
import type { SearchSource } from "./SourceSwitch";

const SOURCE_LABEL: Record<SearchSource, string> = {
  sehua: "色花堂",
  bitmagnet: "Bt",
};

type FilterKey = "sort" | "match" | "time" | "size";

const SORT_LABEL: Record<(typeof SEARCH_PARAMS.sortType)[number], string> = {
  // Bitmagnet：default = 时间倒序（已取消 relevance 打分）
  default: "默认",
  date: "最新",
  size: "大小",
  count: "文件数",
};
const MATCH_LABEL: Record<(typeof SEARCH_PARAMS.matchMode)[number], string> = {
  smart: "智能",
  exact: "精确",
  fuzzy: "模糊",
};
const TIME_LABEL: Record<(typeof SEARCH_PARAMS.filterTime)[number], string> = {
  all: "不限",
  "gt-1day": "1 天内",
  "gt-7day": "7 天内",
  "gt-31day": "31 天内",
  "gt-365day": "1 年内",
};
const SIZE_LABEL: Record<(typeof SEARCH_PARAMS.filterSize)[number], string> = {
  all: "不限",
  lt100mb: "<100MB",
  "gt100mb-lt500mb": "100–500MB",
  "gt500mb-lt1gb": "500MB–1GB",
  "gt1gb-lt5gb": "1–5GB",
  gt5gb: ">5GB",
};

const SORT_OPTS = SEARCH_PARAMS.sortType.map((value) => ({
  value,
  label: SORT_LABEL[value],
}));
const MATCH_OPTS = SEARCH_PARAMS.matchMode.map((value) => ({
  value,
  label: MATCH_LABEL[value],
}));
const TIME_OPTS = SEARCH_PARAMS.filterTime.map((value) => ({
  value,
  label: TIME_LABEL[value],
}));
const SIZE_OPTS = SEARCH_PARAMS.filterSize.map((value) => ({
  value,
  label: SIZE_LABEL[value],
}));

function pick(
  opts: readonly { value: string; label: string }[],
  value: string,
) {
  return opts.find((o) => o.value === value)?.label ?? value;
}

export function SearchFilters({
  sortType,
  matchMode,
  filterTime,
  filterSize,
  onSortType,
  onMatchMode,
  onFilterTime,
  onFilterSize,
  showMatch = true,
  searchSource,
  onSearchSourceChange,
  showSource = false,
}: {
  sortType: SortType;
  matchMode: MatchMode;
  filterTime: FilterTime;
  filterSize: FilterSize;
  onSortType: (v: SortType) => void;
  onMatchMode: (v: MatchMode) => void;
  onFilterTime: (v: FilterTime) => void;
  onFilterSize: (v: FilterSize) => void;
  showMatch?: boolean;
  searchSource?: SearchSource;
  onSearchSourceChange?: (v: SearchSource) => void;
  showSource?: boolean;
}) {
  const [open, setOpen] = useState<FilterKey | null>(null);
  const [menuBox, setMenuBox] = useState<CSSProperties | null>(null);
  const triggerRefs = useRef<
    Partial<Record<FilterKey, HTMLButtonElement | null>>
  >({});

  const cells: {
    key: FilterKey;
    fieldLabel: string;
    text: string;
  }[] = [
    { key: "sort", fieldLabel: "排序", text: pick(SORT_OPTS, sortType) },
    ...(showMatch
      ? [{ key: "match" as const, fieldLabel: "匹配", text: pick(MATCH_OPTS, matchMode) }]
      : []),
    { key: "size", fieldLabel: "大小", text: pick(SIZE_OPTS, filterSize) },
    { key: "time", fieldLabel: "时间", text: pick(TIME_OPTS, filterTime) },
  ];

  const menu = useMemo(() => {
    if (open === "sort") {
      return {
        title: "排序",
        current: sortType,
        opts: SORT_OPTS,
        set: onSortType as (v: string) => void,
      };
    }
    if (open === "match") {
      return {
        title: "匹配",
        current: matchMode,
        opts: MATCH_OPTS,
        set: onMatchMode as (v: string) => void,
      };
    }
    if (open === "time") {
      return {
        title: "时间",
        current: filterTime,
        opts: TIME_OPTS,
        set: onFilterTime as (v: string) => void,
      };
    }
    if (open === "size") {
      return {
        title: "大小",
        current: filterSize,
        opts: SIZE_OPTS,
        set: onFilterSize as (v: string) => void,
      };
    }
    return null;
  }, [
    open,
    sortType,
    matchMode,
    filterTime,
    filterSize,
    onSortType,
    onMatchMode,
    onFilterTime,
    onFilterSize,
  ]);

  const placeMenu = (key: FilterKey) => {
    const btn = triggerRefs.current[key];
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const width = Math.min(120, Math.max(88, r.width * 0.92));
    const left = Math.max(
      8,
      Math.min(r.left + (r.width - width) / 2, window.innerWidth - width - 8),
    );
    setMenuBox({
      position: "fixed",
      top: r.bottom + 4,
      left,
      width,
      zIndex: 120,
    });
  };

  useLayoutEffect(() => {
    if (!open) {
      setMenuBox(null);
      return;
    }
    placeMenu(open);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const place = () => placeMenu(open);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      const btn = open ? triggerRefs.current[open] : null;
      const menuEl = document.getElementById("filters-bm-portal-menu");
      if (btn?.contains(t) || menuEl?.contains(t)) return;
      setOpen(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    const t = window.setTimeout(() => {
      window.addEventListener("pointerdown", onPointer, true);
    }, 0);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("pointerdown", onPointer, true);
    };
  }, [open]);

  function toggle(key: FilterKey) {
    setOpen((cur) => (cur === key ? null : key));
  }

  const portal =
    typeof document !== "undefined" && menu && menuBox
      ? createPortal(
          <div
            id="filters-bm-portal-menu"
            className="filters-bm__menu"
            style={menuBox}
            role="listbox"
            aria-label={menu.title}
          >
            <div className="filters-bm__menu-card">
              {menu.opts.map((o) => {
                const selected = o.value === menu.current;
                return (
                  <button
                    key={o.value}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`filters-bm__opt${selected ? " is-selected" : ""}`}
                    onClick={() => {
                      menu.set(o.value);
                      setOpen(null);
                    }}
                  >
                    <span className="filters-bm__opt-label">{o.label}</span>
                    {selected ? (
                      <Check
                        className="filters-bm__check"
                        size={16}
                        strokeWidth={2.25}
                        aria-hidden
                      />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div
      className={[
        "filters-bm",
        showMatch ? "" : "filters-bm--3",
        showSource ? "filters-bm--with-source" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label="筛选"
    >
      {showSource && searchSource != null && onSearchSourceChange ? (
        <div className="filters-bm__field">
          <button
            type="button"
            className="filters-bm__trigger filters-bm__trigger--toggle"
            aria-label="切换搜索来源"
            onClick={() =>
              onSearchSourceChange(
                searchSource === "sehua" ? "bitmagnet" : "sehua",
              )
            }
          >
            <span className="filters-bm__label">来源</span>
            <span className="filters-bm__value-row">
              <span className="filters-bm__value">
                {SOURCE_LABEL[searchSource]}
              </span>
            </span>
          </button>
        </div>
      ) : null}
      {cells.map((c) => {
        const expanded = open === c.key;
        return (
          <div
            key={c.key}
            className={`filters-bm__field${expanded ? " is-open" : ""}`}
          >
            <button
              type="button"
              ref={(el) => {
                triggerRefs.current[c.key] = el;
              }}
              className="filters-bm__trigger"
              aria-expanded={expanded}
              aria-haspopup="listbox"
              onClick={() => toggle(c.key)}
            >
              <span className="filters-bm__label">{c.fieldLabel}</span>
              <span className="filters-bm__value-row">
                <span className="filters-bm__value">{c.text}</span>
                <ChevronDown
                  className="filters-bm__chev"
                  size={14}
                  strokeWidth={2}
                  aria-hidden
                />
              </span>
            </button>
          </div>
        );
      })}
      {portal}
    </div>
  );
}
