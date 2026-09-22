"""只读探针：10musume 封面 http vs https（走与生产同一条取图链路）。"""
from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

PAIRS = [
    "http://www.10musume.com/moviepages/122609_01/images/str.jpg",
    "http://www.10musume.com/moviepages/122714_01/images/str.jpg",
    "http://www.10musume.com/moviepages/122912_02/images/str.jpg",
    "http://www.10musume.com/moviepages/123009_01/images/str.jpg",
    "https://www.10musume.com/moviepages/122711_01/images/str.jpg",
    "https://www.10musume.com/moviepages/122817_01/images/str.jpg",
    "https://www.10musume.com/moviepages/122918_01/images/str.jpg",
]


def main() -> int:
    from app.scrap_library import embed as embed_svc

    for u in PAIRS:
        print(f"\n--- {u}", flush=True)
        for label, cand in (("as-is", u), ("https ", u.replace("http://", "https://", 1))):
            try:
                got = embed_svc._fetch_cover_bytes(cand, slot_timeout=4.0)  # noqa: SLF001
            except Exception as e:  # noqa: BLE001
                print(f"  [{label}] EXC {type(e).__name__}: {e}", flush=True)
                continue
            if not got:
                print(f"  [{label}] None", flush=True)
                continue
            raw, ctype = got
            print(
                f"  [{label}] {len(raw)}B ctype={ctype!r} "
                f"blank={embed_svc._is_blank_cover_bytes(raw)}",  # noqa: SLF001
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
