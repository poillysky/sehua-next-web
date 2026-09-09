# -*- coding: utf-8 -*-
"""FreeJavBT 详情刮削（对齐 MDCS freejavbt.ts）。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    pick_og_image,
    std_code,
    strip_tags,
    soup,
)

DEFAULT_BASE = "https://www.freejavbt.com"
SOURCE = "freejavbt"

AV_MAN_NAMES = {
    "貞松大輔", "鮫島", "森林原人", "黒田悠斗", "主観", "吉村卓", "野島誠", "小田切ジュン", "しみけん",
    "セツネヒデユキ", "大島丈", "玉木玲", "ウルフ田中", "ジャイアント廣田", "イセドン内村", "西島雄介",
    "平田司", "杉浦ボッ樹", "大沢真司", "ピエール剣", "羽田", "田淵正浩", "タツ", "南佳也", "吉野篤史",
    "今井勇太", "マッスル澤野", "井口", "松山伸也", "花岡じった", "佐川銀次", "およよ中野", "小沢とおる",
    "橋本誠吾", "阿部智広", "沢井亮", "武田大樹", "市川哲也", "浅野あたる", "梅田吉雄", "阿川陽志",
    "素人", "結城結弦", "畑中哲也", "堀尾", "上田昌宏", "えりぐち", "市川潤", "沢木和也", "トニー大木",
    "横山大輔", "一条真斗", "真田京", "イタリアン高橋", "中田一平", "完全主観", "イェーイ高島", "山田万次郎",
    "澤地真人", "杉山", "ゴロー", "細田あつし", "藍井優太", "奥村友真", "ザーメン二郎", "桜井ちんたろう",
    "冴山トシキ", "久保田裕也", "戸川夏也", "北こうじ", "柏木純吉", "ゆうき", "トルティーヤ鈴木", "神けんたろう",
    "堀内ハジメ", "ナルシス小林", "アーミー", "池田径", "吉村文孝", "優生", "久道実", "一馬", "辻隼人",
    "片山邦生", "Qべぇ", "志良玉弾吾", "今岡爽紫郎", "工藤健太", "原口", "アベ", "染島貢", "岩下たろう",
    "小野晃", "たむらあゆむ", "川越将護", "桜木駿", "瀧口", "TJ本田", "園田", "宮崎", "鈴木一徹", "黒人",
    "カルロス", "天河", "ぷーてゃん", "左曲かおる", "富田", "TECH", "ムールかいせ", "健太", "山田裕二",
    "池沼ミキオ", "ウサミ", "押井敬之", "浅見草太", "ムータン", "フランクフルト林", "石橋豊彦", "矢野慎二",
    "芦田陽", "くりぼ", "ダイ", "ハッピー池田", "山形健", "忍野雅一", "渋谷優太", "服部義", "たこにゃん",
    "北山シロ", "つよぽん", "山本いくお", "学万次郎", "平井シンジ", "望月", "ゆーきゅん", "頭田光", "向理来",
    "かめじろう", "高橋しんと", "栗原良", "テツ神山", "タラオ", "真琴", "滝本", "金田たかお", "平ボンド",
    "春風ドギー", "桐島達也", "中堀健二", "徳田重男", "三浦屋助六", "志戸哲也", "ヒロシ", "オクレ", "羽目白武",
    "ジョニー岡本", "幸野賀一", "インフィニティ", "ジャック天野", "覆面", "安大吉", "井上亮太", "笹木良一",
    "艦長", "軍曹", "タッキー", "阿部ノボル", "ダウ兄", "まーくん", "梁井一", "カンパニー松尾", "大塚玉堂",
    "日比野達郎", "小梅", "ダイナマイト幸男", "タケル", "くるみ太郎", "山田伸夫", "氷崎健人",
}


def _uniq(names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        t = n.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _with_https(url: str) -> str:
    s = str(url or "").strip().replace("\\/", "/")
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    return s


def _build_fanza_trailer(sample: str) -> str:
    raw = _with_https(sample)
    if not raw:
        return ""
    if re.search(r"\.mp4(?:[?#].*)?$", raw, re.I):
        return raw
    trailer = re.sub(r"hlsvideo", "litevideo", raw, flags=re.I)
    if re.search(r"/pv/", trailer, re.I) and re.search(r"playlist\.m3u8", trailer, re.I):
        return ""
    m = re.search(r"/([^/]+)/playlist\.m3u8", trailer, re.I)
    if m:
        return re.sub(r"playlist\.m3u8", f"{m.group(1)}_sm_w.mp4", trailer, flags=re.I)
    return ""


def _pick_best_trailer(candidates: list[str]) -> str | None:
    best = ""
    best_rank = -1
    ranks = [
        (re.compile(r"4k", re.I), 120),
        (re.compile(r"hhb", re.I), 100),
        (re.compile(r"mhb", re.I), 80),
        (re.compile(r"mmb", re.I), 60),
        (re.compile(r"sm", re.I), 40),
    ]
    for raw in candidates:
        built = _build_fanza_trailer(raw)
        url = built or (
            _with_https(raw)
            if re.search(r"\.mp4(?:[?#].*)?$", _with_https(raw), re.I)
            else ""
        )
        if not url or re.search(r"\.m3u8", url, re.I):
            continue
        rank = 20 if re.search(r"\.mp4", url, re.I) else 0
        for pat, r in ranks:
            if pat.search(url):
                rank = r
                break
        if rank > best_rank:
            best, best_rank = url, rank
    return best or None


def parse_freejavbt_title(html: str, fallback_code: str) -> tuple[str, str]:
    raw_m = re.search(r"<title[^>]*>([\s\S]*?)</title>", html or "", re.I)
    raw = re.sub(r"\| FREE JAV BT", "", raw_m.group(1) if raw_m else "", flags=re.I).strip()
    if not raw:
        return "", fallback_code
    pipe_parts = [s.strip() for s in raw.split("|")]
    number = fallback_code
    title = ""
    if len(pipe_parts) == 2:
        number = pipe_parts[0] or fallback_code
        title = re.sub(re.escape(number), "", "|".join(pipe_parts[1:]), flags=re.I).strip()
    else:
        sp = raw.split()
        if len(sp) >= 2:
            number = sp[0] or fallback_code
            title = " ".join(sp[1:]).strip()
    title = (
        title.replace("中文字幕", "")
        .replace("無碼", "")
        .replace("\\n", "")
        .replace("_", "-")
    )
    title = re.sub(re.escape(number), "", title, flags=re.I)
    title = re.sub(r"--+", "-", title).strip()
    raw_for_check = "|".join(pipe_parts) if len(pipe_parts) == 2 else raw
    if not title or "翻译错误" in title or "每日更新" in raw_for_check:
        return "", number
    return title, number


def strip_trailing_actors_from_title(title: str, all_actors: list[str]) -> str:
    t = title.strip()
    if not t or not all_actors:
        return t
    names = sorted([n for n in all_actors if n and len(n) >= 2], key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        for name in names:
            if t.endswith(name):
                t = t[: -len(name)].strip()
                changed = True
                break
            spaced = f" {name}"
            if t.endswith(spaced):
                t = t[: -len(spaced)].strip()
                changed = True
                break
    return t.strip()


def clean_freejavbt_title(title: str, number: str, all_actors: list[str]) -> str:
    t = clean_title(title, number)
    t = re.sub(r"\s*(免费AV在线看|無料で見る|在线看)\s*$", "", t, flags=re.I).strip()
    t = strip_trailing_actors_from_title(t, all_actors)
    if is_junk_title(t) or re.search(
        r"你可能喜欢|あなたは好きかもしれません|翻译错误|每日更新", t
    ):
        return ""
    return t


def _text_after_span(doc, label_re: re.Pattern[str]) -> str:
    for el in doc.select("span"):
        lab = strip_tags(el.get_text())
        if not label_re.search(lab):
            continue
        sib = el.find_next_sibling()
        if sib is not None:
            return strip_tags(sib.get_text()).strip()
        parent = el.parent
        if parent is not None:
            b = parent.select_one("b")
            found = strip_tags(b.get_text() if b else parent.get_text().replace(lab, ""))
            return found.strip()
    return ""


def _meta_by_label(doc, label_re: re.Pattern[str]) -> tuple[str, list[str]]:
    text = ""
    links: list[str] = []
    for el in doc.select(".single-video-meta"):
        lab_el = el.find("span", recursive=False)
        lab = strip_tags(lab_el.get_text()) if lab_el else ""
        if not label_re.search(lab):
            continue
        for a in el.select("a"):
            n = strip_tags(a.get_text())
            if n and len(n) < 60 and n not in links:
                links.append(n)
        spans = [c for c in el.find_all("span", recursive=False)]
        if len(spans) >= 2:
            text = strip_tags(spans[-1].get_text())
        else:
            text = strip_tags(el.get_text().replace(lab, ""))
    if not text and not links:
        text = _text_after_span(doc, label_re)
    return text.strip(), links


def _is_actress_link(class_name: str) -> bool:
    return bool(re.search(r"(^|\s)actress(\s|$)", class_name or "", re.I))


def _parse_all_actors(doc) -> list[str]:
    all_actors: list[str] = []
    skip_sel = ".related, .sidebar, #related, .you-may-like, .recommend, .ranking, .footer, .comment"
    for a in doc.select("a"):
        if a.find_parent(class_=re.compile(
            r"related|sidebar|you-may-like|recommend|ranking|footer|comment", re.I
        )):
            continue
        # also skip by id related
        parent = a.find_parent(id="related")
        if parent is not None:
            continue
        if a.select_one(skip_sel):
            pass
        cls = a.get("class") or []
        cls_s = " ".join(cls) if isinstance(cls, list) else str(cls)
        if not _is_actress_link(cls_s):
            continue
        n = strip_tags(a.get_text())
        if n and n != "?" and "暫無" not in n and n not in all_actors:
            all_actors.append(n)
    return all_actors


def pick_actors_referenced_in_title(title: str, candidates: list[str]) -> list[str]:
    if not title.strip() or not candidates:
        return []
    return _uniq([n for n in candidates if len(n) >= 2 and n in title])


def _parse_actors(doc, title: str) -> list[str]:
    _, meta_links = _meta_by_label(
        doc, re.compile(r"演员|女優|出演|スター|AV女優|女优|女優名")
    )
    meta_actors = _uniq([n for n in meta_links if n not in AV_MAN_NAMES])
    pool = meta_actors or [
        n for n in _parse_all_actors(doc) if n not in AV_MAN_NAMES
    ]
    referenced = pick_actors_referenced_in_title(title, pool)
    return referenced or pool


def _parse_premiered(doc) -> str | None:
    text, links = _meta_by_label(doc, re.compile(r"日期|発売日|公開日|发行日|發行日"))
    scoped = text or " ".join(links)
    if not scoped:
        info = doc.select_one(".single-video-info, .single-video-meta")
        if info is not None:
            local = soup(str(info))
            scoped = (
                _text_after_span(local, re.compile(r"日期|発売日|公開日|发行日|發行日"))
                or _meta_by_label(local, re.compile(r"日期|発売日|公開日|发行日|發行日"))[0]
            )
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", scoped or "")
    if not dm:
        return None
    premiered = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
    try:
        release = datetime.fromisoformat(f"{premiered}T00:00:00+00:00")
        today = datetime.now(timezone.utc)
        if release.timestamp() > today.timestamp() + 45 * 24 * 3600:
            return None
    except Exception:
        pass
    return premiered


def _parse_genres(doc) -> list[str]:
    tags: list[str] = []

    def push(raw: str) -> None:
        item = raw.strip().lstrip("#").replace("，", "")
        if item and item not in tags:
            tags.append(item)

    for a in doc.select(
        'a[class*="genre"], a[href*="/genre/"], a[href*="/genres/"], a[href*="/tag/"]'
    ):
        push(strip_tags(a.get_text()))
    _, from_meta = _meta_by_label(doc, re.compile(r"类别|類別|ジャンル|类型|類型"))
    for n in from_meta:
        if not re.search(r"同一|動画|视频|更多", n, re.I):
            push(n)
    return tags[:40]


def _parse_cover(html: str, page_url: str) -> str | None:
    doc = soup(html)
    candidates: list[str] = []
    for el in doc.select("img.video-cover"):
        src = el.get("data-src") or el.get("src")
        if src:
            candidates.append(src)
    og = pick_og_image(html)
    if og:
        candidates.append(og)
    for el in doc.select('img.lazyload[data-src*="/samples/"]'):
        src = el.get("data-src")
        if src:
            candidates.append(src)
    for raw in candidates:
        url = abs_url(raw, page_url)
        if (
            url
            and url.startswith("http")
            and not re.search(r"no_preview_lg", url, re.I)
            and not is_junk_cover_url(url)
        ):
            return url
    return None


def _parse_extrafanart(doc, page_url: str, cover_url: str | None) -> list[str]:
    urls: list[str] = []
    for a in doc.select("a.tile-item"):
        href = a.get("href")
        if not href or "#preview-video" in href:
            continue
        url = abs_url(href, page_url)
        if not url or not url.startswith("http") or is_junk_cover_url(url):
            continue
        if not re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I) and not re.search(
            r"/samples/", url, re.I
        ):
            continue
        if cover_url and url == cover_url:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _parse_trailer(doc, html: str) -> str | None:
    sources: list[str] = []
    for el in doc.select(
        "video#preview-video source, video.preview source, .preview video source"
    ):
        src = _with_https(el.get("src") or "")
        if src:
            sources.append(src)
    for sel in ("video#preview-video", "video.preview", ".preview video"):
        el = doc.select_one(sel)
        direct = _with_https(el.get("src") if el else "")
        if direct:
            sources.append(direct)
    embed = re.search(
        r"https?://[^\"'\s<>]+(?:dmm\.co\.jp|cc\d+\.dmm\.co\.jp)[^\"'\s<>]*(?:\.mp4|playlist\.m3u8)",
        html,
        re.I,
    )
    if embed:
        sources.append(embed.group(0))
    return _pick_best_trailer([_build_fanza_trailer(s) or s for s in sources])


def parse_freejavbt_detail_html(html: str, code: str, page_url: str) -> dict:
    doc = soup(html)
    if (
        "single-video-info col-12" not in html
        and not doc.select(".single-video-meta")
        and not pick_og_image(html)
    ):
        raise RuntimeError("非详情页")

    std = std_code(code)
    all_actors = _parse_all_actors(doc)
    raw_title, number = parse_freejavbt_title(html, std)
    title = clean_freejavbt_title(raw_title, number or std, all_actors)
    actor_title_hint = title or raw_title

    premiered = _parse_premiered(doc)
    runtime_raw = _text_after_span(
        doc, re.compile(r"时长|時長|収録時間|再生時間")
    ) or _meta_by_label(doc, re.compile(r"时长|収録時間|再生時間"))[0]
    rm = re.search(r"(\d+)", runtime_raw or "")
    runtime = int(rm.group(1)) if rm else None

    series = (
        _text_after_span(doc, re.compile(r"系列|シリーズ"))
        or (_meta_by_label(doc, re.compile(r"系列|シリーズ"))[1] or [""])[0]
        or _meta_by_label(doc, re.compile(r"系列|シリーズ"))[0]
        or ""
    )
    directors = _uniq(
        [
            x
            for x in [
                _text_after_span(doc, re.compile(r"导演|導演|監督")),
                *_meta_by_label(doc, re.compile(r"导演|導演|監督"))[1],
            ]
            if x
        ]
    )
    studio = (
        _text_after_span(doc, re.compile(r"制作|製作|メーカー"))
        or _meta_by_label(doc, re.compile(r"制作|製作|メーカー"))[0]
        or ""
    )
    publisher = (
        _text_after_span(doc, re.compile(r"发行|發行"))
        or _meta_by_label(doc, re.compile(r"发行|發行"))[0]
        or ""
    )
    actors = _parse_actors(doc, actor_title_hint)
    genres = _parse_genres(doc)
    cover_url = _parse_cover(html, page_url)
    extras = _parse_extrafanart(doc, page_url, cover_url)
    trailer = _parse_trailer(doc, html)

    if not title and not genres and not actors and not cover_url:
        raise RuntimeError("未找到标题")

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover_url,
        studio=studio or None,
        actors=actors,
        tags=genres,
        date=premiered,
        extra={
            "publisher": publisher or None,
            "series": series or None,
            "directors": directors or None,
            "runtime": runtime if runtime and runtime > 0 else None,
            "website": page_url,
            "trailerUrl": trailer,
            "extrafanartUrls": extras or None,
        },
    )


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")
    ck = cookie or None
    slugs = [std]
    fc2 = re.search(r"FC2[-_]?PPV[-_]?(\d+)", std, re.I) or re.search(
        r"^FC2[-_]?(\d+)$", std, re.I
    )
    if fc2:
        slugs = [f"FC2-PPV-{fc2.group(1)}", f"FC2-{fc2.group(1)}", *slugs]

    seen: set[str] = set()
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        for path in (
            f"/{quote(slug)}",
            f"/zh/{quote(slug)}",
            f"/{quote(slug)}/",
            f"/ja/{quote(slug)}",
        ):
            url = f"{base}{path}"
            try:
                html = fetch_html(
                    url, referer=f"{base}/", cookie=ck, source_id=SOURCE, fast=True
                )
            except RuntimeError:
                continue
            if not html or len(html) < 800:
                continue
            if re.search(
                r"あなたは好きかもしれません|你可能喜欢|404|找不到", html, re.I
            ) and not page_mentions_code(html, std) and not page_mentions_code(html, slug):
                raise RuntimeError("未找到")
            if not page_mentions_code(html, std) and not page_mentions_code(html, slug):
                continue
            try:
                parsed = parse_freejavbt_detail_html(html, std, url)
            except RuntimeError:
                continue
            if not parsed.get("title") and not parsed.get("posterUrl") and not parsed.get(
                "actors"
            ):
                continue
            return parsed

    raise RuntimeError("未找到")
