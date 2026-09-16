import json
from pathlib import Path

rows = []
for p in sorted(Path("_gap_reports").glob("e2e_analyze_*.json")):
    rows.append(json.loads(p.read_text(encoding="utf-8")))

print(f"{'id':12} {'fetch':5} {'acc':5} issues")
for d in rows:
    print(
        f"{str(d.get('id')):12} {str(d.get('fetchOk')):5} {str(d.get('accuracyOk')):5} "
        f"{d.get('issues')}"
    )
