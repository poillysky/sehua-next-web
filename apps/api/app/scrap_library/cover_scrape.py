# -*- coding: utf-8 -*-
"""刮削封面处理：对齐 MDCS poster.ts / faceCrop.ts（七区裁剪 + 画质）。"""

from __future__ import annotations

import io
import logging
from typing import Any, Literal

from app.core.region_meta import REGION_ORDER

log = logging.getLogger(__name__)

# 与 MDCS posterCrop 一致：right / face / none
CoverCropMode = Literal["right", "face", "none"]
CoverQuality = Literal["high", "low"]
CoverCropRatio = Literal["full", "emby"]

COVER_CROP_MODES: tuple[str, ...] = ("right", "face", "none")
COVER_QUALITIES: tuple[str, ...] = ("high", "low")
COVER_CROP_RATIOS: tuple[str, ...] = ("full", "emby")

# 旧版 id → MDCS id
_MODE_ALIASES: dict[str, str] = {
    "right": "right",
    "right_portrait": "right",
    "face": "face",
    "face_portrait": "face",
    "none": "none",
    "keep_landscape": "none",
}

COVER_CROP_LABELS: dict[str, str] = {
    "right": "右侧裁剪",
    "face": "人脸识别（失败则居中）",
    "none": "不裁剪",
}

COVER_CROP_HINTS: dict[str, str] = {
    "japan_censored": "碟封右侧多为海报，建议右侧裁剪",
    "japan_gravure": "建议右侧裁剪",
    "japan_uncensored": "可保留原图，推荐不裁剪",
    "japan_amateur": "尺寸不规则，建议人脸识别裁剪",
    "fc2": "尺寸不规则，建议人脸识别裁剪",
    "china": "多为完整宽图，建议不裁剪",
    "western": "建议不裁剪",
}

# 对齐 MDCS createDefaultScrapeConfig.kindProfiles.posterCrop
DEFAULT_REGION_COVER_CROP: dict[str, str] = {
    "japan_censored": "right",
    "japan_gravure": "right",
    "japan_amateur": "face",
    "fc2": "face",
    "japan_uncensored": "none",
    "china": "none",
    "western": "none",
}


def _canon_mode(raw: str) -> str:
    key = str(raw or "").strip().lower()
    return _MODE_ALIASES.get(key, "")


def target_ratio(crop_ratio: str = "full") -> float:
    """MDCS：full=2.12/3；emby=2/3。"""
    return 2 / 3 if crop_ratio == "emby" else 2.12 / 3


def default_cover_settings() -> dict[str, Any]:
    return {
        "quality": "high",
        # 对齐 MDCS download.cropRatio
        "cropRatio": "full",
        "regionCrop": {
            rid: DEFAULT_REGION_COVER_CROP.get(rid, "none") for rid in REGION_ORDER
        },
    }


def normalize_cover_settings(raw: Any, *, prev: dict[str, Any] | None = None) -> dict[str, Any]:
    base = default_cover_settings()
    prior = prev if isinstance(prev, dict) else {}
    src = raw if isinstance(raw, dict) else {}

    q = str(src.get("quality", prior.get("quality", base["quality"]))).strip().lower()
    if q not in COVER_QUALITIES:
        q = str(base["quality"])

    ratio = str(
        src.get("cropRatio", prior.get("cropRatio", base["cropRatio"]))
    ).strip().lower()
    if ratio not in COVER_CROP_RATIOS:
        ratio = str(base["cropRatio"])

    region_crop: dict[str, str] = {}
    raw_rc = src.get("regionCrop")
    prior_rc = prior.get("regionCrop") if isinstance(prior.get("regionCrop"), dict) else {}
    base_rc = base["regionCrop"]
    if not isinstance(raw_rc, dict):
        raw_rc = {}
    for rid in REGION_ORDER:
        mode = _canon_mode(
            str(
                raw_rc.get(rid, prior_rc.get(rid, base_rc.get(rid, "none")))
                or "none"
            )
        )
        if mode not in COVER_CROP_MODES:
            mode = str(base_rc.get(rid, "none"))
        region_crop[rid] = mode

    return {"quality": q, "cropRatio": ratio, "regionCrop": region_crop}


def cover_crop_for_region(region: str, cover_cfg: dict[str, Any] | None = None) -> str:
    cfg = normalize_cover_settings(cover_cfg)
    rid = str(region or "").strip()
    from app.core.region_meta import REGION_META, resolve_fs_region

    if rid not in REGION_META:
        mapped = resolve_fs_region(rid)
        if mapped:
            rid = mapped
        else:
            for k, meta in REGION_META.items():
                if str(meta.get("label") or "") == rid:
                    rid = k
                    break
    return str(cfg["regionCrop"].get(rid) or "none")


def _center_crop_box(image_w: int, image_h: int, ratio: float) -> tuple[int, int, int, int]:
    """对齐 MDCS centerCropBox → (left, top, width, height)。"""
    cw, ch = image_w, image_h
    if image_w / image_h > ratio:
        cw = max(1, int(image_h * ratio))
    else:
        ch = max(1, int(image_w / ratio))
    left = max(0, (image_w - cw) // 2)
    top = max(0, (image_h - ch) // 2)
    return left, top, max(1, cw), max(1, ch)


def _select_primary_face(
    faces: list[tuple[int, int, int, int, float]], image_w: int
) -> tuple[int, int, int, int, float] | None:
    """对齐 MDCS selectPrimaryFace：分数 + 面积 + 略偏右。"""
    if not faces:
        return None

    def score_of(f: tuple[int, int, int, int, float]) -> float:
        left, _top, fw, fh, sc = f
        cx = left + fw / 2
        right_bias = (cx / image_w) if image_w > 0 else 0.0
        area = fw * fh
        return sc * 100 + right_bias * 12 + min(area / 1000, 30)

    return max(faces, key=score_of)


def _face_focus_box(
    image_w: int,
    image_h: int,
    face: tuple[int, int, int, int, float],
    ratio: float,
) -> tuple[int, int, int, int]:
    """对齐 MDCS faceFocusBox：脸中心约在框 38% 高度处。"""
    cw, ch = image_w, image_h
    if image_w / image_h > ratio:
        cw = max(1, int(image_h * ratio))
    else:
        ch = max(1, int(image_w / ratio))
    cw = max(1, min(cw, image_w))
    ch = max(1, min(ch, image_h))

    fl, ft, fw, fh, _sc = face
    face_cx = fl + fw / 2
    face_cy = ft + fh / 2
    left = int(round(face_cx - cw / 2))
    top = int(round(face_cy - ch * 0.38))

    pad = max(int(round(max(fw, fh) * 0.35)), 8)
    min_left = max(0, fl + fw + pad - cw)
    max_left = min(image_w - cw, fl - pad)
    if min_left <= max_left:
        left = max(min_left, min(left, max_left))
    else:
        left = max(0, min(left, image_w - cw))

    min_top = max(0, ft + fh + pad - ch)
    max_top = min(image_h - ch, ft - pad)
    if min_top <= max_top:
        top = max(min_top, min(top, max_top))
    else:
        top = max(0, min(top, image_h - ch))

    left = max(0, min(left, image_w - cw))
    top = max(0, min(top, image_h - ch))
    return left, top, cw, ch


def _detect_faces_opencv(im) -> list[tuple[int, int, int, int, float]]:
    try:
        import cv2  # type: ignore
        import numpy as np

        rgb = im.convert("RGB")
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        w, h = im.size
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(max(32, w // 20), max(32, h // 20)),
        )
        out: list[tuple[int, int, int, int, float]] = []
        if faces is None:
            return out
        for x, y, fw, fh in faces:
            # Haar 无 score，用面积归一近似
            area = float(fw * fh)
            out.append((int(x), int(y), int(fw), int(fh), min(0.99, area / (w * h + 1) * 8)))
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("opencv face detect failed: %s", e)
        return []


def _already_portrait(w: int, h: int, ratio: float) -> bool:
    """对齐 MDCS：竖版成品不再叠裁（w/h <= ratio * 1.15）。"""
    if h <= 0:
        return False
    return (w / h) <= ratio * 1.15


def _crop_right(im, ratio: float):
    """对齐 MDCS right：取右侧约 47% 条带，再按目标比例居中裁。"""
    w, h = im.size
    if _already_portrait(w, h, ratio):
        return im
    strip_w = max(1, int(w * 0.47))
    left0 = max(0, w - strip_w)
    box_l, box_t, box_w, box_h = _center_crop_box(strip_w, h, ratio)
    left = left0 + box_l
    top = box_t
    return im.crop((left, top, left + box_w, top + box_h))


def _crop_face(im, ratio: float):
    """对齐 MDCS face：人脸锚点裁切；失败则居中。"""
    w, h = im.size
    if _already_portrait(w, h, ratio):
        return im
    faces = _detect_faces_opencv(im)
    primary = _select_primary_face(faces, w)
    if primary:
        left, top, cw, ch = _face_focus_box(w, h, primary, ratio)
    else:
        left, top, cw, ch = _center_crop_box(w, h, ratio)
    return im.crop((left, top, left + cw, top + ch))


def process_cover_bytes(
    data: bytes,
    *,
    crop_mode: str = "none",
    quality: str = "high",
    crop_ratio: str = "full",
) -> bytes:
    """按 MDCS 策略处理封面字节，输出 JPEG（用于 poster）。"""
    if not data or len(data) < 32:
        return data
    mode = _canon_mode(crop_mode) or "none"
    if mode not in COVER_CROP_MODES:
        mode = "none"
    q = quality if quality in COVER_QUALITIES else "high"
    ratio_key = crop_ratio if crop_ratio in COVER_CROP_RATIOS else "full"
    ratio = target_ratio(ratio_key)
    try:
        from PIL import Image, ImageOps

        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")

        if mode == "right":
            im = _crop_right(im, ratio)
        elif mode == "face":
            im = _crop_face(im, ratio)
        # none: 不裁剪

        if q == "low":
            max_edge = 960
            if im.width > max_edge or im.height > max_edge:
                im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            jpeg_q = 72
        else:
            # 对齐 MDCS jpeg quality=90
            jpeg_q = 90

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=jpeg_q, optimize=True, subsampling=0)
        out = buf.getvalue()
        return out if out else data
    except Exception as e:  # noqa: BLE001
        log.debug("process_cover_bytes failed: %s", e)
        return data


def rewrite_cover_url_for_quality(url: str, quality: str) -> list[str]:
    """按画质给出候选 URL（高画质对齐 MDCS preferHighResPoster：ps→pl）。"""
    u = str(url or "").strip()
    if not u:
        return []
    q = quality if quality in COVER_QUALITIES else "high"
    alts: list[str] = []
    if q == "low":
        for a, b in (
            ("pl.jpg", "ps.jpg"),
            ("_b.jpg", "_s.jpg"),
            ("/big/", "/small/"),
            ("cover-n.jpg", "cover-t.jpg"),
        ):
            if a in u:
                alts.append(u.replace(a, b))
        # 小图优先，但仍保留大图兜底（DMM ps 常为空图/NOW PRINTING）
        hi: list[str] = []
        if "ps.jpg" in u:
            hi.append(u.replace("ps.jpg", "pl.jpg"))
        if "_s.jpg" in u:
            hi.append(u.replace("_s.jpg", "_b.jpg"))
        return list(dict.fromkeys([*alts, u, *hi]))
    for a, b in (
        ("ps.jpg", "pl.jpg"),
        ("_s.jpg", "_b.jpg"),
        ("/small/", "/big/"),
        ("cover-t.jpg", "cover-n.jpg"),
    ):
        if a in u:
            alts.append(u.replace(a, b))
    return list(dict.fromkeys([u, *alts]))
