from pathlib import Path
text = Path("scripts/_emit_fill_out.txt").read_text(encoding="utf-8")
# extract makers section
a = text.split("===== CHAT: ALL MAKERS =====")[1]
makers_part, prefs_part = a.split("===== CHAT: ALL PREFIXES")
makers_lines = [l for l in makers_part.strip().splitlines() if l.strip()]
print(f"MAKERS={len(makers_lines)}")
for l in makers_lines:
    print(l)
