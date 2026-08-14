'use client';

import { formatByteSize, parseHighlight } from '@/lib/format';

export type FileEntry = {
  index: number;
  path: string;
  size: number;
  extension?: string;
};

type FileNode = FileEntry & { type: 'file'; name: string };
type DirNode = {
  index: string;
  type: 'folder';
  name: string;
  path: string;
  children: Array<DirNode | FileNode>;
};

const EXTENSION_MAP: Record<string, string[]> = {
  folder: ['folder'],
  audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'wma', 'aac', 'mid', 'midi', 'cue'],
  image: [
    'jpg',
    'jpeg',
    'png',
    'gif',
    'bmp',
    'svg',
    'webp',
    'tiff',
    'ico',
    'heic',
    'raw',
    'psd',
    'ai',
  ],
  video: [
    'mp4',
    'mkv',
    'webm',
    'avi',
    'mov',
    'flv',
    'wmv',
    'mpeg',
    'mpg',
    '3gp',
    'm4v',
    'rm',
    'rmvb',
    'ts',
    'm2ts',
    'pmp',
  ],
  book: ['pdf', 'epub', 'fb2', 'mobi', 'azw', 'azw3', 'cbr', 'cbz', 'chm'],
  web: ['torrent', 'html', 'htm', 'php', 'url', 'asp', 'aspx', 'jsp'],
  archive: [
    'zip',
    'rar',
    '7z',
    'gz',
    'bz2',
    'tar',
    'xpi',
    'rpm',
    'cab',
    'lzh',
    'dmg',
    'z',
    'lz',
    'xz',
    'tgz',
    'tbz2',
  ],
  disk: ['iso', 'img', 'vmdk', 'vdi'],
  executable: [
    'exe',
    'msi',
    'apk',
    'deb',
    'bat',
    'sh',
    'bin',
    'dll',
    'so',
    'cmd',
    'com',
    'run',
    'vbs',
    'app',
  ],
  subtitle: ['srt', 'sub', 'ssa', 'ass', 'vtt', 'rt', 'rtx', 'smi'],
};

const VIDEO_HINT_RE =
  /(?:^|[.\s\[\(（_/|=-])(mp4|mkv|avi|wmv|rmvb|m2ts|ts|mov|flv|mpeg|mpg|m4v|webm|rm)(?:$|[.\s\]\)）_/|=-])/i;

const ARCHIVE_HINT_RE =
  /(?:^|[.\s\[\(（_/|=-])(zip|rar|7z|iso)(?:$|[.\s\]\)）_/|=-])/i;

const SKIP_NAME_RE =
  /\.(nfo|txt|url|jpg|jpeg|png|gif|webp|bmp|srt|ass|ssa|vtt)$/i;

const PADDING_NAME_RE =
  /^(_____padding_file_|\.pad\/\d+|____padding_file_)/i;

/** 列表卡片不展示小于此体积的文件（广告图等） */
export const CORE_MIN_SIZE = 100 * 1024 * 1024;

export function getFileType(extension?: string): string {
  if (!extension) return 'file';
  const e = String(extension).toLowerCase();
  if (e === 'folder') return 'folder';
  for (const [type, exts] of Object.entries(EXTENSION_MAP)) {
    if (exts.includes(e)) return type;
  }
  return 'file';
}

function hintFromText(text?: string): string {
  const blob = String(text || '');
  if (!blob.trim()) return '';
  const video = blob.match(VIDEO_HINT_RE);
  if (video) return video[1].toLowerCase().trim();
  const archive = blob.match(ARCHIVE_HINT_RE);
  if (archive) return archive[1].toLowerCase().trim();
  return '';
}

/** 从路径 / 文件名 / 标题补全扩展名（色花常把格式写在标题 [avi/1.01GB]） */
export function inferExtension(
  file: Pick<FileEntry, 'path' | 'extension'>,
  hintText?: string,
): string {
  const raw = String(file.extension || '')
    .trim()
    .replace(/^\./, '')
    .toLowerCase();
  if (raw && raw.length <= 8 && !/\s/.test(raw) && /^[a-z0-9]+$/i.test(raw)) {
    return raw;
  }
  // 全角点等
  const normalized = String(file.path || '')
    .replace(/\uFF0E/g, '.')
    .replace(/\u3002/g, '.');
  const base = normalized.split('/').pop() || normalized;
  const spaced = base.match(/\.([a-z0-9]{2,5})\s*$/i);
  if (spaced) return spaced[1].toLowerCase();
  const dot = base.match(/\.([a-z0-9]{2,5})$/i);
  if (dot) return dot[1].toLowerCase();
  const fromPath = hintFromText(base) || hintFromText(normalized);
  if (fromPath) return fromPath;
  const fromHint = hintFromText(hintText);
  if (fromHint) return fromHint;
  return '';
}

/** 取路径最后一段文件名（兼容 `/` 与 `\`） */
export function fileBaseName(path: string): string {
  const normalized = String(path || '').replace(/\\/g, '/');
  const parts = normalized.split('/').filter(Boolean);
  return parts[parts.length - 1] || normalized || '';
}

/** 对齐 Bitmagnet-Next-Web：padding / 无后缀沉底，有后缀文件先展示 */
export function sortFilesLikeBitmagnet(files: FileEntry[]): FileEntry[] {
  return [...(files || [])].sort((a, b) => {
    const aPad = PADDING_NAME_RE.test(fileBaseName(a.path)) ? 1 : 0;
    const bPad = PADDING_NAME_RE.test(fileBaseName(b.path)) ? 1 : 0;
    if (aPad !== bPad) return aPad - bPad;
    const aExt = inferExtension(a) ? 0 : 1;
    const bExt = inferExtension(b) ? 0 : 1;
    if (aExt !== bExt) return aExt - bExt;
    return (a.index || 0) - (b.index || 0);
  });
}

/** 仅使用真实可识别后缀；不再默认瞎猜 mp4 */
export function resolveDisplayExt(
  file: Pick<FileEntry, 'path' | 'extension' | 'size'>,
  hintText?: string,
): string {
  return inferExtension(file, hintText);
}

/** 展示名：有真实后缀才补上 .mkv / .mp4 等 */
export function displayFileName(
  path: string,
  extension?: string,
): string {
  const name = fileBaseName(path);
  const ext = String(extension || '')
    .trim()
    .replace(/^\./, '')
    .toLowerCase();
  if (!ext) return name;
  if (new RegExp(`\\.${ext}$`, 'i').test(name)) return name;
  if (VIDEO_HINT_RE.test(name) || ARCHIVE_HINT_RE.test(name)) return name;
  const cleaned = name.replace(/\s+/g, ' ').trim();
  return `${cleaned}.${ext}`;
}

/** 核心资源优先级：视频 > 光盘/压缩包 > 大文件；跳过图文/字幕/padding/<100MB */
export function coreFileScore(
  file: FileEntry,
  hintText?: string,
): number {
  const name = fileBaseName(file.path);
  if (PADDING_NAME_RE.test(name) || PADDING_NAME_RE.test(file.path || '')) {
    return -1;
  }
  if ((file.size || 0) < CORE_MIN_SIZE) {
    return -1;
  }
  const ext = inferExtension(file, hintText);
  // 列表核心区：必须能识别出真实后缀，避免展示「纯中文种子名」假文件
  if (!ext) return -1;
  const type = getFileType(ext || undefined);
  if (SKIP_NAME_RE.test(name) && type !== 'video' && type !== 'archive') {
    return -1;
  }
  if (type === 'video') return 1000 + Math.min(file.size || 0, 1e12) / 1e9;
  if (type === 'disk') return 800 + Math.min(file.size || 0, 1e12) / 1e9;
  if (type === 'archive') return 700 + Math.min(file.size || 0, 1e12) / 1e9;
  if (type === 'audio') return 400 + (file.size || 0) / 1e9;
  if (type === 'image' || type === 'subtitle' || type === 'web') return -1;
  return 200 + (file.size || 0) / 1e9;
}

/** 列表卡片：只保留视频等核心文件，按优先级排序 */
export function pickCoreFiles(
  files: FileEntry[],
  max = 3,
  hintText?: string,
): { core: FileEntry[]; hidden: number } {
  const list = (files || []).map((f) => ({
    ...f,
    extension: inferExtension(f, hintText) || f.extension,
  }));
  if (!list.length) return { core: [], hidden: 0 };

  const scored = list
    .map((f, i) => ({ f, i, score: coreFileScore(f, hintText) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.i - b.i);

  let picked = scored.map((x) => x.f);
  const hasVideo = picked.some(
    (f) => getFileType(inferExtension(f, hintText)) === 'video',
  );
  if (hasVideo) {
    picked = picked.filter((f) => {
      const t = getFileType(inferExtension(f, hintText));
      return t === 'video' || t === 'archive' || t === 'disk';
    });
  } else if (picked.length === 0) {
    // 绝不回退到 PNG/广告图；留空由 UI 提示进详情
    return { core: [], hidden: list.length };
  }

  const core = picked.slice(0, Math.max(1, max));
  const hidden = Math.max(0, list.length - core.length);
  return { core, hidden };
}

/** 对齐 Bitmagnet-Next-Web getSizeColor */
export function sizeTone(size: number): string {
  if (size < 1024 * 1024 * 2) return 'xs';
  if (size < 1024 * 1024 * 50) return 'sm';
  if (size < 1024 * 1024 * 200) return 'md';
  if (size < 1024 * 1024 * 1024) return 'lg';
  return 'xl';
}

export function FileTypeIcon({ extension }: { extension?: string }) {
  return (
    <span
      className="file-type-icon"
      data-icon={getFileType(extension)}
      aria-hidden
    />
  );
}

function buildTree(files: FileEntry[], maxDepth = 3): Array<DirNode | FileNode> {
  const root: DirNode = {
    index: 'root',
    type: 'folder',
    name: '',
    path: '',
    children: [],
  };
  for (const file of files) {
    const parts = (file.path || '').split('/').filter(Boolean);
    if (!parts.length) continue;
    const withExt = {
      ...file,
      extension: inferExtension(file) || file.extension,
    };
    if (parts.length === 1) {
      root.children.push({
        ...withExt,
        type: 'file',
        name: parts[0],
      });
      continue;
    }
    let cur = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (i === parts.length - 1) {
        cur.children.push({ ...withExt, type: 'file', name: part });
      } else if (i === maxDepth) {
        cur.children.push({
          ...withExt,
          type: 'file',
          name: parts.slice(i).join('/'),
          path: parts.slice(i).join('/'),
        });
        break;
      } else {
        let next = cur.children.find(
          (c): c is DirNode => c.type === 'folder' && c.name === part,
        );
        if (!next) {
          next = {
            index: `_${part}_${i}`,
            type: 'folder',
            name: part,
            path: part,
            children: [],
          };
          cur.children.push(next);
        }
        cur = next;
      }
    }
  }
  return root.children;
}

function FileRow({
  node,
  highlight,
  flat,
}: {
  node: DirNode | FileNode;
  highlight?: string | string[];
  flat?: boolean;
}) {
  const ext =
    node.type === 'folder'
      ? 'folder'
      : node.extension ||
        // 大文件无后缀：仅图标按视频示意，不伪造文件名
        ((node.size || 0) >= CORE_MIN_SIZE ? 'mp4' : undefined);
  const missingExt =
    node.type === 'file' &&
    !(node.extension || '').trim() &&
    !/\.[a-z0-9]{2,5}$/i.test(fileBaseName(node.path || node.name));

  return (
    <li className={`bm-file${flat ? ' bm-file--core' : ''}`}>
      <div className="bm-file__row">
        <FileTypeIcon extension={ext} />
        <span
          className={`bm-file__name${node.type === 'folder' ? ' is-folder' : ''}`}
          title={node.path}
          dangerouslySetInnerHTML={{
            __html: highlight
              ? parseHighlight(node.name, highlight)
              : node.name,
          }}
        />
        {missingExt ? (
          <span className="bm-file__nosuffix" title="种子元数据中该文件名无扩展名">
            无后缀
          </span>
        ) : null}
        {node.type === 'file' && node.size ? (
          <span className="bm-file__size" data-tone={sizeTone(node.size)}>
            {formatByteSize(node.size)}
          </span>
        ) : null}
      </div>
      {!flat && node.type === 'folder' && node.children.length ? (
        <ul className="bm-file__sub">
          {node.children.map((child) => (
            <FileRow
              key={
                child.type === 'folder'
                  ? child.index
                  : `${child.index}-${child.path}`
              }
              node={child}
              highlight={highlight}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** 共用文件树：类型图标 + 大小色标（色花 / Bitmagnet） */
export function TorrentFileList({
  files,
  filesCount,
  highlight,
  max = -1,
  onMore,
  /** 列表卡片：只展示视频等核心资源 */
  coreOnly = false,
  /** 标题/描述等，用于补全无扩展名文件的格式（如 [avi/1GB]） */
  hintText,
}: {
  files: FileEntry[];
  filesCount?: number | null;
  highlight?: string | string[];
  max?: number;
  onMore?: () => void;
  coreOnly?: boolean;
  hintText?: string;
}) {
  const list = sortFilesLikeBitmagnet(files || []);
  const total = filesCount ?? list.length;

  let shown: FileEntry[];
  let hidden: number;

  if (coreOnly) {
    const limit = max > 0 ? max : 3;
    const picked = pickCoreFiles(list, limit, hintText);
    shown = picked.core;
    hidden = Math.max(picked.hidden, Math.max(0, Number(total) - shown.length));
  } else {
    shown = max > 0 ? list.slice(0, max) : list;
    hidden =
      max > 0 ? Math.max(0, Math.max(list.length, Number(total) || 0) - max) : 0;
  }

  if (coreOnly) {
    if (!shown.length) {
      return (
        <div className="bm-files bm-files--core">
          <p className="bm-files__empty">未列出视频文件</p>
          {Number(total) > 0 ? (
            <button
              type="button"
              className="bm-files__more-btn"
              onClick={onMore}
            >
              共 {total} 个文件，点进详情查看…
            </button>
          ) : null}
        </div>
      );
    }
    return (
      <ul className="bm-files bm-files--core">
        {shown.map((file) => {
          const ext = resolveDisplayExt(file, hintText);
          const node: FileNode = {
            ...file,
            extension: ext || file.extension,
            type: 'file',
            name: displayFileName(file.path, ext),
          };
          return (
            <FileRow
              key={`${file.index}-${file.path}`}
              node={node}
              highlight={highlight}
              flat
            />
          );
        })}
        {hidden > 0 ? (
          <li className="bm-files__more">
            <button
              type="button"
              className="bm-files__more-btn"
              onClick={onMore}
            >
              另有 {hidden} 个文件…
            </button>
          </li>
        ) : null}
      </ul>
    );
  }

  const tree = buildTree(
    shown.map((f) => ({
      ...f,
      extension: inferExtension(f, hintText) || f.extension,
    })),
  );
  if (!tree.length) {
    return <p className="bm-files__empty">暂无文件信息</p>;
  }

  return (
    <ul className="bm-files">
      {tree.map((node) => (
        <FileRow
          key={
            node.type === 'folder' ? node.index : `${node.index}-${node.path}`
          }
          node={
            node.type === 'file'
              ? {
                  ...node,
                  name: displayFileName(node.path, node.extension),
                }
              : node
          }
          highlight={highlight}
        />
      ))}
      {hidden > 0 ? (
        <li className="bm-files__more">
          <button type="button" className="bm-files__more-btn" onClick={onMore}>
            还有 {hidden} 个文件…
          </button>
        </li>
      ) : null}
    </ul>
  );
}
