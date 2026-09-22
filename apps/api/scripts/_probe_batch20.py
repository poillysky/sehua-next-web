import sys, time
sys.path.insert(0, ".")
import httpx
from app.prefix.catalog_dmm import content_id, gql_ppv, guess_digits

prefs = "ACRN ADZ ALD AMBI AMCP ARSO ASW BEAF BUR CHUC CWPBD DDH DMOW DOKS DSE ECB ELO EROFV EUUD EVDV".split()
http = httpx.Client(follow_redirects=True, timeout=10.0)
for p in prefs:
    maker = ""
    for dig in guess_digits(p):
        for n in (1, 50, 100):
            info = gql_ppv(http, content_id(p, n, dig), timeout=8.0)
            if info and str(info.get("maker_ja") or "").strip():
                maker = str(info["maker_ja"]).strip()
                break
            time.sleep(0.02)
        if maker:
            break
    print(f"{p}\t{maker or '-'}")
http.close()
