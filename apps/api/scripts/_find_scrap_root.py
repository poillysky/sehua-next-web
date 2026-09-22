import sys
sys.path.insert(0, ".")
from app.core.db import connect, media_dir, ROOT
print("ROOT", ROOT)
print("media_dir", media_dir())
p = media_dir() / "scrap-library"
print("scrap-library", p, p.exists())
if p.exists():
    dirs = [x.name for x in p.iterdir() if x.is_dir()]
    print("regions", dirs[:20])
