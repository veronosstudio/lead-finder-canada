"""Read-only: what's waiting in the sheet (status=new) by country, email type and date."""
from collections import Counter
import finder as F
rows = F.sheet_get("new", 20000)
print("new rows returned:", len(rows))
print("keys on a recent row:", sorted(rows[-1].keys()) if rows else None)
c = Counter(((r.get("country") or "CA").upper(), (r.get("email_type") or "(blank)"), (r.get("date") or "")[:10]) for r in rows)
for k, n in sorted(c.items(), key=lambda x: (x[0][0], x[0][2], x[0][1])): print(k, n)
print("tiers:", Counter((r.get("tier") or "(blank)") for r in rows))
