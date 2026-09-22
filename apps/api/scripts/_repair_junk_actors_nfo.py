# -*- coding: utf-8 -*-
"""Correct over-aggressive junk-actor NFO rewrite: keep real names only, no genre lift."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.db import connect, init_db
from app.scrap_library.enrich import (
    _clean_actors,
    _looks_like_actor_sentence_frag,
    _title_trailing_person_name,
)
from app.scrap_library.nfo import _actor_names, _append_actors_mdcx, write_nfo

ROOT = Path(r"E:/Project/sehua-next-web/media/scrap-library/日本有码")

# 仅这些曾明确污染、需要修；空 actor 的旧条目不要靠标签乱升格
FORCE_CODES = {
    "ALDN-098",
    "ALDN-344",
    "APAK-328",
    "APAK-001",
    "APAK-101",
    "APNS-021",
    "APNS-019",
    "ANB-001",
    "ANB-002",
    "AKDL-262",
    "AKDL-253",
    "AKDL-250",
    "AKDL-246",
    "AKDL-245",
    "YRH-025",
    "YMDD-159",
    "YM-052",
}


def _looks_like_real_person(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    cleaned = _clean_actors([n])
    if not cleaned:
        return False
    n = cleaned[0]
    if _looks_like_actor_sentence_frag(n):
        return False
    # 片商文档/街区描写误入
    if any(s in n for s in ("ドキュメント", "周辺", "チャンネル", "频道", "頻道")):
        return False
    # 姓+假名 / 假名艺名
    if re.fullmatch(r"[一-龥々〆ヵヶ]{1,4}[ぁ-んァ-ンー･・]{1,10}", n):
        return True
    if re.fullmatch(r"[ぁ-んァ-ンー]{2,12}", n):
        return True
    # 汉字人名 2～8（题材已 junk）
    if re.fullmatch(r"[一-龥々]{2,8}", n):
        return True
    # 西洋/混合名
    if re.search(r"[A-Za-z]", n) or "・" in n or "·" in n:
        return True
    # 汉字+假名混合短名
    if (
        re.search(r"[ぁ-んァ-ン]", n)
        and re.search(r"[一-龥]", n)
        and len(n) <= 12
        and not re.search(r"[はがをにでともの]", n[1:-1] or "")
    ):
        # 仍允许 姓+假名；长街区描写已在上面拦
        return True
    return False


def resolve(root_el: ET.Element, code: str) -> list[str]:
    before = _actor_names(root_el)
    kept = [a for a in _clean_actors(before) if _looks_like_real_person(a)]
    if kept:
        return kept[:12]
    # 仅对目标条目：标题尾人名兜底（不从题材标签升格）
    if code in FORCE_CODES:
        title = ""
        for tag in ("title", "originaltitle"):
            el = root_el.find(tag)
            if el is not None:
                title = "".join(el.itertext()).strip()
                if title:
                    break
        tail = _title_trailing_person_name(title)
        if tail and _looks_like_real_person(tail):
            return _clean_actors([tail])[:12]
    return []


def rewrite_actors(path: Path, names: list[str]) -> None:
    tree = ET.parse(path)
    r = tree.getroot()
    for a in list(r.findall("actor")):
        r.remove(a)
    insert_at = len(list(r))
    for i, ch in enumerate(list(r)):
        if ch.tag in ("tag", "genre", "set", "studio", "maker"):
            insert_at = i
            break
    tmp = ET.Element("movie")
    _append_actors_mdcx(tmp, names)
    for offset, el in enumerate(list(tmp)):
        r.insert(insert_at + offset, el)
    write_nfo(path, r)


def main() -> None:
    repaired: list[tuple[str, list[str], list[str]]] = []
    # 扫最近改动的 + FORCE
    paths = {p for p in ROOT.rglob("*.nfo") if p.stem in FORCE_CODES}
    for p in sorted(ROOT.rglob("*.nfo"), key=lambda x: x.stat().st_mtime, reverse=True)[
        :400
    ]:
        paths.add(p)

    for p in sorted(paths):
        try:
            tree = ET.parse(p)
            r = tree.getroot()
        except Exception:  # noqa: BLE001
            continue
        before = _actor_names(r)
        after = resolve(r, p.stem)
        if before == after:
            continue
        # 跳过「本来就空且仍空」
        if not before and not after:
            continue
        rewrite_actors(p, after)
        repaired.append((p.stem, before, after))

    print("corrected", len(repaired))
    for code, b, a in repaired:
        print(code, b, "=>", a)

    codes = sorted({c for c, *_ in repaired})
    if not codes:
        return
    init_db()
    updated = 0
    with connect() as conn:
        ph = ",".join("?" * len(codes))
        rows = conn.execute(
            f"""
            SELECT id, code, payload_json FROM enrich_queue_log
            WHERE region=? AND status='done' AND code IN ({ph})
            """,
            ("japan_censored", *codes),
        ).fetchall()
        by_code = {c: a for c, _b, a in repaired}
        for row in rows:
            d = dict(row)
            code = str(d.get("code") or "")
            target = by_code.get(code)
            if target is None:
                continue
            raw = d.get("payload_json")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            changed = False
            for path in (
                ("fields", "actors"),
                ("detail", "actors"),
                ("merged", "actors"),
                ("actors",),
            ):
                cur: object = payload
                ok = True
                for k in path[:-1]:
                    if not isinstance(cur, dict) or k not in cur:
                        ok = False
                        break
                    cur = cur[k]
                if not ok or not isinstance(cur, dict):
                    continue
                key = path[-1]
                if key in cur and cur[key] != target:
                    cur[key] = target
                    changed = True
            fields = payload.get("fields")
            if isinstance(fields, list):
                for f in fields:
                    if not isinstance(f, dict):
                        continue
                    fid = str(f.get("id") or f.get("key") or "")
                    if fid not in ("actors", "actress", "女优"):
                        continue
                    text = "、".join(target)
                    if f.get("value") != target or f.get("text") != text:
                        f["value"] = target
                        f["text"] = text
                        changed = True
            if changed:
                conn.execute(
                    "UPDATE enrich_queue_log SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), d["id"]),
                )
                updated += 1
        conn.commit()
    print("log rows updated", updated)


if __name__ == "__main__":
    main()
