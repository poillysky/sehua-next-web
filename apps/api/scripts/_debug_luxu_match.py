import sys
sys.path.insert(0, ".")
from app.prefix.maker_names import MAKER_I18N, MAKER_INTRO, _intro_for_maker_key

s = "LUXU"
print("direct", repr(_intro_for_maker_key(s)))
for canon, trip in MAKER_I18N.items():
    if s in trip or s == canon:
        print("MATCH", canon, trip, "->", MAKER_INTRO.get(canon))
    # substring traps
    if isinstance(trip, str) and s in trip:
        print("STR SUB", canon, trip)
    if isinstance(trip, (list, tuple)):
        for i, part in enumerate(trip):
            if isinstance(part, str) and s and s in part and s != part:
                print("PART SUB", canon, i, part)

# empty string trap
s2 = ""
for canon, trip in list(MAKER_I18N.items())[:5]:
    print("empty in trip?", canon, type(trip), (s2 in trip) if not isinstance(trip, (list,tuple)) else s2 in trip, trip)
