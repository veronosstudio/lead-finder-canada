"""Read-only: show chosen rows and what the skipped rows look like (no changes to the sheet)."""
import re, sys
from collections import Counter
import finder as F
names = re.compile(sys.argv[1] if len(sys.argv) > 1 else "desert shores|amber custom|glover", re.I)
rows = []
for st in ["new", "skip", "Instantly", "Gmail"]:
    for r in F.sheet_get(st, 10000): r["status"] = st; rows.append(r)
for r in rows:
    if names.search(r.get("business", "")):
        print("ROW |", r["business"], "|", r.get("website"), "|", r["status"], "|", r.get("service"), "|", r.get("score"), "|", r.get("why_dated"))
c = Counter()
for r in rows:
    if r["status"] != "skip": continue
    parts = [p for p in (r.get("why_dated") or "").lower().split("; ") if p and not re.search(r"licensed|spends|runs", p)]
    parts = sorted(re.sub(r"\d{4}", "YYYY", p) for p in parts)
    c[" + ".join(parts)] += 1
for k, n in c.most_common(30): print(f"SKIP {n:5d} :: {k}")
