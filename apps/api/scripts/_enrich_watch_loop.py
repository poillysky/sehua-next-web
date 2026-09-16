# -*- coding: utf-8 -*-
"""Enrich slowdown watcher: sample status every N seconds, append jsonl, print tick."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

OUT = Path(r"e:\Project\sehua-next-web\.tmp_enrich_monitor.jsonl")
COOKIE = Path(r"e:\Project\sehua-next-web\.tmp_enrich_cookie.txt")
URI = "http://127.0.0.1:8020/scrap-library/embed/enrich/status"
INTERVAL = 60


def fetch() -> dict:
    cookie = COOKIE.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(URI, headers={"Cookie": cookie})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))["data"]


def sample(prev: dict | None) -> dict:
    st = fetch()
    m = st.get("monitor") or {}
    sm = m.get("summary") or {}
    qc = st.get("queueCounts") or {}
    phases: dict[str, int] = {}
    stall_kinds: dict[str, int] = {}
    long_items: list[dict] = []
    for x in m.get("inflight") or []:
        if not isinstance(x, dict):
            continue
        p = str(x.get("phase") or "?")
        phases[p] = phases.get(p, 0) + 1
        stall = x.get("stall") if isinstance(x.get("stall"), dict) else None
        if stall and stall.get("kind"):
            k = str(stall.get("kind"))
            stall_kinds[k] = stall_kinds.get(k, 0) + 1
        elapsed = int(x.get("elapsedMs") or 0)
        if elapsed >= 15000:
            long_items.append(
                {
                    "code": x.get("code"),
                    "phase": p,
                    "elapsedMs": elapsed,
                    "stall": (stall or {}).get("kind"),
                }
            )
    logs = list((st.get("regionLogs") or {}).get("japan_censored") or st.get("log") or [])
    interesting = []
    keys = (
        "封面池",
        "并发番号",
        "cover.",
        "cover_fail",
        "workers=",
        "slot",
        "Flare",
        "prefer",
        "裁剪",
        "队列表",
        "早停",
    )
    for line in logs[-40:]:
        s = str(line)
        if any(k in s for k in keys):
            interesting.append(s[:180])
    done = int(qc.get("done") or 0)
    fail = int(qc.get("fail") or 0)
    avg = int(sm.get("avgFetchMs") or 0)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "running": bool(st.get("running")),
        "halt": str(st.get("halt") or ""),
        "phase": str(st.get("phase") or "")[:80],
        "done": done,
        "fail": fail,
        "pending": int(qc.get("pending") or 0),
        "runningN": int(qc.get("running") or 0),
        "avgFetchMs": avg,
        "stallingN": int(sm.get("stallingN") or 0),
        "inflightN": int(sm.get("inflightN") or 0),
        "itemWorkers": int(m.get("itemWorkers") or 0),
        "phases": phases,
        "stallKinds": stall_kinds,
        "longItems": long_items[:6],
        "logHits": interesting[-8:],
    }
    if prev:
        dt = max(1.0, INTERVAL)
        d_done = done - int(prev.get("done") or 0)
        d_fail = fail - int(prev.get("fail") or 0)
        rec["deltaDone"] = d_done
        rec["deltaFail"] = d_fail
        rec["ratePerMin"] = round(d_done / dt * 60.0, 1)
        rec["avgDelta"] = avg - int(prev.get("avgFetchMs") or 0)
    return rec


def main() -> None:
    prev = None
    # immediate first sample
    rec = sample(None)
    prev = rec
    OUT.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AGENT_LOOP_TICK_enrich_watch " + json.dumps(rec, ensure_ascii=False), flush=True)
    if not rec.get("running"):
        print("AGENT_LOOP_TICK_enrich_watch " + json.dumps({"done": True, "reason": "not_running"}, ensure_ascii=False), flush=True)
        return
    while True:
        time.sleep(INTERVAL)
        try:
            rec = sample(prev)
            prev = rec
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print("AGENT_LOOP_TICK_enrich_watch " + json.dumps(rec, ensure_ascii=False), flush=True)
            if not rec.get("running"):
                print(
                    "AGENT_LOOP_TICK_enrich_watch "
                    + json.dumps({"done": True, "reason": "stopped", "last": rec}, ensure_ascii=False),
                    flush=True,
                )
                break
        except Exception as e:  # noqa: BLE001
            print(
                "AGENT_LOOP_TICK_enrich_watch "
                + json.dumps({"error": str(e)[:200]}, ensure_ascii=False),
                flush=True,
            )


if __name__ == "__main__":
    main()
