import fs from "node:fs";

export type PosterCropMode = "right" | "none" | "face";
export type PosterCropRatioId = "full" | "emby";

export type PosterCropConfig = {
  byKind?: Record<string, PosterCropMode | string>;
  ratio?: PosterCropRatioId | string;
  /** 对已刮到的竖版/高清海报也做中心裁剪以统一比例 */
  cropDownloadedPoster?: boolean;
  /** 缩略图裁剪结果分辨率更高时优先用裁剪 */
  preferCropIfBetter?: boolean;
};

/** 读 JPEG 宽高；失败返回 null（只读文件头，避免整图进内存） */
export function readJpegSize(
  filePath: string,
): { width: number; height: number } | null {
  try {
    const fd = fs.openSync(filePath, "r");
    try {
      const buf = Buffer.alloc(65536);
      const n = fs.readSync(fd, buf, 0, buf.length, 0);
      if (n < 100 || buf[0] !== 0xff || buf[1] !== 0xd8) return null;
      let i = 2;
      while (i < n - 9) {
        if (buf[i] !== 0xff) {
          i += 1;
          continue;
        }
        const marker = buf[i + 1]!;
        if (marker === 0xd9 || marker === 0xda) break;
        const len = (buf[i + 2]! << 8) | buf[i + 3]!;
        if (marker >= 0xc0 && marker <= 0xc3) {
          const height = (buf[i + 5]! << 8) | buf[i + 6]!;
          const width = (buf[i + 7]! << 8) | buf[i + 8]!;
          return { width, height };
        }
        i += 2 + len;
      }
      return null;
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return null;
  }
}

export function resolveCropRatio(ratioId?: string | null): number {
  const id = String(ratioId || "full").toLowerCase();
  if (id === "emby" || id === "2/3" || id === "2:3") return 2 / 3;
  return 2.12 / 3;
}

export function resolveCropMode(
  cfg: PosterCropConfig | undefined,
  kind: string | undefined,
): PosterCropMode {
  const raw = String(cfg?.byKind?.[kind || ""] || "").toLowerCase();
  if (raw === "none" || raw === "no" || raw === "skip") return "none";
  if (raw === "face" || raw === "ai" || raw === "attention") return "face";
  if (raw === "right" || raw === "right_crop") return "right";
  // 七区默认
  if (kind === "japan_amateur" || kind === "fc2") return "face";
  if (
    kind === "japan_uncensored" ||
    kind === "china" ||
    kind === "western"
  ) {
    return "none";
  }
  return "right";
}

/**
 * 从横向 pl 右侧裁出竖版海报（约 2:3），对齐 mdc-ng。
 * 依赖 sharp；失败返回 false。
 */
export async function cropPosterFromLandscapeJpeg(
  srcPath: string,
  destPath: string,
  opts?: { ratio?: number },
): Promise<boolean> {
  return cropPosterImage(srcPath, destPath, {
    mode: "right",
    ratio: opts?.ratio,
  });
}

/** 中心裁剪到目标宽高比（竖版海报墙） */
async function centerCropToRatio(
  srcPath: string,
  destPath: string,
  ratio: number,
): Promise<boolean> {
  try {
    const size = readJpegSize(srcPath);
    if (!size || size.width < 80 || size.height < 80) return false;
    const cur = size.width / size.height;
    const sharp = (await import("sharp")).default;
    let left = 0;
    let top = 0;
    let width = size.width;
    let height = size.height;
    if (Math.abs(cur - ratio) < 0.02) {
      if (srcPath !== destPath) fs.copyFileSync(srcPath, destPath);
      return true;
    }
    if (cur > ratio) {
      width = Math.max(1, Math.round(size.height * ratio));
      left = Math.max(0, Math.round((size.width - width) / 2));
    } else {
      height = Math.max(1, Math.round(size.width / ratio));
      top = Math.max(0, Math.round((size.height - height) / 2));
    }
    const tmp = destPath + ".__crop__.jpg";
    await sharp(srcPath)
      .extract({ left, top, width, height })
      .jpeg({ quality: 90 })
      .toFile(tmp);
    fs.renameSync(tmp, destPath);
    return true;
  } catch {
    try {
      fs.unlinkSync(destPath + ".__crop__.jpg");
    } catch {
      /* ignore */
    }
    return false;
  }
}

/** 人脸/注意力定位裁剪到目标比例（sharp attention，无额外模型依赖） */
async function faceCropToRatio(
  srcPath: string,
  destPath: string,
  ratio: number,
): Promise<boolean> {
  try {
    const size = readJpegSize(srcPath);
    if (!size || size.width < 80 || size.height < 80) return false;
    const targetH = size.height;
    const targetW = Math.max(1, Math.round(targetH * ratio));
    const sharp = (await import("sharp")).default;
    const tmp = destPath + ".__crop__.jpg";
    if (targetW >= size.width * 0.98) {
      // 已接近目标比例：用 attention 缩放到统一高度
      await sharp(srcPath)
        .resize({
          width: Math.max(targetW, 1),
          height: targetH,
          fit: "cover",
          position: sharp.strategy.attention,
        })
        .jpeg({ quality: 90 })
        .toFile(tmp);
    } else {
      await sharp(srcPath)
        .resize({
          width: targetW,
          height: targetH,
          fit: "cover",
          position: sharp.strategy.attention,
        })
        .jpeg({ quality: 90 })
        .toFile(tmp);
    }
    fs.renameSync(tmp, destPath);
    return true;
  } catch {
    try {
      fs.unlinkSync(destPath + ".__crop__.jpg");
    } catch {
      /* ignore */
    }
    // 回退右侧裁剪
    return cropPosterImage(srcPath, destPath, { mode: "right", ratio });
  }
}

export async function cropPosterImage(
  srcPath: string,
  destPath: string,
  opts: { mode: PosterCropMode; ratio?: number },
): Promise<boolean> {
  const ratio = opts.ratio ?? 2.12 / 3;
  if (opts.mode === "none") {
    try {
      if (srcPath !== destPath) fs.copyFileSync(srcPath, destPath);
      return true;
    } catch {
      return false;
    }
  }
  if (opts.mode === "face") {
    return faceCropToRatio(srcPath, destPath, ratio);
  }
  // right
  try {
    const size = readJpegSize(srcPath);
    if (!size || size.width < 200 || size.height < 200) return false;
    const targetW = Math.max(1, Math.round(size.height * ratio));
    if (targetW >= size.width * 0.95) {
      // 已接近竖版：可选中心裁到精确比例
      return centerCropToRatio(srcPath, destPath, ratio);
    }
    const left = Math.max(0, size.width - targetW);
    const sharp = (await import("sharp")).default;
    const tmp = destPath + ".__crop__.jpg";
    await sharp(srcPath)
      .extract({ left, top: 0, width: targetW, height: size.height })
      .jpeg({ quality: 90 })
      .toFile(tmp);
    fs.renameSync(tmp, destPath);
    return true;
  } catch {
    try {
      fs.unlinkSync(destPath + ".__crop__.jpg");
    } catch {
      /* ignore */
    }
    return false;
  }
}

/**
 * 按配置写出海报文件。
 * 产品约定：刮削落盘始终保存原图（优先竖版/高清原图，否则缩略图原图）；
 * 七区裁剪方案仅用于 App 内实时显示取景，不在此做 sharp 裁剪。
 */
export async function applyPosterCropConfig(
  coverSrc: string,
  posterDest: string,
  opts: {
    kind?: string;
    config?: PosterCropConfig;
    portraitSrc?: string | null;
  },
): Promise<{ ok: boolean; mode: PosterCropMode; used: "crop" | "portrait" | "original" }> {
  const mode = resolveCropMode(opts.config, opts.kind);

  const portrait = String(opts.portraitSrc || "").trim();
  let hasPortrait = false;
  if (
    portrait &&
    portrait !== coverSrc &&
    fs.existsSync(portrait)
  ) {
    try {
      const bytes = fs.statSync(portrait).size;
      const s = readJpegSize(portrait);
      // 拒绝 NOW PRINTING 一类极小占位图，回落横版原图
      hasPortrait = bytes >= 12_000 && Boolean(s && s.width >= 200 && s.height >= 280);
    } catch {
      hasPortrait = false;
    }
  }

  try {
    if (hasPortrait) {
      fs.copyFileSync(portrait, posterDest);
      return { ok: true, mode, used: "portrait" };
    }
    if (coverSrc !== posterDest) fs.copyFileSync(coverSrc, posterDest);
    else if (!fs.existsSync(posterDest)) fs.copyFileSync(coverSrc, posterDest);
    return { ok: true, mode, used: "original" };
  } catch {
    return { ok: false, mode, used: "original" };
  }
}
