import type { BrowsePreferences } from '@/hooks/useBrowsePreferences';
import type { ResourceItem } from '@/types/resource';

function blobOf(item: ResourceItem) {
  return `${item.name || ''}\n${item.title || ''}`;
}

export function matchesChinesePrefer(item: ResourceItem): boolean {
  const board = item.board_name || '';
  const fid = item.board_fid || '';
  const name = item.name || '';
  const title = item.title || '';
  const blob = blobOf(item);

  if (board.includes('高清中文字幕')) return true;
  if (fid === '103' || fid.startsWith('103:')) return true;
  if (/-[0-9]{2,6}(CX|C)([._\s-]|$)/i.test(blob)) return true;
  if (/-C/i.test(name) || /-C/i.test(title)) return true;
  const hitZh =
    name.includes('字幕') ||
    title.includes('字幕') ||
    name.includes('中文') ||
    title.includes('中文');
  const noSub = name.includes('无字幕') || title.includes('无字幕');
  return hitZh && !noSub;
}

export function matchesCrackPrefer(item: ResourceItem): boolean {
  const board = item.board_name || '';
  const fid = item.board_fid || '';
  const name = item.name || '';
  const title = item.title || '';
  const blob = blobOf(item);

  if (fid === '103:481') return true;
  if (
    /无码高清|無碼高清|高清中文字幕.*无码|高清中文字幕.*無碼|无码破解|無碼破解|无码流出|無碼流出/.test(
      board,
    )
  ) {
    return true;
  }
  if (/-[0-9]{2,6}(CX|UC|U)([._\s-]|$)/i.test(blob)) return true;
  if (/-U|_U/i.test(name) || /-U|_U/i.test(title)) return true;
  if (
    /破解|马赛克破坏|馬賽克破壞/.test(name) ||
    /破解|马赛克破坏|馬賽克破壞/.test(title)
  ) {
    return true;
  }
  return false;
}

/** 在无倾向底池上套中文/破解（可叠加） */
export function filterByBrowsePrefs(
  resources: ResourceItem[],
  prefs: BrowsePreferences,
): ResourceItem[] {
  let list = resources;
  if (prefs.preferChinese) list = list.filter(matchesChinesePrefer);
  if (prefs.preferCrack) list = list.filter(matchesCrackPrefer);
  return list;
}
