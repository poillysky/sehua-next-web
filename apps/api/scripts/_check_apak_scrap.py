import sys
sys.path.insert(0, ".")
from app.prefix.maker_names import resolve_maker_intro_for_prefix, PREFIX_INTRO
from app.core.maps_paths import maps_dir
from pathlib import Path

# scrap library APAK
roots = [
    Path(r"E:/Project/sehua-next-web/data/scrap-library"),
    Path(r"E:/Project/sehua-next-web/apps/../data/scrap-library"),
]
for r in roots:
    p = r / "日本有码" / "APAK"
    print(r, "exists", r.exists(), "APAK", p.exists())
    if p.exists():
        print("  children", len(list(p.iterdir())))

print("PREFIX_INTRO APAK", PREFIX_INTRO.get("APAK"))
print("resolve APAK", repr(resolve_maker_intro_for_prefix("APAK")))
print("resolve APAKA", repr(resolve_maker_intro_for_prefix("APAKA")))
