/** 一会能直连、一会要过盾的不稳定站（实测自适应） */
export const ADAPTIVE_FLARE_SOURCE_IDS = new Set<string>([
  "airav_io",
  "airav",
  "sevenmmtv",
  "avbase",
  "mgstage",
]);

export function isAdaptiveFlareSource(sourceId?: string | null): boolean {
  const id = String(sourceId || "")
    .trim()
    .toLowerCase();
  return Boolean(id) && ADAPTIVE_FLARE_SOURCE_IDS.has(id);
}
