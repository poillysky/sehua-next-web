const SOURCE_DISPLAY: Record<string, string> = {
  mdcx_c_number: '色花堂',
  local_code_title: '色花堂',
};

export function sourceIconMeta(source: string): {
  id: string;
  label: string;
  hue: number;
} {
  const id = String(source || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_');
  let hue = 210;
  for (let i = 0; i < id.length; i += 1) hue = (hue + id.charCodeAt(i) * 17) % 360;
  return {
    id,
    label: SOURCE_DISPLAY[id] || id || '—',
    hue,
  };
}

export function displayHitSource(source?: string): string {
  const s = String(source || '').trim();
  if (
    !s ||
    s === 'log_recover' ||
    s === 'recover' ||
    s === 'local_scan' ||
    s === 'scan'
  ) {
    return '';
  }
  return s;
}
