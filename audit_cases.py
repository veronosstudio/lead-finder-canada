"""Run the real site check on known cases + report every result type from a fresh search slice."""
import finder as F
cases = [("Marathon Food And Beverage Inc", "https://faracilaw.com", "lawyer"), ("New Hope Community Church", "https://newhopecochrane.com", "church"),
         ("Canvas Construction", "https://canvasconstruction.com", "contractor"), ("Gray Law P.C.", "https://graylawil.com", "lawyer"),
         ("Kingsley Law Group", "https://kingsleylawgroup.com", "lawyer")]
for name, site, cat in cases:
    c = {"osm_id": "test", "business": name, "category": cat, "town": "Chicago", "province": "IL", "website": site,
         "domain": F.domain(site), "phone": "", "osm_email": ""}
    _, result, lead = F.check(c)
    print(f"CASE {name[:34]:35} {site:32} -> {result}" + (f"  email={lead['email']}" if lead else ""))
