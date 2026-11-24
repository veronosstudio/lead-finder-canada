// Veronos Studio reply engine (runs every 10 minutes via pg_cron). Modeled on Series Supply's followup-reminders.
// Kash's flow (Nov 24): interested reply -> Kash alerted -> builds the homepage -> link emailed in their thread (offers a phone walkthrough)
// -> preview is live 7 days -> 3 follow-ups during those 7 days to book the meeting.
// What runs on its own:
//  1) Syncs "Interested" leads from the Veronos campaigns (veronos_settings.campaigns) into veronos_leads.
//  2) Reads every reply to a Veronos inbox. Notes a phone number if they volunteer one (never asks).
//     Yeses Instantly didn't label still get added; questions/price talk get flagged "needs you".
//  3) A yes is NOT auto-answered: Kash gets an alert to build the homepage; the first reply they get is the link.
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
// "We received your message" auto-acknowledgements (skipped unless they also say yes).
const AUTOACK_RX = /thank you for (your (e-?mail|message|inquiry)|contacting)|we have received your (message|e-?mail|inquiry)|(this is an )?automated (response|message)|do not reply to this (e-?mail|message)/i;
const YES_RX = /\b(yes|yeah|yep|sure|go ahead|go for it|sounds (great|good)|love to|happy to|let'?s (see|do)|send it|interested|why not|please do|ok(ay)?)\b/i;
const NO_RX = /(?:do not|don'?t|dont) (?:contact|email|e-mail|message) me|going to pass|i'?ll pass|(?:have|got) someone else|not interested|no thanks|no thank you|all set|we'?re (good|set)|remove me|unsubscribe|stop emailing|take me off|not at this time|happy with (our|my)|just (redid|redesigned|updated)/i;
const OPTOUT_RX = /(?:do not|don'?t|dont) (?:contact|email|e-mail|message) me|unsubscribe|remove me|stop emailing|take me off/i; // always wins over a "yes" word
const THANKS_RX = /^(hey|hi|thanks|thank you|awesome|great|perfect|appreciate|will do|sounds good|got it|ok|okay|cool|amazing)[\s\S]{0,60}$/i;
const PHONE_RX = /(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b/;
const phoneIn = (t: string) => { const m = t.match(PHONE_RX); return m ? `(${m[1]}) ${m[2]}-${m[3]}` : ""; };
// Questions, price talk or long notes go to Kash instead of an automatic reply.
const needsHuman = (t: string) => /\?/.test(t) || /\b(price|cost|how much|pricing|charge|budget|contract|catch)\b/i.test(t) || t.length > 400;

// ---- Copy (written as Kash; short, casual, no dashes) ----
// Email v3 (Kash, Nov 24): the homepage is "already built", so a yes gets no auto-reply; the first reply is the link.
// Instant heads-up to Kash on every new yes (and maybe), via Resend.
async function notifyKash(S: any, w: any, text: string) {
  const key = Deno.env.get("RESEND_API_KEY"); const to = S.notify_email;
  if (!key || !to) return;
  const body = `New Veronos yes: ${w.company || w.email}${w.city ? " (" + w.city + ")" : ""}\n\nThey said: "${text.slice(0, 300)}"\n\nSite: ${w.website || "-"}\nEmail: ${w.email}\nPhone they gave: ${w.cell || "none"}\nWhat we noticed: ${w.hook || "-"}\n\nThey were told it's already built. Build it now and send the link (save the preview link and it goes out in their thread).`;
  try {
    await fetch("https://api.resend.com/emails", { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from: S.notify_from || "Veronos alerts <logan@seriessupply.com>", to: [to], subject: `New yes: ${w.company || w.email}`, text: body }) });
  } catch { /* alert is best-effort */ }
}
const PREVIEW = (hi: string, link: string) => `${hi}\n\nHere's your new homepage:\n\n${link}\n\nIt's live for 7 days so you can click around on your phone and computer. Let me know what you think! Happy to walk you through it over the phone too if that's easier.\n\nKash`;
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
  const J = (b: unknown, s = 200) => new Response(JSON.stringify(b, null, 1), { status: s, headers: { "content-type": "application/json" } });
  const veronosThread = async (email: string) => {
    const em = await ik(`/emails?lead=${encodeURIComponent(email)}&limit=12&sort_order=desc`);
    return (em.items || []).filter((e: any) => INBOX_RX.test(String(e.eaccount || "")) || INBOX_RX.test(String(e.to_address_email_list || "")));
  };
  // Reply desk for the twice-daily check-in: everyone flagged "needs you", with the thread.
  if (url.searchParams.get("desk")) {
    const { data } = await sb.from("veronos_leads").select("*").eq("needs_you", true).or("lost.is.null,lost.eq.false").order("needs_you_at", { ascending: true });
    const people: any[] = [];
    for (const w of data || []) {
      let thread: any[] = [];
      try {
        const items = await veronosThread(w.email);
        thread = items.map((e: any) => ({ at: e.timestamp_email, who: e.ue_type === 2 ? "them" : "kash", text: cleanReply(String(e.body?.text || e.content_preview || "")).slice(0, 600) })).reverse();
        await sleep(900);
      } catch { /* optional */ }
      people.push({ email: w.email, first_name: w.first_name, company: w.company, website: w.website, city: w.city, niche: w.niche, hook: w.hook, status: w.status,
        why: w.needs_you_why, cell: w.cell, preview_link: w.preview_link, their_reply: w.reply_snippet, notes: w.notes, thread });
    }
    return J({ count: people.length, people });
  }
  // Manual updates (Kash, or Claude on his behalf). With text: sends Kash's approved reply in their thread.
  if (req.method === "POST") {
    const email = String(body.email || "").toLowerCase().trim();
    if (!email) return new Response(JSON.stringify({ ok: false, error: "email required" }), { status: 400 });
    if (body.text) {
      const items = await veronosThread(email);
      const last = items.find((e: any) => e.ue_type === 2) || items[0];
      if (!last) return J({ ok: false, error: "no Veronos thread for " + email }, 409);
      const newest = items[0];
      if (!body.force && newest && newest.ue_type !== 2 && last && new Date(newest.timestamp_email).getTime() > new Date(last.timestamp_email).getTime())
        return J({ ok: false, error: "Kash already replied after their latest message. Not sent (force:true to send anyway)." }, 409);
      const inbox = last.ue_type === 2 ? last.eaccount : (last.eaccount || "");
      const subject = /^re:/i.test(last.subject || "") ? last.subject : `Re: ${last.subject || "homepage idea"}`;
      const text = String(body.text);
      await ik("/emails/reply", { method: "POST", body: JSON.stringify({ reply_to_uuid: last.id, eaccount: inbox, subject, body: { text, html: toHtml(text) } }) });
      await sb.from("veronos_leads").update({ needs_you: false, last_touch: new Date().toISOString(), inbox }).eq("email", email);
      await sb.from("veronos_log").insert({ email, step: "personal reply (approved by Kash)", inbox, result: "sent" });
      return J({ ok: true, from: inbox, subject });
    }
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
        if (st === 0 || OOO_RX.test(text) || (AUTOACK_RX.test(text) && !YES_RX.test(text))) continue;
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
          if (!dry && !yes) await notifyKash(S, w, text);
          report.push({ email: from, action: yes ? "yes (not labelled in Instantly): added" : "maybe: added, needs you" });
          continue;
        }
        const prev = w.last_reply_at ? new Date(w.last_reply_at).getTime() : 0;
        if (t <= prev + 60000 && w.reply_snippet) continue;
        const patch: any = { last_reply_at: new Date(t).toISOString(), reply_snippet: text.slice(0, 400), inbox: w.inbox || e.eaccount };
        if (cell && !w.cell) { patch.cell = cell; patch.cell_got_at = now.toISOString(); }
        if ((NO_RX.test(text) && !YES_RX.test(text)) || OPTOUT_RX.test(text)) { patch.status = "Lost"; patch.lost = true; patch.needs_you = false; }
        else if (w.preview_sent_at && !THANKS_RX.test(text)) { patch.needs_you = true; patch.needs_you_at = now.toISOString(); patch.needs_you_why = "Replied to the preview"; }
        else if (needsHuman(text)) { patch.needs_you = true; patch.needs_you_at = now.toISOString(); patch.needs_you_why = "Question: reply personally"; }
        await save(w, patch);
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
      // a) New yes (Kash, Nov 24): no automatic reply. Email 1 says the homepage is already built, so the first
      //    message back must BE the homepage. Flag it for Kash right away; he builds it and saves the preview link,
      //    and the engine emails the link in their thread (step c).
      if (w.status === "New yes" && !w.asked_cell_at && !w.needs_you) {
        const thread = await lastReceived(w.email);
        const text = thread ? cleanReply(String(thread.body?.text || thread.content_preview || "")) : String(w.reply_snippet || "");
        const why = needsHuman(text) ? "Build their homepage, then reply with the link (they asked something too)" : "Build their homepage, then send the link";
        await save(w, { asked_cell_at: now.toISOString(), status: "Building", needs_you: true, needs_you_at: now.toISOString(), needs_you_why: why, reply_snippet: text.slice(0, 400) });
        if (!dry) await notifyKash(S, w, text);
        report.push({ email: w.email, action: "yes: flagged for Kash to build" });
        continue;
      }
      // c) Preview saved: email it.
      if (w.preview_link && !w.preview_sent_at) {
        if (!replyHours) { report.push({ email: w.email, action: "preview waits for morning" }); continue; }
        const thread = await lastReceived(w.email);
        if (thread && await threadReply(w, thread, "preview", PREVIEW(hi, w.preview_link))) {
          sends++;
          await save(w, { preview_sent_at: now.toISOString(), status: "Preview sent", needs_you: false, needs_you_why: null });
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
