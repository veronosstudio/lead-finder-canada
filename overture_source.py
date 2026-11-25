"""Overture Maps (free, open business data) -> the same website check + owner-first email finder -> US sheet.

Usage: CONFIG=config_us.json python overture_source.py [target=100] [metros=Phoenix,Dallas-Fort Worth] [release=2026-11-18.0]
Rows go in with osm_id "ov/<overture id>" so they can be told apart (and moved to their own tab later).
"""
import os, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed
import duckdb
import finder as F
import refine as R

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
TARGET = int(args.get("target", "100"))
RELEASE = args.get("release", "2026-11-18.0")
METROS = [m.strip() for m in args.get("metros", "Phoenix,Dallas-Fort Worth").split(",") if m.strip()]
if args.get("metros", "") in ("", "auto"):          # nightly: each of the 4 searches takes every 4th metro
    METROS = list(F.CFG["metros"])[F.SHARD::F.SHARDS]
# most valuable first; matched against Overture's basic_category / taxonomy primary
NICHES = [  # the 3 launch niches first, across every metro, then the rest
    r"dentist|orthodont|dental|endodont|periodont|oral_surgeon",
    r"roof|hvac|heating|air_condition|plumb|electrician|electrical_contractor",
    r"lawyer|attorney|law_firm|legal",
    r"contractor|remodel|construction|builder|window|glass|solar|pool|fence|garage_door|cabinet|flooring",
    r"chiropract|physical_therap|physiotherap|optometr|veterinar|medical_spa|dermatolog|podiatr|audiolog",
    r"accountant|accounting|tax|financial|insurance|wealth", r"landscap|lawn|pest|tree_service", r"auto_body|collision",
    r"funeral"]
F.SEEN = os.path.join(F.ROOT, "data", f"seen-overture{F.SUFFIX}.csv")   # one file per search (no git clashes)

CON = None
def query(metro, pat):
    global CON
    if CON is None:
        CON = duckdb.connect(); CON.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    s, w, n, e = F.CFG["metros"][metro][1]
    sql = f"""
      SELECT id, names.primary AS name, basic_category AS cat, taxonomy.primary AS tax, websites, phones, emails,
             addresses[1].locality AS town, addresses[1].region AS region, confidence, operating_status,
             brand.names.primary AS brand, (bbox.xmin + bbox.xmax)/2 AS lon, (bbox.ymin + bbox.ymax)/2 AS lat
      FROM read_parquet('s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*', hive_partitioning=1)
      WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}
        AND websites IS NOT NULL AND len(websites) > 0 AND confidence >= 0.6
        AND (operating_status IS NULL OR operating_status = 'open')
        AND regexp_matches(lower(coalesce(basic_category, '') || ' ' || coalesce(taxonomy.primary, '')), ?)"""
    t = time.time(); rows = CON.execute(sql, [pat]).fetchall(); cols = [d[0] for d in CON.description]
    F.log(f"overture: {metro} / {pat.split('|')[0]}: {len(rows)} places with a website ({time.time() - t:.0f}s)")
    return [dict(zip(cols, r)) for r in rows]

def main():
    seen_ids, seen_domains = F.load_seen()
    leads, seen_rows, checked = [], [], 0
    from collections import Counter
    for pat in NICHES:                       # best niche in every metro before the next niche
        for metro in METROS:
            if len(leads) >= TARGET: break
            places = query(metro, pat)
            pool, by_dom = [], {}
            for p in places:
                if p.get("brand"): continue
                if any(w in (p.get("name") or "").lower() for w in F.CFG.get("skip_name_words", [])): continue
                site = F.norm_site(p["websites"][0]); d = F.domain(site)
                if not d or any(b in site.lower() for b in F.BAD_HOSTS): continue
                by_dom.setdefault(d, []).append((p, site))
            for d, ps in by_dom.items():
                if len(ps) > 2 or d in seen_domains or f"ov/{ps[0][0]['id']}" in seen_ids: continue   # 3+ places on one site = chain
                p, site = ps[0]
                pool.append({"osm_id": f"ov/{p['id']}", "business": p["name"] or "", "category": p["cat"] or p["tax"] or "",
                             "town": p["town"] or metro, "province": (p["region"] or "").upper()[-2:] if re.fullmatch(r"(?:[A-Z]{2}-)?[A-Za-z]{2}", p["region"] or "") else F.CFG["metros"][metro][0],
                             "website": site, "domain": d, "phone": (p["phones"] or [""])[0], "osm_email": (p["emails"] or [""])[0],
                             "lat": p["lat"], "lon": p["lon"]})
            random.shuffle(pool)
            F.log(f"  {len(pool)} new websites to check")
            for i in range(0, len(pool), F.CFG["workers"] * 4):          # stop soon after the target, not at the end of the pool
                if len(leads) >= TARGET: break
                with ThreadPoolExecutor(F.CFG["workers"]) as ex:
                    for fut in as_completed([ex.submit(F.check, c) for c in pool[i:i + F.CFG["workers"] * 4]]):
                        c, result, lead = fut.result(); checked += 1
                        seen_ids.add(c["osm_id"]); seen_domains.add(c["domain"])
                        seen_rows.append([c["osm_id"], c["domain"], F.TODAY, result])
                        if lead and len(leads) < TARGET:
                            leads.append(lead); F.log(f"  LEAD {lead['business']} ({lead['town']}) {lead['email']} [{lead.get('email_type')}] :: {lead['why_dated']}")
            F.log(f"overture: {checked} checked so far, {len(leads)} leads")
    F.append_seen(seen_rows)
    time.sleep(F.SHARD * 4)   # many searches at once: take turns writing to the sheet
    added = F.post_to_sheet([{k: v for k, v in l.items() if not k.startswith("_")} for l in leads]) if leads else 0
    F.log(f"DONE overture: checked {checked}, leads {len(leads)}, sheet added {added}, "
          f"hit rate {len(leads) / max(1, checked):.1%}, owner/manager emails {sum(1 for l in leads if l.get('email_type') in ('owner', 'manager'))}, "
          f"named greetings {sum(1 for l in leads if l.get('first_name'))}")

if __name__ == "__main__":
    main()
