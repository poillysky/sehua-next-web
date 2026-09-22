import sys
from pathlib import Path
sys.path.insert(0, ".")
from app.prefix.maker_names import resolve_maker_intro_for_prefix, PREFIX_INTRO
from app.scrap_library.embed import _prefix_blurb, _studio_blurb

print("APAK prefix intro", repr(resolve_maker_intro_for_prefix("APAK")))
print("APAK _prefix_blurb", repr(_prefix_blurb("APAK")))
print("APAKA studio", repr(_studio_blurb("APAKA")))
print("APAK studio", repr(_studio_blurb("APAK")))

# find scrap path
from app.core import maps_paths
# scrap root
import os
cands = list(Path(r"E:/Project/sehua-next-web").rglob("APAK-001"))
print("APAK-001 hits", cands[:5])
