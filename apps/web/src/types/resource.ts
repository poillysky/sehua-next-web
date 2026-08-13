export type ResourceFile = {
  index: number;
  path: string;
  size: number;
  extension?: string;
};

export type ResourceItem = {
  hash: string;
  name: string;
  title?: string | null;
  description?: string | null;
  source_url?: string | null;
  board_fid?: string | null;
  board_name?: string | null;
  forum_id?: string | null;
  forum_name?: string | null;
  extract_password?: string | null;
  preview_images: string[];
  ed2k_links: string[];
  size: number;
  ed2k_link: string;
  link_kind: string;
  single_file: boolean;
  files_count: number;
  files: ResourceFile[];
  created_at: number;
  updated_at: number;
};

export type BrowseResult = {
  resources: ResourceItem[];
  total_count: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export type SearchResult = {
  keywords: string[];
  resources: ResourceItem[];
  total_count: number;
  has_more: boolean;
  page: number;
  page_size: number;
  match_mode?: MatchMode;
};

export type SortType = 'default' | 'size' | 'count' | 'date';
export type MatchMode = 'smart' | 'exact' | 'fuzzy';
export type FilterTime =
  | 'all'
  | 'gt-1day'
  | 'gt-7day'
  | 'gt-31day'
  | 'gt-365day';
export type FilterSize =
  | 'all'
  | 'lt100mb'
  | 'gt100mb-lt500mb'
  | 'gt500mb-lt1gb'
  | 'gt1gb-lt5gb'
  | 'gt5gb';

export type BoardNavCategory = {
  category: string;
  parents: Array<{
    name: string;
    fid?: string;
    children?: Array<{ name: string; fid?: string; search_keyword?: string }>;
  }>;
};

export type AuthUser = {
  id: number;
  username: string;
  is_admin?: boolean;
  created_at?: string;
};

export type ResourceDbConfig = {
  enabled: boolean;
  dsn: string;
  note: string;
  configured?: boolean;
};
