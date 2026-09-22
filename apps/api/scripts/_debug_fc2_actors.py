# -*- coding: utf-8 -*-
from pathlib import Path
from app.scrap_library.embed import (
    TABLE,
    ensure_schema,
    get_meta_pool,
    get_settings,
    resolve_root,
)
from app.scrap_library.nfo import parse_nfo

ensure_schema()
pool = get_meta_pool()
root = resolve_root(get_settings().get("root")).resolve()
with pool.connection() as c, c.cursor() as cur:
    cur.execute(
        f"""
        SELECT code, rel_path, source_text
        FROM {TABLE}
        WHERE upper(prefix)='FC2PPV'
          AND source_text LIKE %s
        LIMIT 8
        """,
        ("%女优：%",),
    )
    rows = [dict(r) for r in (cur.fetchall() or [])]

out = Path(__file__).with_name("_debug_fc2_actors_out.txt")
lines: list[str] = []
for d in rows:
    lines.append(f"CODE {d.get('code')}")
    for line in str(d.get("source_text") or "").splitlines():
        if line.startswith(("女优", "标签", "类型")):
            lines.append(f"  {line}")
    folder = root / Path(str(d.get("rel_path") or ""))
    nfos = list(folder.glob("*.nfo")) if folder.is_dir() else []
    if nfos:
        meta = parse_nfo(nfos[0])
        lines.append(f"  actors={meta.get('actors')!r}")
        lines.append(f"  tags={(meta.get('tags') or [])[:12]!r}")
        lines.append(f"  genres={(meta.get('genres') or [])[:12]!r}")
        # peek raw actor nodes
        import xml.etree.ElementTree as ET

        raw = nfos[0].read_text(encoding="utf-8", errors="replace")
        root_el = ET.fromstring(raw)
        actor_names = [
            (a.findtext("name") or "").strip()
            for a in root_el.findall(".//actor")
        ]
        lines.append(f"  xml_actors={actor_names!r}")
    lines.append("---")
out.write_text("\n".join(lines), encoding="utf-8")
print("wrote", out, "n=", len(rows))
