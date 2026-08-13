import type {
  FilterSize,
  FilterTime,
  MatchMode,
  SortType,
} from "@/types/resource";

export const SEARCH_PARAMS = {
  sortType: ["default", "size", "count", "date"] as const,
  filterTime: [
    "all",
    "gt-1day",
    "gt-7day",
    "gt-31day",
    "gt-365day",
  ] as const,
  filterSize: [
    "all",
    "lt100mb",
    "gt100mb-lt500mb",
    "gt500mb-lt1gb",
    "gt1gb-lt5gb",
    "gt5gb",
  ] as const,
  matchMode: ["smart", "exact", "fuzzy"] as const,
};

export const DEFAULT_SORT_TYPE: SortType = "default";
export const DEFAULT_FILTER_TIME: FilterTime = "all";
export const DEFAULT_FILTER_SIZE: FilterSize = "all";
export const DEFAULT_MATCH_MODE: MatchMode = "smart";
export const SEARCH_PAGE_SIZE = 10;
export const SEARCH_KEYWORD_LENGTH_MIN = 2;
/** 番号搜索底池一次拉取上限（无中文/破解，客户端再 filter） */
export const CODE_SEARCH_POOL_SIZE = 80;
/** 前缀番号网格每页条数 */
export const PREFIX_CODE_PAGE_SIZE = 60;
/** 前缀翻页上限 */
export const BROWSE_PAGE_MAX = 5000;

export function normalizeSortType(v?: string | null): SortType {
  if (v && (SEARCH_PARAMS.sortType as readonly string[]).includes(v)) {
    return v as SortType;
  }
  return DEFAULT_SORT_TYPE;
}

export function normalizeMatchMode(v?: string | null): MatchMode {
  if (v && (SEARCH_PARAMS.matchMode as readonly string[]).includes(v)) {
    return v as MatchMode;
  }
  return DEFAULT_MATCH_MODE;
}

export function normalizeFilterTime(v?: string | null): FilterTime {
  if (v && (SEARCH_PARAMS.filterTime as readonly string[]).includes(v)) {
    return v as FilterTime;
  }
  return DEFAULT_FILTER_TIME;
}

export function normalizeFilterSize(v?: string | null): FilterSize {
  if (v && (SEARCH_PARAMS.filterSize as readonly string[]).includes(v)) {
    return v as FilterSize;
  }
  return DEFAULT_FILTER_SIZE;
}
