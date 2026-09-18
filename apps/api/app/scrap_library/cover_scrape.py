# -*- coding: utf-8 -*-
"""刮削封面处理：三种裁切 + 原尺寸 JPEG 落盘。

铁律：
- 只有横图（宽>高）才裁；竖图/方图不裁
- 裁切只削左右，高度不变
- 裁完什么样就存什么样：不缩最长边，只转 JPEG

落盘规则：
- 本地只保留 poster.jpg
- 包装图：pl 优先；pl 若是横图则看 ps——够大用 ps，不够则横图裁

分区模式（3 种）：
- right（右裁）：竖图原样；横图右裁成竖幅
- face（人脸）：竖图原样；横图按人脸水平裁（无人脸→中裁）
- none（不裁剪）：只要网站原版横图；竖图一律跳过
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Literal

from app.core.region_meta import REGION_ORDER

log = logging.getLogger(__name__)

CoverCropMode = Literal["right", "face", "none"]
CoverQuality = Literal["compact"]
CoverCropRatio = Literal["full", "emby"]

COVER_CROP_MODES: tuple[str, ...] = ("right", "face", "none")
COVER_QUALITIES: tuple[str, ...] = ("compact",)
COVER_CROP_RATIOS: tuple[str, ...] = ("full", "emby")
_COVER_QUALITY_ALIASES: tuple[str, ...] = ("compact", "high", "low")

# 成品短边下限：过小 ps（如 147×200）弃用，改走横图裁
DEFAULT_MIN_SHORT_EDGE = 400
_SIDE_STRIP = 0.47
_FACE_LEFT_CX = 0.40
_FACE_RIGHT_CX = 0.60

_MODE_ALIASES: dict[str, str] = {
    "right": "right",
    "right_portrait": "right",
    "smart": "right",  # 旧竖图优先 → 右裁
    "auto": "right",
    "right_face": "right",
    "face": "face",
    "face_portrait": "face",
    "none": "none",
    "keep_landscape": "none",
    "landscape": "none",
}

COVER_CROP_LABELS: dict[str, str] = {
    "right": "右裁",
    "face": "人脸",
    "none": "不裁剪",
}

COVER_QUALITY_LABELS: dict[str, str] = {
    "compact": "省盘",
}

COVER_CROP_HINTS: dict[str, str] = {
    "japan_censored": "优先原版竖图(pl>ps)；否则横图右裁",
    "japan_amateur": "优先原版竖图；否则横图按人脸裁",
    "fc2": "优先原版竖图；否则横图按人脸裁",
    "japan_uncensored": "只要网站原版横图，跳过竖图",
    "china": "只要网站原版横图，跳过竖图",
    "western": "只要网站原版横图，跳过竖图",
}

DEFAULT_REGION_COVER_CROP: dict[str, str] = {
    "japan_censored": "right",
    "japan_amateur": "face",
    "fc2": "face",
    "japan_uncensored": "none",
    "china": "none",
    "western": "none",
}

_FACE_IDEAL_CX = 0.5
_FACE_IDEAL_CY = 0.38
_FACE_OFF_CX = 0.18
_FACE_OFF_CY = 0.22

_SMART_UPGRADE_REGIONS = frozenset({"japan_censored"})


def _canon_mode(raw: str) -> str:
    key = str(raw or "").strip().lower()
    return _MODE_ALIASES.get(key, "")


def target_ratio(crop_ratio: str = "full") -> float:
    """MDCS：full=2.12/3；emby=2/3。"""
    return 2 / 3 if crop_ratio == "emby" else 2.12 / 3


def default_cover_settings() -> dict[str, Any]:
    return {
        "quality": "compact",
        "cropRatio": "full",
        "regionCrop": {
            rid: DEFAULT_REGION_COVER_CROP.get(rid, "none") for rid in REGION_ORDER
        },
        "minShortEdge": DEFAULT_MIN_SHORT_EDGE,
        "waveTimeoutSec": 8,
        # 竖图模式：已有可用横图后，再等这么久找竖图，超时即裁横图落盘
        "portraitGraceSec": 1.5,
        # v11：最终版打分早停 + 原尺寸落盘 + 新默认源序
        "coverLogicVersion": 11,
    }


def normalize_cover_settings(raw: Any, *, prev: dict[str, Any] | None = None) -> dict[str, Any]:
    base = default_cover_settings()
    prior = prev if isinstance(prev, dict) else {}
    src = raw if isinstance(raw, dict) else {}

    q = "compact"

    ratio = str(
        src.get("cropRatio", prior.get("cropRatio", base["cropRatio"]))
    ).strip().lower()
    if ratio not in COVER_CROP_RATIOS:
        ratio = str(base["cropRatio"])

    try:
        ver_blob = src if src else prior
        logic_ver = int(ver_blob.get("coverLogicVersion") or 0)
    except (TypeError, ValueError):
        logic_ver = 0

    # v9：恢复 right/face/none 三模式默认
    migrate_v9 = logic_ver < 9
    # v10：封面波次默认 12→8（竖图 grace 已管早停，无需久等）
    migrate_v10 = logic_ver < 10

    try:
        min_edge = int(
            src.get(
                "minShortEdge",
                prior.get("minShortEdge", base["minShortEdge"]),
            )
        )
    except (TypeError, ValueError):
        min_edge = DEFAULT_MIN_SHORT_EDGE
    min_edge = max(120, min(1200, min_edge))

    try:
        wave_to = int(
            src.get(
                "waveTimeoutSec",
                prior.get("waveTimeoutSec", base.get("waveTimeoutSec", 8)),
            )
        )
    except (TypeError, ValueError):
        wave_to = 8
    if migrate_v10 and wave_to >= 12:
        wave_to = int(base.get("waveTimeoutSec") or 8)
    wave_to = max(3, min(60, wave_to))

    try:
        grace = float(
            src.get(
                "portraitGraceSec",
                prior.get(
                    "portraitGraceSec",
                    base.get("portraitGraceSec", 1.5),
                ),
            )
        )
    except (TypeError, ValueError):
        grace = 1.5
    grace = max(0.2, min(8.0, grace))

    region_crop: dict[str, str] = {}
    raw_rc = src.get("regionCrop")
    prior_rc = prior.get("regionCrop") if isinstance(prior.get("regionCrop"), dict) else {}
    base_rc = base["regionCrop"]
    if not isinstance(raw_rc, dict):
        raw_rc = {}
    # 旧写真裁剪并入有码
    if "japan_censored" not in raw_rc and raw_rc.get("japan_gravure"):
        raw_rc = {**raw_rc, "japan_censored": raw_rc["japan_gravure"]}
    if "japan_censored" not in prior_rc and prior_rc.get("japan_gravure"):
        prior_rc = {**prior_rc, "japan_censored": prior_rc["japan_gravure"]}
    for rid in REGION_ORDER:
        if migrate_v9:
            region_crop[rid] = str(base_rc.get(rid, "none"))
            continue
        raw_mode = str(
            raw_rc.get(rid, prior_rc.get(rid, base_rc.get(rid, "none"))) or "none"
        )
        mode = _canon_mode(raw_mode)
        if mode not in COVER_CROP_MODES:
            mode = str(base_rc.get(rid, "none"))
        region_crop[rid] = mode if mode in COVER_CROP_MODES else "none"

    return {
        "quality": q,
        "cropRatio": ratio,
        "regionCrop": region_crop,
        "minShortEdge": min_edge,
        "waveTimeoutSec": wave_to,
        "portraitGraceSec": grace,
        "coverLogicVersion": max(logic_ver, 10),
    }


def cover_crop_for_region(region: str, cover_cfg: dict[str, Any] | None = None) -> str:
    cfg = normalize_cover_settings(cover_cfg)
    rid = str(region or "").strip()
    from app.core.region_meta import REGION_META, resolve_fs_region

    # 旧逻辑区并回物理 FC2
    if rid in {"fc2_ppv", "FC2-PPV 番号"}:
        rid = "fc2"

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
    """居中竖幅框：高度始终等于原图高，只水平裁宽（对齐「智能剪裁不改高度」）。"""
    return _portrait_box_keep_height(image_w, image_h, ratio, anchor_cx=None)


def _portrait_box_keep_height(
    image_w: int,
    image_h: int,
    ratio: float,
    *,
    anchor_cx: float | None = None,
) -> tuple[int, int, int, int]:
    """竖幅取景：ch = 原图高；cw = min(W, round(H×ratio))；可选水平锚点。

    横封→竖海报时只削左右，不砍上下。已比目标更竖（W/H≤ratio）则整图返回。
    """
    if image_w <= 0 or image_h <= 0:
        return 0, 0, max(1, image_w), max(1, image_h)
    ch = image_h
    cw = max(1, min(image_w, int(round(image_h * float(ratio)))))
    if anchor_cx is None:
        left = max(0, (image_w - cw) // 2)
    else:
        left = int(round(float(anchor_cx) - cw / 2))
        left = max(0, min(left, image_w - cw))
    return left, 0, cw, ch


def _filter_faces(
    faces: list[tuple[int, int, int, int, float]],
    image_w: int,
    image_h: int,
    *,
    strict: bool = False,
) -> list[tuple[int, int, int, int, float]]:
    """丢掉过小脸、底栏缩略图条（拼贴出道封常见噪声）。

    strict=True：只保留「可能是主图」的脸，用于判主图 vs 多小图拼贴。
    """
    if not faces or image_w <= 0 or image_h <= 0:
        return []
    area_img = float(image_w * image_h)
    min_edge = 0.07 if strict else 0.045
    min_frac = 0.008 if strict else 0.0022
    out: list[tuple[int, int, int, int, float]] = []
    for f in faces:
        fl, ft, fw, fh, sc = f
        if fw < image_w * min_edge or fh < image_h * min_edge:
            continue
        if (fw * fh) / area_img < min_frac:
            continue
        # 底栏 18% 内的小脸：多半是剧照条
        cy = (ft + fh / 2) / image_h
        if cy > 0.82 and (fw * fh) / area_img < 0.012:
            continue
        out.append(f)
    if out:
        return out
    return [] if strict else list(faces)


def _face_box_area(f: tuple[int, int, int, int, float]) -> int:
    return max(0, int(f[2]) * int(f[3]))


def _analyze_cover_subject(
    faces: list[tuple[int, int, int, int, float]],
    image_w: int,
    image_h: int,
) -> dict[str, Any]:
    """区分「一张主人物图」vs「多小图拼贴」。

    单纯数人脸不够：正常碟封常是 1 张大主图；异常出道/Q&A 封是多张小图。
    用主脸面积占比 + 相对第二名的优势判定 dominant；多张且无主图 → collage。
    """
    raw = _filter_faces(faces, image_w, image_h, strict=False)
    strict = _filter_faces(faces, image_w, image_h, strict=True)
    usable = strict or raw
    empty: dict[str, Any] = {
        "kind": "none",
        "primary": None,
        "usable": [],
        "topFrac": 0.0,
        "faceN": 0,
    }
    if not usable or image_w <= 0 or image_h <= 0:
        return empty

    ranked = sorted(usable, key=_face_box_area, reverse=True)
    top = ranked[0]
    img_a = float(image_w * image_h)
    top_a = float(_face_box_area(top))
    top_frac = top_a / img_a
    second_a = float(_face_box_area(ranked[1])) if len(ranked) > 1 else 0.0
    second_frac = second_a / img_a
    # 主图：足够大，或明显压过其它脸
    dominant = top_frac >= 0.025 or (
        top_frac >= 0.012 and (second_a <= 0 or top_a >= second_a * 2.4)
    )
    # 拼贴：多张脸且没有真正主图（多小图）
    collage = False
    if len(ranked) >= 3 and not dominant:
        collage = True
    if len(ranked) >= 4 and top_frac < 0.04:
        collage = True
        dominant = False
    if len(strict) >= 3 and top_frac < 0.03:
        collage = True
        dominant = False
    # DVD 整盒横封：左侧剧照条多人脸被 strict 滤掉后易误判 dominant；
    # 用原始脸数 + 主脸偏小 → 当作 collage，走侧裁找主封面。
    raw_n = len(faces or [])
    if (
        image_w > image_h * 1.15
        and raw_n >= 5
        and top_frac < 0.035
    ):
        collage = True
        dominant = False

    if collage:
        kind = "collage"
        # 整盒仍保留最大脸作侧裁锚点（右封面主脸）
        primary = top if top_frac >= 0.006 else None
    elif dominant:
        kind = "dominant"
        primary = top
    else:
        kind = "weak"
        primary = top if top_frac >= 0.008 else None

    return {
        "kind": kind,
        "primary": primary,
        "usable": ranked,
        "topFrac": top_frac,
        "secondFrac": second_frac,
        "faceN": len(ranked),
        "rawFaceN": raw_n,
    }


def _select_primary_face(
    faces: list[tuple[int, int, int, int, float]],
    image_w: int,
    *,
    image_h: int = 0,
) -> tuple[int, int, int, int, float] | None:
    """主脸：优先「面积优势」的主导脸；无主导时不乱跟小脸。"""
    if not faces:
        return None
    h = int(image_h or 0)
    if h > 0:
        info = _analyze_cover_subject(faces, image_w, h)
        if info["kind"] == "collage":
            return None
        if info.get("primary"):
            return info["primary"]
        usable = info.get("usable") or []
        return usable[0] if usable else None

    filtered = list(faces)

    def score_of(f: tuple[int, int, int, int, float]) -> float:
        left, top, fw, fh, sc = f
        cx = left + fw / 2
        right_bias = (cx / image_w) if image_w > 0 else 0.0
        area = fw * fh
        return area + sc * 40 + right_bias * 8

    return max(filtered, key=score_of)


def _strip_face_mass(
    faces: list[tuple[int, int, int, int, float]],
    image_w: int,
    x0: float,
    x1: float,
) -> float:
    """落在水平区间内的脸面积总和（拼贴时选左/右条带用）。"""
    mass = 0.0
    for fl, _ft, fw, fh, _sc in faces:
        cx = fl + fw / 2
        if x0 <= cx <= x1:
            mass += float(fw * fh)
    return mass


def _crop_collage_side(im, ratio: float, faces: list[tuple[int, int, int, int, float]]):
    """拼贴封：先按条带选左/中/右（默认右），侧裁后再检主导脸并收紧。

    不直接对人脸锚点整图（易跟到小插图）；侧裁后若出现真正主图再 face。
    整盒横封：主人物多在右侧封面，左侧是剧照拼贴。
    """
    w, h = im.size
    strip = max(1.0, w * _SIDE_STRIP)
    left_m = _strip_face_mass(faces, w, 0.0, strip)
    right_m = _strip_face_mass(faces, w, w - strip, float(w))
    center_m = _strip_face_mass(faces, w, w * 0.28, w * 0.72)
    # 有码碟封主视觉多在右；仅当左侧明显更「重」才左裁
    # 注意：左侧拼贴人脸数多但单脸小 → mass 可能虚高；用面积加权后仍偏左才切左
    if left_m > right_m * 1.8 and left_m >= center_m * 1.2:
        side = _crop_left(im, ratio)
    elif center_m > right_m * 1.25 and center_m > left_m * 1.25:
        side = _crop_center(im, ratio)
    else:
        side = _crop_right(im, ratio)

    sw, sh = side.size
    faces2 = _detect_faces_opencv(side)
    info2 = _analyze_cover_subject(faces2, sw, sh)
    # 侧裁后若相对清出主图，再按脸水平对齐；否则保留侧裁（比乱跟小脸稳）
    if info2.get("primary") and (
        info2.get("kind") == "dominant"
        or (
            float(info2.get("topFrac") or 0) >= 0.01
            and int(info2.get("faceN") or 0) <= 2
        )
        or (
            float(info2.get("topFrac") or 0)
            >= max(float(info2.get("secondFrac") or 0) * 2.0, 0.01)
        )
    ):
        faced = _crop_face(side, ratio, force=True)
        if _score_portrait_crop(faced) >= _score_portrait_crop(side) * 0.92:
            return faced
    return side


def _face_focus_box(
    image_w: int,
    image_h: int,
    face: tuple[int, int, int, int, float],
    ratio: float,
    *,
    tight: bool = False,
) -> tuple[int, int, int, int]:
    """人脸水平锚点取竖幅；高度始终等于原图高（不砍上下）。

    tight 仅收紧水平边距（仍不改高度）；旧版按脸放大改高度已废弃。
    """
    fl, _ft, fw, _fh, _sc = face
    face_cx = fl + fw / 2
    left, top, cw, ch = _portrait_box_keep_height(
        image_w, image_h, ratio, anchor_cx=face_cx
    )
    pad = max(int(round(max(fw, _fh) * (0.15 if tight else 0.28))), 8)
    min_left = max(0, fl + fw + pad - cw)
    max_left = min(image_w - cw, fl - pad)
    if min_left <= max_left:
        left = max(min_left, min(left, max_left))
    else:
        left = max(0, min(left, image_w - cw))
    return left, top, cw, ch


def _crop_face(im, ratio: float, *, force: bool = False, tight: bool = False):
    """人脸锚点裁切；失败则居中。仅横图裁；竖图原样返回。"""
    w, h = im.size
    if not _is_landscape(w, h):
        return im
    if not force and _already_portrait(w, h, ratio):
        return im
    faces = _detect_faces_opencv(im)
    primary = _select_primary_face(faces, w, image_h=h)
    if primary:
        left, top, cw, ch = _face_focus_box(
            w, h, primary, ratio, tight=tight
        )
    else:
        left, top, cw, ch = _center_crop_box(w, h, ratio)
    return im.crop((left, top, left + cw, top + ch))


_YUNET_MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
_yunet_detector = None
_yunet_failed = False


def _get_yunet_detector():
    """懒加载 YuNet；Haar 对大脸/侧脸常漏检，拼贴主图靠它。"""
    global _yunet_detector, _yunet_failed
    if _yunet_failed:
        return None
    if _yunet_detector is not None:
        return _yunet_detector
    try:
        import cv2  # type: ignore

        if not hasattr(cv2, "FaceDetectorYN") or not _YUNET_MODEL.is_file():
            _yunet_failed = True
            return None
        # input size 在 detect 前按图重设
        det = cv2.FaceDetectorYN.create(
            str(_YUNET_MODEL),
            "",
            (320, 320),
            0.55,
            0.3,
            5000,
        )
        _yunet_detector = det
        return det
    except Exception as e:  # noqa: BLE001
        log.debug("yunet init failed: %s", e)
        _yunet_failed = True
        return None


def _detect_faces_yunet(im) -> list[tuple[int, int, int, int, float]]:
    try:
        import cv2  # type: ignore
        import numpy as np

        det = _get_yunet_detector()
        if det is None:
            return []
        rgb = im.convert("RGB")
        arr = np.ascontiguousarray(np.array(rgb))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        w, h = im.size
        det.setInputSize((int(w), int(h)))
        _retval, faces = det.detect(bgr)
        if faces is None:
            return []
        out: list[tuple[int, int, int, int, float]] = []
        for row in faces:
            x, y, fw, fh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            score = float(row[-1]) if len(row) > 4 else 0.5
            if fw < 8 or fh < 8 or score < 0.45:
                continue
            ix, iy = max(0, int(x)), max(0, int(y))
            iw, ih = max(1, int(fw)), max(1, int(fh))
            if ix + iw > w:
                iw = max(1, w - ix)
            if iy + ih > h:
                ih = max(1, h - iy)
            out.append((ix, iy, iw, ih, min(0.99, max(0.0, score))))
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("yunet detect failed: %s", e)
        return []


def _detect_faces_haar(im) -> list[tuple[int, int, int, int, float]]:
    try:
        import cv2  # type: ignore
        import numpy as np

        if not hasattr(cv2, "CascadeClassifier"):
            return []
        rgb = im.convert("RGB")
        arr = np.array(rgb)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        w, h = im.size
        # 略抬 minSize，减少底栏/插图误检
        min_sz = (max(28, w // 28), max(28, h // 28))
        out: list[tuple[int, int, int, int, float]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for name in (
            "haarcascade_frontalface_alt2.xml",
            "haarcascade_frontalface_default.xml",
        ):
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
            if cascade.empty():
                continue
            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=min_sz,
            )
            if faces is None:
                continue
            for x, y, fw, fh in faces:
                key = (int(x), int(y), int(fw), int(fh))
                if key in seen:
                    continue
                seen.add(key)
                area = float(fw * fh)
                out.append(
                    (
                        key[0],
                        key[1],
                        key[2],
                        key[3],
                        min(0.99, area / (w * h + 1) * 8),
                    )
                )
            if out:
                break
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("haar face detect failed: %s", e)
        return []


def _detect_faces_opencv(im) -> list[tuple[int, int, int, int, float]]:
    """优先 YuNet（主图更准），失败回退 Haar。"""
    try:
        yunet = _detect_faces_yunet(im)
        if yunet:
            return yunet
        return _detect_faces_haar(im)
    except Exception as e:  # noqa: BLE001
        log.debug("opencv face detect failed: %s", e)
        return []


def _already_portrait(w: int, h: int, ratio: float = 0.0) -> bool:
    """竖图判定：高≥宽即竖图，不再叠裁。

    ratio 保留参数兼容旧调用；竖/横只看 h>=w（用户铁律：只有横图才裁）。
    """
    del ratio  # 兼容旧签名
    return h > 0 and h >= w


def _is_landscape(w: int, h: int) -> bool:
    """横图：宽严格大于高，才允许裁切。"""
    return w > 0 and h > 0 and w > h


def _face_off_center(im) -> bool:
    """成品竖图里主脸是否明显偏离理想构图（人物不正）。"""
    w, h = im.size
    if w <= 0 or h <= 0:
        return False
    faces = _detect_faces_opencv(im)
    primary = _select_primary_face(faces, w, image_h=h)
    if not primary:
        return False
    fl, ft, fw, fh, _sc = primary
    cx = (fl + fw / 2) / w
    cy = (ft + fh / 2) / h
    if abs(cx - _FACE_IDEAL_CX) > _FACE_OFF_CX:
        return True
    if abs(cy - _FACE_IDEAL_CY) > _FACE_OFF_CY:
        return True
    if fl < w * 0.02 or (fl + fw) > w * 0.98:
        return True
    if ft < h * 0.01 or (ft + fh) > h * 0.99:
        return True
    return False


def _crop_right(im, ratio: float):
    """横封右对齐竖幅：保留原高度，宽度 = H×ratio（约右半人物区）。"""
    w, h = im.size
    if not _is_landscape(w, h):
        return im
    _l, top, cw, ch = _portrait_box_keep_height(w, h, ratio)
    left = max(0, w - cw)
    return im.crop((left, top, left + cw, top + ch))


def _crop_left(im, ratio: float):
    """横封左对齐竖幅：保留原高度（人物偏左时用）。"""
    w, h = im.size
    if not _is_landscape(w, h):
        return im
    _l, top, cw, ch = _portrait_box_keep_height(w, h, ratio)
    return im.crop((0, top, cw, top + ch))


def _crop_center(im, ratio: float):
    """横封居中竖幅：保留原高度，只水平中裁。"""
    w, h = im.size
    if not _is_landscape(w, h):
        return im
    left, top, cw, ch = _center_crop_box(w, h, ratio)
    return im.crop((left, top, left + cw, top + ch))


def _score_portrait_crop(im) -> float:
    """评价竖版成品：主脸面积大、靠近理想构图、不贴边 → 分高。"""
    w, h = im.size
    if w <= 0 or h <= 0:
        return -1e9
    faces = _detect_faces_opencv(im)
    primary = _select_primary_face(faces, w, image_h=h)
    if not primary:
        return 0.0
    fl, ft, fw, fh, sc = primary
    area = (fw * fh) / float(w * h)
    cx = (fl + fw / 2) / w
    cy = (ft + fh / 2) / h
    edge = 0.0
    if fl < w * 0.02 or (fl + fw) > w * 0.98:
        edge += 0.15
    if ft < h * 0.01 or (ft + fh) > h * 0.99:
        edge += 0.1
    return (
        area * 120.0
        - abs(cx - _FACE_IDEAL_CX) * 40.0
        - abs(cy - _FACE_IDEAL_CY) * 25.0
        - edge * 20.0
        + min(float(sc), 1.0) * 5.0
    )


def _side_from_face_cx(cx: float) -> str:
    """主脸水平位置 → left / center / right。"""
    if cx < _FACE_LEFT_CX:
        return "left"
    if cx > _FACE_RIGHT_CX:
        return "right"
    return "center"


def _ensure_portrait(im, ratio: float):
    """智能竖图模式：成品必须竖图；仍横则强制侧裁。"""
    w, h = im.size
    if h <= 0:
        return im
    if h >= w:  # 已是竖或方偏竖
        return im
    # 仍横：默认右裁到目标比例
    return _crop_right(im, ratio)


def _crop_by_side(im, ratio: float, side: str):
    if side == "left":
        return _crop_left(im, ratio)
    if side == "right":
        return _crop_right(im, ratio)
    return _crop_center(im, ratio)


def _crop_smart(im, ratio: float):
    """智能竖图裁切：竖图保持不动；仅横图裁成竖幅。

    铁律：h≥w 不裁；横图裁切不改高度（只削左右）。
    """
    w, h = im.size
    if h <= 0:
        return im
    # 竖图/方图：绝不裁
    if not _is_landscape(w, h):
        return im

    faces = _detect_faces_opencv(im)
    subject = _analyze_cover_subject(faces, w, h)
    kind = str(subject.get("kind") or "none")
    primary = subject.get("primary")
    usable = list(subject.get("usable") or [])
    busy_pack = len(faces) >= 5

    # 拼贴：侧裁
    if kind == "collage":
        return _ensure_portrait(_crop_collage_side(im, ratio, usable or faces), ratio)

    # 横图 + 主导主图
    # DVD 整盒横图常误检多脸；勿 tight 放大中间（会只剩一小块），按主脸选侧或右裁封面。
    if kind == "dominant" and primary:
        fl, _ft, fw, _fh, _sc = primary
        cx = (fl + fw / 2) / w
        side = _side_from_face_cx(cx)
        if busy_pack:
            # 多脸 ≈ 整盒：优先侧裁满高，不用 tight face
            return _ensure_portrait(_crop_by_side(im, ratio, side or "right"), ratio)
        first = _crop_by_side(im, ratio, side)
        if not _face_off_center(first):
            return _ensure_portrait(first, ratio)
        cands = [
            first,
            _crop_left(im, ratio),
            _crop_center(im, ratio),
            _crop_right(im, ratio),
            _crop_face(im, ratio),
        ]
        return _ensure_portrait(max(cands, key=_score_portrait_crop), ratio)

    # 弱脸/无脸：横图默认右裁
    return _ensure_portrait(_crop_right(im, ratio), ratio)


def probe_cover_bytes(data: bytes) -> dict[str, Any]:
    """探测封面字节尺寸与是否空白。"""
    out: dict[str, Any] = {
        "ok": False,
        "width": 0,
        "height": 0,
        "shortEdge": 0,
        "blank": False,
        "issues": [],
    }
    if not data or len(data) < 32:
        out["issues"].append("empty")
        return out
    try:
        from PIL import Image, ImageOps

        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        out["width"], out["height"] = int(w), int(h)
        out["shortEdge"] = int(min(w, h))
    except Exception:  # noqa: BLE001
        out["issues"].append("unreadable")
        return out

    try:
        from app.scrap_library.embed import _is_blank_cover_bytes

        if _is_blank_cover_bytes(data):
            out["blank"] = True
            out["issues"].append("blank")
    except Exception:  # noqa: BLE001
        pass

    out["ok"] = not out["issues"]
    return out


def cover_bytes_acceptable(
    data: bytes,
    *,
    min_short_edge: int = DEFAULT_MIN_SHORT_EDGE,
) -> bool:
    """下载/裁切后的硬门禁：非空且短边达标。"""
    info = probe_cover_bytes(data)
    if not info.get("ok") and "blank" in (info.get("issues") or []):
        return False
    if info.get("blank"):
        return False
    if int(info.get("shortEdge") or 0) < max(1, int(min_short_edge)):
        return False
    if "unreadable" in (info.get("issues") or []) or "empty" in (
        info.get("issues") or []
    ):
        return False
    return True


def url_looks_small_poster(url: str) -> bool:
    """CDN 包装小图标记（DMM ps 等）；候选排序时靠后。"""
    u = str(url or "").lower()
    return any(
        x in u
        for x in ("ps.jpg", "_s.jpg", "/small/", "cover-t.jpg", "pb_e_")
    )


def cover_url_layer(url: str) -> str:
    """封面 URL 分层：pl | ps | thumb（对齐 COVER_LOGIC）。"""
    u = str(url or "").lower()
    # 包装小竖 / 横封包装（MGStage pb_e）→ ps 波
    if any(
        x in u
        for x in (
            "ps.jpg",
            "_s.jpg",
            "/small/",
            "cover-t.jpg",
            "pb_e_",
            "/pb_",
        )
    ):
        return "ps"
    if any(
        x in u
        for x in (
            "pl.jpg",
            "_b.jpg",
            "pf_e_",
            "/pf_",
            "/big/",
            "cover-n.jpg",
            "bigimage",
        )
    ):
        return "pl"
    return "thumb"


def url_looks_portrait_pack(url: str) -> bool:
    """包装/官网竖图 URL（DMM ps/pl、MGStage pf_e 等）。"""
    u = str(url or "").lower()
    return any(
        x in u
        for x in ("ps.jpg", "pl.jpg", "pf_e_", "/pf_")
    )


def cover_aspect_kind(width: int, height: int) -> str:
    """portrait | landscape | square | unknown。"""
    w, h = int(width or 0), int(height or 0)
    if w <= 0 or h <= 0:
        return "unknown"
    if h > w * 1.05:
        return "portrait"
    if w > h * 1.05:
        return "landscape"
    return "square"


def analyze_local_poster(path: Path | str) -> dict[str, Any]:
    """扫描本地 poster：是否空白/横图/人脸偏离/过小。"""
    p = Path(path)
    out: dict[str, Any] = {
        "ok": False,
        "issues": [],
        "width": 0,
        "height": 0,
        "faceOff": False,
    }
    if not p.is_file():
        out["issues"].append("missing")
        return out
    try:
        from PIL import Image, ImageOps

        im = Image.open(p)
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        out["width"], out["height"] = int(w), int(h)
    except Exception:  # noqa: BLE001
        out["issues"].append("unreadable")
        return out

    if w < 80 or h < 80 or min(w, h) < DEFAULT_MIN_SHORT_EDGE // 2:
        out["issues"].append("too_small")
    if w > h * 1.05:
        out["issues"].append("landscape")
    try:
        from app.scrap_library.embed import _is_blank_cover_file

        if _is_blank_cover_file(p):
            out["issues"].append("blank")
    except Exception:  # noqa: BLE001
        pass

    try:
        if im.mode not in ("RGB", "L"):
            rgb = im.convert("RGB")
        elif im.mode == "L":
            rgb = im.convert("RGB")
        else:
            rgb = im
        if _face_off_center(rgb):
            out["faceOff"] = True
            out["issues"].append("face_off")
    except Exception:  # noqa: BLE001
        pass

    out["ok"] = not out["issues"]
    return out


def _jpeg_encode(
    im,
    *,
    quality: str = "compact",
) -> bytes:
    """原尺寸 JPEG 编码：不缩放，裁完什么样就存什么样。"""
    del quality  # 兼容旧调用；画质档不再缩边
    from PIL import Image as PilImage

    work = im
    if not isinstance(work, PilImage.Image):
        return b""
    buf = io.BytesIO()
    work.save(
        buf,
        format="JPEG",
        quality=90,
        optimize=True,
        subsampling=0,
    )
    return buf.getvalue()


def process_cover_bytes(
    data: bytes,
    *,
    crop_mode: str = "right",
    quality: str = "compact",
    crop_ratio: str = "full",
) -> bytes:
    """按 right / face / none 处理；原尺寸 JPEG 落盘。

    铁律：
    - 只有横图（宽>高）才裁；竖图/方图原样
    - 裁切只削左右，高度必须等于源图
    - 不缩放：裁完像素尺寸原样写 JPEG
    """
    if not data or len(data) < 32:
        return data
    mode = _canon_mode(crop_mode) or "right"
    if mode not in COVER_CROP_MODES:
        mode = "right"
    del quality  # 兼容旧参数；不再按档缩边
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

        w, h = im.size
        src_h = h
        src_im = im
        # 竖图绝不进裁切分支
        if _is_landscape(w, h):
            if mode == "right":
                im = _crop_right(im, ratio)
            elif mode == "face":
                im = _crop_face(im, ratio, force=True)
                # 无人脸时 _crop_face 已居中；仍横则再强制中裁（勿回落右裁）
                if im.size[1] < im.size[0]:
                    im = _crop_center(im, ratio)
        # none / 竖图：不裁

        # 铁律：裁切只削左右，高度必须等于源图
        if im.size[1] != src_h and src_h > 0:
            log.warning(
                "cover crop changed height %s→%s; revert to source",
                src_h,
                im.size[1],
            )
            im = src_im

        out = _jpeg_encode(im)
        return out if out else data
    except Exception as e:  # noqa: BLE001
        log.debug("process_cover_bytes failed: %s", e)
        return data


def rewrite_cover_url_for_quality(url: str, quality: str) -> list[str]:
    """封面候选：pl/_b/pf_e 优先，ps/_s/pb_e 兜底。"""
    u = str(url or "").strip()
    if not u:
        return []
    cands = [u]
    for a, b in (
        ("ps.jpg", "pl.jpg"),
        ("pl.jpg", "ps.jpg"),
        ("_s.jpg", "_b.jpg"),
        ("_b.jpg", "_s.jpg"),
        ("/small/", "/big/"),
        ("/big/", "/small/"),
        ("cover-t.jpg", "cover-n.jpg"),
        ("cover-n.jpg", "cover-t.jpg"),
        # MGStage：pb_e 横封 ↔ pf_e 竖海报（对齐 MDCX）
        ("pb_e_", "pf_e_"),
        ("pf_e_", "pb_e_"),
        ("/pb_", "/pf_"),
        ("/pf_", "/pb_"),
    ):
        if a in u:
            cands.append(u.replace(a, b))
    uniq = list(dict.fromkeys(cands))
    # 竖海报/大图在前
    def _pref(x: str) -> tuple[int, int]:
        xl = x.lower()
        small = 1 if url_looks_small_poster(xl) or "pb_e_" in xl else 0
        official = 0 if ("pf_e_" in xl or "image.mgstage.com" in xl) else 1
        return (official, small)

    return sorted(uniq, key=_pref)
