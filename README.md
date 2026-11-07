# Veronos lead finder: Canada

Runs every night on GitHub (about 1:17 AM Edmonton) and costs nothing: no paid services, no AI.

**What it does**
1. Pulls small businesses that list a website from OpenStreetMap, one province and category group at a time (Alberta first, then BC, SK, MB, ON, the Maritimes and QC). It picks up where the last night stopped.
2. Visits each website and scores how dated or DIY it looks: not built for phones, old copyright year, no HTTPS, DIY builders (Wix, Weebly, GoDaddy...), old themes, no main headline, phone number not tappable. Chains, modern agency sites and dead sites are dropped.
3. Keeps only email addresses the business publishes on its own site (home, contact or about page).
4. Stops at 100 qualified leads or 45 minutes.

**Where the results go**
- `leads/YYYY-MM-DD.csv`: that night's leads (business, category, town, province, website, email, where the email was found, phone, dated score, why it's dated).
- `data/seen.csv`: every business ever checked, so nobody is checked or delivered twice.
- `state/last_run.json`: how the last run went. `state/progress.json`: where it is in the province/category list.

**Run it now:** Actions tab > "Nightly lead finder (Canada)" > Run workflow.
**Change the daily number or categories:** edit `config.json`.

US businesses are handled by a separate app, so the two never overlap.

## Instantly export (with email hook)
`SHEET_URL=... SHEET_TOKEN=... python export_instantly.py status=new out=instantly.csv`
Adds a `hook` column (from `hooks.py`) that fits "Noticed your site {{hook}}." — e.g. "is pretty tough to read on a phone",
'shows a "Not secure" warning in Chrome', "still says ©2019 at the bottom", or "was getting a bit dated". Only states what the check found.
Tiers (column `tier` in the sheet, set automatically): **A** = clearly old at a glance (not phone-friendly, "Not secure",
©2022 or older, Flash/table/font layouts, ancient builders) → send first. **B** = borderline (DIY builders + invisible signals)
→ send later with a softer pitch that doesn't call the site old. `export_instantly.py tier=A` exports A only.
