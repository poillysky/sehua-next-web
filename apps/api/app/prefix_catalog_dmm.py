"""DMM GraphQL helpers for prefix/code verification."""

from __future__ import annotations

import re
from typing import Any

import httpx

GQL = "https://api.video.dmm.co.jp/graphql"
DIGITAL_QUERY = """
query ScrapDigitalContent($id: ID!) {
  ppvContent(id: $id) {
    id title maker { name } label { name }
  }
}
"""
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# series -> preferred DMM contentId digit prefix (mdcs-aligned)
SERIES_DIGIT: dict[str, str] = {
    "ssis": "",
    "ssni": "",
    "sone": "",
    "snos": "",
    "ofje": "",
    "sivr": "",
    "midv": "",
    "mida": "",
    "miab": "",
    "miaa": "",
    "miae": "",
    "mimk": "",
    "mifd": "",
    "mird": "",
    "mdvr": "",
    "mizd": "",
    "ipzz": "",
    "ipx": "",
    "ipz": "",
    "ipvr": "",
    "supd": "",
    "jur": "",
    "juq": "",
    "jul": "",
    "juy": "",
    "jux": "",
    "achj": "",
    "roe": "",
    "oba": "",
    "ure": "",
    "adn": "",
    "same": "",
    "rbk": "",
    "sspd": "",
    "pred": "",
    "pgd": "",
    "waaa": "",
    "meyd": "",
    "cawd": "",
    "kawd": "",
    "stars": "1",
    "star": "1",
    "start": "1",
    "sdnm": "1",
    "sdab": "1",
    "sdde": "1",
    "sdmm": "1",
    "dandy": "1",
    "fsdss": "1",
    "fcdss": "1",
    "dldss": "1",
    "svdvd": "1",
    "svvrt": "1",
    "sw": "1",
    "wanz": "3",
    "gvg": "13",
    "gvh": "13",
    "abf": "436",
    "abp": "118",
    "onez": "118",
    "mxgs": "h_068",
    "ienf": "1",
    "aarm": "",
    "aldn": "",
    "apns": "",
    "avop": "",
    "avsa": "",
    "bban": "",
    "bijn": "",
    "blk": "",
    "bmw": "",
    "bony": "",
    "cemd": "",
    "cesd": "",
    "cjod": "",
    "club": "",
    "dass": "",
    "dazd": "",
    "dsvr": "",
    "dvdms": "1",
    "dvmm": "",
    "ebwh": "",
    "eyan": "",
    "fjin": "",
    "fns": "1",
    "focs": "",
    "fpre": "",
    "hbad": "1",
    "hikr": "",
    "hmn": "",
    "hnd": "",
    "hndb": "",
    "hnds": "",
    "hunbl": "",
    "hunta": "1",
    "huntb": "",
    "huntc": "",
    "jfb": "",
    "jufd": "",
    "jufe": "",
    "juny": "",
    "kagp": "",
    "kavr": "",
    "ksbj": "",
    "kwbd": "",
    "lulu": "",
    "mdon": "",
    "mfyd": "",
    "mgold": "1",
    "mikr": "",
    "mism": "",
    "mkck": "",
    "mrss": "",
    "mtall": "1",
    "mucd": "",
    "mudr": "",
    "mukc": "",
    "mukd": "",
    "nad": "1",
    "namh": "1",
    "ndra": "",
    "ngod": "",
    "nhdta": "1",
    "nhdtb": "1",
    "nhdtc": "1",
    "nima": "",
    "nkkd": "",
    "nsfs": "",
    "ofes": "",
    "pbd": "",
    "pfes": "",
    "ppbd": "",
    "pppd": "",
    "pppe": "",
    "prst": "",
    "pxvr": "",
    "rctd": "1",
    "rki": "",
    "royd": "",
    "sace": "1",
    "sdam": "1",
    "sdjs": "1",
    "sdmt": "1",
    "sdmu": "1",
    "sora": "",
    "tek": "",
    "urvrsp": "",
    "vagu": "",
    "vec": "",
    "vema": "",
    "venu": "",
    "venx": "",
    "ymdd": "",

}


def series_key(prefix: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", prefix).lower()


def guess_digits(prefix: str) -> list[str]:
    s = series_key(prefix)
    known = SERIES_DIGIT.get(s)
    if known is not None:
        return [known]
    return ["", "1", "13", "49", "436", "118"]


def content_id(prefix: str, n: int, digit: str = "") -> str:
    s = series_key(prefix)
    num = str(int(n)).zfill(5)
    return f"{digit}{s}{num}" if digit else f"{s}{num}"


def gql_ppv(http: httpx.Client, cid: str, *, timeout: float = 6.0) -> dict[str, Any] | None:
    detail = f"https://video.dmm.co.jp/av/content/?id={cid}"
    try:
        r = http.post(
            GQL,
            json={
                "operationName": "ScrapDigitalContent",
                "variables": {"id": cid},
                "query": DIGITAL_QUERY,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://video.dmm.co.jp",
                "Referer": detail,
                "User-Agent": UA,
            },
            timeout=timeout,
        )
    except Exception:
        return None
    if r.status_code >= 400:
        return None
    try:
        hit = ((r.json().get("data") or {}).get("ppvContent")) or None
    except Exception:
        return None
    if not hit or not (hit.get("id") or hit.get("title")):
        return None
    return {
        "cid": cid,
        "title": str(hit.get("title") or ""),
        "maker_ja": (hit.get("maker") or {}).get("name") or "",
        "label_ja": (hit.get("label") or {}).get("name") or "",
    }


def resolve_digit(
    http: httpx.Client, prefix: str, sample_ns: tuple[int, ...] = (1, 50, 100, 200, 500)
) -> tuple[str, dict[str, Any]] | None:
    for n in sample_ns:
        for dig in guess_digits(prefix):
            cid = content_id(prefix, n, dig)
            hit = gql_ppv(http, cid)
            if hit:
                return dig, hit
    return None


def probe_serial(
    http: httpx.Client, prefix: str, n: int, digit: str
) -> dict[str, Any] | None:
    hit = gql_ppv(http, content_id(prefix, n, digit))
    if hit:
        return hit
    # 一次瞬断重试，避免二分被「假阴性」压低最新号
    return gql_ppv(http, content_id(prefix, n, digit))


def find_max_serial(
    http: httpx.Client,
    prefix: str,
    digit: str,
    *,
    hi_cap: int = 1500,
    stride: int = 25,
) -> int:
    """自高位找最大存在流水号（兼容中间空洞）。

    递减采样 + 空隙串行扫描；探测失败重试，避免假阴性。
    """
    del stride

    def _probe(n: int) -> bool:
        cid = content_id(prefix, n, digit)
        for _ in range(3):
            try:
                if gql_ppv(http, cid):
                    return True
            except Exception:
                continue
        return False

    def _scan_down(start: int, stop: int) -> int:
        for x in range(start, stop - 1, -1):
            if _probe(x):
                return x
        return 0

    cap = max(1, int(hi_cap))
    if _probe(cap):
        while cap < 10000:
            nxt = min(10000, cap + 500)
            if _probe(nxt):
                cap = nxt
            else:
                return _scan_down(nxt - 1, cap + 1) or cap
        return cap

    samples = sorted(
        {
            s
            for s in (
                cap,
                2000,
                1500,
                1200,
                1000,
                800,
                600,
                400,
                300,
                200,
                150,
                100,
                80,
                50,
                30,
                20,
                10,
                5,
                3,
                2,
                1,
            )
            if 1 <= s <= cap
        },
        reverse=True,
    )

    prev = cap + 1
    for s in samples:
        if prev - 1 >= s + 1:
            hit = _scan_down(prev - 1, s + 1)
            if hit:
                return hit
        if _probe(s):
            return s
        prev = s

    return _scan_down(cap, 1)


def harvest_serials_quick(
    http: httpx.Client,
    prefix: str,
    digit: str,
    serial_max: int,
) -> tuple[list[int], str]:
    """Fast path: only probe a small set of real serials (+ max).

    integrity=quick — not a full plate list; enough to prove the prefix
    and anchor serial_min/max for later dense fill.
    """
    if serial_max <= 0:
        return [], "empty"
    candidates = [1, 2, 3, 5, 10, 20, 50, 100, 200, 300, 500]
    candidates = [n for n in candidates if n < serial_max]
    candidates.append(serial_max)
    # unique preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for n in candidates:
        if n > 0 and n not in seen:
            seen.add(n)
            ordered.append(n)
    ok: list[int] = []
    for n in ordered:
        if probe_serial(http, prefix, n, digit):
            ok.append(n)
    return ok, "quick"


def harvest_serials_dense(
    http: httpx.Client,
    prefix: str,
    digit: str,
    serial_max: int,
    *,
    full_scan_limit: int = 120,
) -> tuple[list[int], str]:
    """Return verified serials.

    integrity:
      - dense: every number 1..max probed (max ≤ full_scan_limit)
      - sampled: endpoints + stride probes (not every hole filled)
    """
    if serial_max <= 0:
        return [], "empty"
    if serial_max <= full_scan_limit:
        ok = []
        for n in range(1, serial_max + 1):
            if probe_serial(http, prefix, n, digit):
                ok.append(n)
        return ok, "dense"

    # sampled: probe 1..40 fully, then stride, always include max
    ok_set: set[int] = set()
    for n in range(1, 41):
        if n <= serial_max and probe_serial(http, prefix, n, digit):
            ok_set.add(n)
    stride = max(2, serial_max // 80)
    for n in range(41, serial_max + 1, stride):
        if probe_serial(http, prefix, n, digit):
            ok_set.add(n)
    if probe_serial(http, prefix, serial_max, digit):
        ok_set.add(serial_max)
    # fill small gaps between known hits when gap ≤ 3
    known = sorted(ok_set)
    for a, b in zip(known, known[1:]):
        if 1 < b - a <= 3:
            for n in range(a + 1, b):
                if probe_serial(http, prefix, n, digit):
                    ok_set.add(n)
    return sorted(ok_set), "sampled"
