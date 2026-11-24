// Veronos Studio reply engine (runs every 10 minutes via pg_cron). Modeled on Series Supply's followup-reminders.
// Kash's flow (Nov 23): interested reply -> ask for a cell -> build the homepage -> send it by email + text
// -> preview is live 7 days -> 3 follow-ups during those 7 days to book the meeting.
// What runs on its own:
//  1) Syncs "Interested" leads from the Veronos campaigns (veronos_settings.campaigns) into veronos_leads.
//  2) Reads every reply to a Veronos inbox. Pulls a cell number out of the reply automatically.
//     Yeses Instantly didn't label still get added; questions/price talk get flagged "needs you".
//  3) 15-25 min after a yes: asks for their cell in the thread (or thanks them if they already gave it).
//  4) When a preview_link is saved for a lead, emails it in the thread (status Preview sent).
//  5) Follow-ups on day 2, 4 and 6 after the preview (link comes down on day 7). Any reply pauses them.
// Never sends on Sundays; first replies Mon-Sat 8am-8pm Central, follow-ups Mon-Fri only.
// GET ?key=K            run the engine (dry=1 to preview without sending)
// GET ?key=K&csv=1      the Google Sheet feed (=IMPORTDATA)
// POST {key,email,...}  update a lead: preview_link, status, meeting_at, plan, notes, cell, lost, clear (needs_you off)
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const API = "https://api.instantly.ai/api/v2";
const INBOX_RX = /veronos/i;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const CT = 6 * 3600e3; // Central time offset (close enough year-round for send windows)
const local = (t: number) => new Date(t - CT);
const isSunday = (t: number) => local(t).getUTCDay() === 0;
function elapsedNoSun(from: number, to: number) {
  let ms = 0, t = from;
  while (t < to) {
    const d = local(t);
    const next = Math.min(to, Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) + CT + 86400e3);
    if (!isSunday(t)) ms += next - t;
    t = next;
  }
  return ms;
}
async function ik(path: string, init: RequestInit = {}) {
  const key = Deno.env.get("INSTANTLY_API_KEY");
  if (!key) throw new Error("INSTANTLY_API_KEY not set");
  const r = await fetch(API + path, { ...init, headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", ...(init.headers || {}) } });
  const t = await r.text();
  if (!r.ok) throw new Error(`${path} ${r.status}: ${t.slice(0, 300)}`);
  return t ? JSON.parse(t) : {};
}
const toHtml = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1">$1</a>').replace(/\n/g, "<br/>");
const hash = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; };
const cleanReply = (body: string) => body.split(/\n\s*(?:On\s[\s\S]{5,200}?wrote:|On (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? |From: |-{3,}\s*Original|Sent from my|>)/i)[0].trim();
const OOO_RX = /out of (the )?office|on vacation|maternity|paternity|away (from|this week|until)|will (return|be back)|be back (in|on)|limited access to (my )?email|auto(matic)?[- ]reply/i;
const YES_RX = /\b(yes|yeah|yep|sure|go ahead|go for it|sounds (great|good)|love to|happy to|let'?s (see|do)|send it|interested|why not|please do|ok(ay)?)\b/i;
const NO_RX = /not interested|no thanks|no thank you|all set|we'?re (good|set)|remove me|unsubscribe|stop emailing|take me off|not at this time|happy with (our|my)|just (redid|redesigned|updated)/i;
const THANKS_RX = /^(hey|hi|thanks|thank you|awesome|great|perfect|appreciate|will do|sounds good|got it|ok|okay|cool|amazing)[\s\S]{0,60}$/i;
const PHONE_RX = /(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b/;
const phoneIn = (t: string) => { const m = t.match(PHONE_RX); return m ? `(${m[1]}) ${m[2]}-${m[3]}` : ""; };
// Questions, price talk or long notes go to Kash instead of an automatic reply.
const needsHuman = (t: string) => /\?/.test(t) || /\b(price|cost|how much|pricing|charge|budget|contract|catch)\b/i.test(t) || t.length > 400;

// ---- Copy (written as Kash; short, casual, no dashes) ----
// Kash's wording (Nov 24): email first, cell is optional, give a timeline.
const ASK_CELL = [
  (hi: string) => `${hi}\n\nSounds good, I'll send it here. If you have a cell, I'd love to text it over too so you can check it out on your phone. Could I grab your number?\n\nI should have it ready in the next day or two.\n\nKash`,
];
const GOT_CELL = (hi: string) => `${hi}\n\nPerfect, got it. I'll text it over as soon as it's ready.\n\nKash`;
const YES_WITH_CELL = (hi: string) => `${hi}\n\nSounds good, I'll send it here and text it over too. I should have it ready in the next day or two.\n\nKash`;
const PREVIEW = (hi: string, link: string) => `${hi}\n\nHere's your new homepage:\n\n${link}\n\nIt's live for 7 days so you can click around on your phone and computer. Let me know what you think!\n\nKash`;
const FU = (n: number, hi: string, book: string) => [
  `${hi}\n\nDid you get a chance to look at it? Happy to tweak anything, like colours, photos or wording.\n\nKash`,
  `${hi}\n\nIf you like it, I can get the full site built and live in about a week. Want to hop on a quick 10 minute call?\n\n${book ? book : "Just reply with a day and time that works for you."}\n\nKash`,
  `${hi}\n\nHeads up, the preview comes down tomorrow. If you want to keep it, just reply here and we'll find a time to chat.\n\nKash`,
][n - 1];
const FU_DAYS = [2, 4, 6];

const COLS: [string, string][] = [["replied_at", "Date replied"], ["status", "Status"], ["todo", "Needs you"], ["company", "Company"], ["first_name", "Contact"], ["email", "Email"],
  ["cell", "Cell (text it here)"], ["website", "Website"], ["city", "City"], ["niche", "Niche"], ["hook", "What's wrong with their site"], ["reply_snippet", "Their last reply"],
  ["preview_link", "Preview link"], ["preview_sent_at", "Preview sent"], ["expires", "Preview expires"], ["fu1_at", "Follow-up 1"], ["fu2_at", "Follow-up 2"], ["fu3_at", "Follow-up 3"],
  ["meeting_at", "Meeting"], ["plan", "Plan"], ["notes", "Notes"], ["office_phone", "Office phone"], ["campaign_name", "Campaign"]];
const ORDER = ["New yes", "Asked for cell", "Building", "Preview sent", "Meeting booked", "Won", "Lost"];
function csv(rows: any[]) {
  const esc = (v: unknown) => { if (v === null || v === undefined) return ""; const s = String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const day = (v: string) => (v ? local(new Date(v).getTime()).toISOString().slice(0, 10) : "");
  const out = [COLS.map((c) => esc(c[1])).join(",")];
  for (const r of rows) {
    const x = { ...r, replied_at: day(r.replied_at), preview_sent_at: day(r.preview_sent_at), fu1_at: day(r.fu1_at), fu2_at: day(r.fu2_at), fu3_at: day(r.fu3_at),
      expires: r.preview_sent_at ? day(new Date(new Date(r.preview_sent_at).getTime() + 7 * 86400e3).toISOString()) : "",
      todo: r.lost ? "" : r.needs_you ? (r.needs_you_why || "Reply to them") : "",
      campaign_name: /9361/.test(r.campaign || "") ? "Canada" : /5749/.test(r.campaign || "") ? "US" : "" };
    out.push(COLS.map((c) => esc(x[c[0]])).join(","));
  }
  return out.join("\n") + `\n\nUpdated,${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const { data: settings } = await sb.from("veronos_settings").select("k,v");
  const S = Object.fromEntries((settings || []).map((x: any) => [x.k, x.v]));
  let body: any = {};
  if (req.method === "POST") { try { body = await req.json(); } catch { /* empty */ } }
  if ((url.searchParams.get("key") || body.key) !== S.key) return new Response("forbidden", { status: 403 });

  // Sheet feed.
  if (url.searchParams.get("csv")) {
    const { data } = await sb.from("veronos_leads").select("*");
    const rows = (data || []).sort((a: any, b: any) => (Number(b.needs_you && !b.lost) - Number(a.needs_you && !a.lost)) || (ORDER.indexOf(a.status) - ORDER.indexOf(b.status)) || String(b.replied_at).localeCompare(String(a.replied_at)));
    return new Response(csv(rows), { headers: { "content-type": "text/csv; charset=utf-8", "cache-control": "no-store" } });
  }
  // Manual updates (Kash, or Claude on his behalf).
  if (req.method === "POST") {
    const email = String(body.email || "").toLowerCase().trim();
    if (!email) return new Response(JSON.stringify({ ok: false, error: "email required" }), { status: 400 });
    const patch: any = {};
    for (const k of ["preview_link", "status", "meeting_at", "plan", "notes", "cell", "lost"]) if (body[k] !== undefined) patch[k] = body[k];
    if (body.clear) patch.needs_you = false;
    if (patch.preview_link) { patch.status = "Building"; patch.needs_you = false; } // the engine sends it on the next run
    if (patch.status === "Meeting booked" || patch.status === "Won" || patch.status === "Lost") patch.needs_you = false;
    if (patch.status === "Lost") patch.lost = true;
    const { data, error } = await sb.from("veronos_leads").update(patch).eq("email", email).select("email,status").single();
    return new Response(JSON.stringify({ ok: !error, lead: data, error: error?.message }), { headers: { "content-type": "application/json" } });
  }

  const dry = S.enabled !== "true" || url.searchParams.get("dry") === "1";
  const force = url.searchParams.get("force") === "1";
  const camps = new Set(String(S.campaigns || "").split(",").map((x) => x.trim()).filter(Boolean));
  const now = new Date(), nowT = now.getTime();
  const hr = local(nowT).getUTCHours(), dow = local(nowT).getUTCDay();
  const replyHours = force || (dow !== 0 && hr >= 8 && hr < 20);          // Mon-Sat 8am-8pm Central
  const followHours = force || (dow >= 1 && dow <= 5 && hr >= 8 && hr < 18); // Mon-Fri 8am-6pm Central
  const report: any[] = [];
  const log = (email: string, step: string, inbox: string, result: string) => dry ? null : sb.from("veronos_log").insert({ email, step, inbox, result });
  const save = async (w: any, patch: any) => { Object.assign(w, patch); if (!dry) await sb.from("veronos_leads").update(patch).eq("email", w.email); };

  try {
    const { data: existing } = await sb.from("veronos_leads").select("*");
    const byEmail = new Map((existing || []).map((w: any) => [w.email.toLowerCase(), w]));
    const fromLead = (l: any, email: string, extra: any = {}) => {
      const p = l.payload || {};
      return { email, first_name: l.first_name || p.firstName || null, company: l.company_name || p.companyName || null, website: l.website || p.website || null,
        city: p.city || null, niche: p.nicheLine || p.service || null, hook: p.hook || null, office_phone: l.phone || p.phone || null,
        campaign: l.campaign || l.campaign_id || null, ...extra };
    };

    // 1) Interested leads from the Veronos campaigns.
    let after: string | undefined;
    for (let i = 0; i < 20; i++) {
      const res = await ik("/leads/list", { method: "POST", body: JSON.stringify({ filter: "FILTER_LEAD_INTERESTED", limit: 100, ...(after ? { starting_after: after } : {}) }) });
      for (const l of res.items || []) {
        const email = String(l.email || "").toLowerCase();
        if (!email || byEmail.has(email)) continue;
        const camp = String(l.campaign || l.campaign_id || "");
        const p = l.payload || {};
        if (!camps.has(camp) && p.hook === undefined && p.nicheLine === undefined) continue; // not a Veronos lead
        const row = fromLead(l, email, { status: "New yes", replied_at: (l.timestamp_last_reply || now.toISOString()), last_reply_at: l.timestamp_last_reply || null });
        if (!dry) { const { data } = await sb.from("veronos_leads").insert(row).select("*").single(); byEmail.set(email, data || row); } else byEmail.set(email, row);
        report.push({ email, action: "new yes added" });
      }
      if (!res.next_starting_after || !(res.items || []).length) break;
      after = res.next_starting_after; await sleep(800);
    }

    // 2) Every reply to a Veronos inbox: pick up cell numbers, sort new people, flag questions.
    const scanFrom = S.last_reply_scan ? new Date(S.last_reply_scan).getTime() : nowT - 3 * 86400e3;
    let newest = scanFrom, cursor = "";
    const seen = new Set<string>();
    for (let i = 0; i < 5; i++) {
      const r = await ik(`/emails?email_type=received&limit=100&sort_order=desc${cursor ? "&starting_after=" + cursor : ""}`);
      let older = false;
      for (const e of r.items || []) {
        const t = new Date(e.timestamp_email || e.timestamp_created).getTime();
        if (t <= scanFrom) { older = true; break; }
        newest = Math.max(newest, t);
        if (!INBOX_RX.test(String(e.eaccount || ""))) continue;
        const from = String(e.from_address_email || e.lead || "").toLowerCase();
        if (!from || seen.has(from)) continue; // newest reply per person only
        seen.add(from);
        const text = cleanReply(String(e.body?.text || e.content_preview || ""));
        const st = Number(e.i_status ?? e.lt_interest_status ?? NaN);
        if (st === 0 || OOO_RX.test(text)) continue;
        const cell = phoneIn(text);
        let w: any = byEmail.get(from) || byEmail.get(String(e.lead || "").toLowerCase());
        if (!w) {
          const no = NO_RX.test(text) || [-1, -2, -3].includes(st);
          if (no) continue; // Instantly already stopped their sequence
          let l: any = {};
          try { const lr = await ik("/leads/list", { method: "POST", body: JSON.stringify({ search: from, limit: 1 }) }); l = (lr.items || [])[0] || {}; await sleep(800); } catch { /* blank */ }
          const yes = YES_RX.test(text) || st === 1;
          const row = fromLead(l, from, { inbox: e.eaccount, replied_at: new Date(t).toISOString(), last_reply_at: new Date(t).toISOString(), reply_snippet: text.slice(0, 400),
            status: "New yes", ...(yes ? {} : { needs_you: true, needs_you_at: now.toISOString(), needs_you_why: "Maybe: reply personally" }) });
          if (!dry) { const { data } = await sb.from("veronos_leads").insert(row).select("*").single(); w = data || row; } else w = row;
          byEmail.set(from, w);
          report.push({ email: from, action: yes ? "yes (not labelled in Instantly): added" : "maybe: added, needs you" });
          continue;
        }
        const prev = w.last_reply_at ? new Date(w.last_reply_at).getTime() : 0;
        if (t <= prev + 60000 && w.reply_snippet) continue;
        const patch: any = { last_reply_at: new Date(t).toISOString(), reply_snippet: text.slice(0, 400), inbox: w.inbox || e.eaccount };
        if (cell && !w.cell) { patch.cell = cell; patch.cell_got_at = now.toISOString(); }
        if (NO_RX.test(text) && !YES_RX.test(text)) { patch.status = "Lost"; patch.lost = true; patch.needs_you = false; }
        else if (w.preview_sent_at && !THANKS_RX.test(text)) { patch.needs_you = true; patch.needs_you_at = now.toISOString(); patch.needs_you_why = "Replied to the preview"; }
        else if (needsHuman(text)) { patch.needs_you = true; patch.needs_you_at = now.toISOString(); patch.needs_you_why = "Question: reply personally"; }
        else if (patch.cell && w.asked_cell_at) { patch.pending_got_cell = true; }
        const pend = !!patch.pending_got_cell; delete patch.pending_got_cell;
        await save(w, patch);
        if (pend) w._gotCell = true;
        report.push({ email: from, action: patch.cell ? `cell saved ${patch.cell}` : patch.lost ? "said no: Lost" : patch.needs_you ? "flagged needs you" : "reply logged" });
      }
      if (older || !r.next_starting_after) break;
      cursor = r.next_starting_after; await sleep(1200);
    }
    if (!dry && newest > scanFrom) await sb.from("veronos_settings").upsert({ k: "last_reply_scan", v: new Date(newest).toISOString() });

    // 3) Automatic replies.
    let sends = 0;
    for (const w of byEmail.values() as any) {
      if (!w.email || w.lost || sends >= 20) continue;
      const first = w.first_name || "";
      const hi = first ? (/^Dr\.?\s/.test(first) ? `Hi ${first},` : `Hey ${first},`) : "Hey there,";
      // a) New yes: ask for their cell (or thank them if they already gave one).
      if (w.status === "New yes" && !w.asked_cell_at && !w.needs_you) {
        const yesAt = new Date(w.last_reply_at || w.replied_at || now).getTime();
        const wait = 15 + (hash(w.email) % 11);
        if (!force && nowT - yesAt < wait * 60e3) { report.push({ email: w.email, action: `asks for cell in ~${wait} min` }); continue; }
        if (!replyHours) { report.push({ email: w.email, action: "ask for cell waits for morning" }); continue; }
        const thread = await lastReceived(w.email);
        if (!thread) { report.push({ email: w.email, action: "no thread found yet" }); continue; }
        const text = cleanReply(String(thread.body?.text || thread.content_preview || ""));
        if (needsHuman(text)) { await save(w, { needs_you: true, needs_you_at: now.toISOString(), needs_you_why: "Question: reply personally", reply_snippet: text.slice(0, 400) }); report.push({ email: w.email, action: "yes with a question: needs you" }); continue; }
        const cell = w.cell || phoneIn(text);
        const msg = cell ? YES_WITH_CELL(hi) : ASK_CELL[hash(w.email) % ASK_CELL.length](hi);
        if (await threadReply(w, thread, cell ? "thanks (had cell)" : "ask for cell", msg)) {
          sends++;
          await save(w, { asked_cell_at: now.toISOString(), status: "Building", needs_you: true, needs_you_at: now.toISOString(), needs_you_why: "Build their homepage", ...(cell && !w.cell ? { cell, cell_got_at: now.toISOString() } : {}) });
        }
        continue;
      }
      // b) They sent their cell after we asked: short thanks.
      if (w._gotCell && replyHours) {
        const thread = await lastReceived(w.email);
        if (thread && await threadReply(w, thread, "got cell", GOT_CELL(hi))) sends++;
        continue;
      }
      // c) Preview saved: email it.
      if (w.preview_link && !w.preview_sent_at) {
        if (!replyHours) { report.push({ email: w.email, action: "preview waits for morning" }); continue; }
        const thread = await lastReceived(w.email);
        if (thread && await threadReply(w, thread, "preview", PREVIEW(hi, w.preview_link))) {
          sends++;
          await save(w, { preview_sent_at: now.toISOString(), status: "Preview sent", needs_you: !!w.cell, needs_you_at: now.toISOString(), needs_you_why: w.cell ? `Text the preview to ${w.cell}` : null });
        }
        continue;
      }
      // d) Follow-ups on day 2, 4, 6 after the preview. A reply pauses them (needs_you).
      if (w.status === "Preview sent" && w.preview_sent_at && !(w.needs_you && /Replied/.test(w.needs_you_why || ""))) {
        const n = !w.fu1_at ? 1 : !w.fu2_at ? 2 : !w.fu3_at ? 3 : 0;
        if (!n) continue;
        const since = elapsedNoSun(new Date(w.preview_sent_at).getTime(), nowT);
        if (since < FU_DAYS[n - 1] * 86400e3) continue;
        const lastReply = w.last_reply_at ? new Date(w.last_reply_at).getTime() : 0;
        if (lastReply > new Date(w.preview_sent_at).getTime() && !THANKS_RX.test(w.reply_snippet || "")) continue;
        if (!followHours) { report.push({ email: w.email, action: `follow-up ${n} waits for weekday hours` }); continue; }
        const thread = await lastReceived(w.email);
        if (thread && await threadReply(w, thread, `follow-up ${n}`, FU(n, hi, S.booking_link || ""))) { sends++; await save(w, { [`fu${n}_at`]: now.toISOString() }); }
      }
    }

    async function lastReceived(email: string) {
      const em = await ik(`/emails?lead=${encodeURIComponent(email)}&limit=10&sort_order=desc`);
      await sleep(2500);
      return (em.items || []).find((e: any) => e.ue_type === 2 && INBOX_RX.test(String(e.eaccount || ""))) || null;
    }
    async function threadReply(w: any, thread: any, label: string, text: string) {
      const inbox = thread.eaccount;
      const subject = /^re:/i.test(thread.subject || "") ? thread.subject : `Re: ${thread.subject || "homepage idea"}`;
      if (dry) { report.push({ email: w.email, action: `WOULD send ${label}`, from: inbox, text }); return false; }
      try {
        await ik("/emails/reply", { method: "POST", body: JSON.stringify({ reply_to_uuid: thread.id, eaccount: inbox, subject, body: { text, html: toHtml(text) } }) });
        await save(w, { inbox, last_touch: now.toISOString() });
        await log(w.email, label, inbox, "sent");
        report.push({ email: w.email, action: `sent ${label}`, from: inbox });
        return true;
      } catch (e) {
        await log(w.email, label, inbox, String(e).slice(0, 400));
        report.push({ email: w.email, action: `${label} FAILED`, error: String(e).slice(0, 200) });
        return false;
      }
    }
  } catch (e) { report.push({ error: String(e).slice(0, 400) }); }
  return new Response(JSON.stringify({ dry_run: dry, at: now.toISOString(), report }, null, 2), { headers: { "content-type": "application/json" } });
});
