"""Read-only: where do owner/named rows sit in the sheet, by status and country."""
from collections import Counter
import finder as F
for st in ["new", "Instantly", "skip", "Bad email", "Not a fit", "Gmail"]:
    rows = F.sheet_get(st, 40000)
    c = Counter(((r.get("country") or "CA").upper(), (r.get("email_type") or "(blank)")) for r in rows)
    print(st, len(rows), dict(c))
