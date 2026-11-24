// veronos-forms: receives website contact forms for Veronos client sites and emails them.
// Preview mode (site.live = false): every enquiry goes to Kash's notify_email, never to the client.
// Live mode: goes to the client's address, with Reply-To set to the person who wrote in.
import { createClient } from "jsr:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type",
};
const J = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...CORS, "Content-Type": "application/json" } });
const clip = (v: unknown, n: number) => (typeof v === "string" ? v.trim().slice(0, n) : "");

async function sha(s: string) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s + "veronos-forms"));
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
  if (req.method !== "POST") return J({ ok: false, error: "method" }, 405);
  let b: Record<string, unknown>;
  try { b = await req.json(); } catch { return J({ ok: false, error: "bad json" }, 400); }

  // Bots: honeypot filled, or submitted faster than a human could type. Pretend success.
  if (clip(b.website, 200) || (typeof b.t === "number" && b.t < 2500)) return J({ ok: true });

  const site = clip(b.site, 80);
  const name = clip(b.name, 120), email = clip(b.email, 200), phone = clip(b.phone, 40);
  const matter = clip(b.matter, 80), message = clip(b.message, 4000);
  if (!name || (!email && !phone)) return J({ ok: false, error: "Please add your name and a phone number or email." }, 422);
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return J({ ok: false, error: "That email address doesn't look right." }, 422);

  const { data: s } = await sb.from("veronos_form_sites").select("*").eq("slug", site).maybeSingle();
  if (!s) return J({ ok: false, error: "unknown site" }, 404);

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "na";
  const ip_hash = await sha(ip);
  const since = new Date(Date.now() - 3600_000).toISOString();
  const { count } = await sb.from("veronos_form_leads").select("id", { count: "exact", head: true }).eq("ip_hash", ip_hash).gte("created_at", since);
  if ((count ?? 0) >= 5) return J({ ok: false, error: "Too many messages from here. Please call the office instead." }, 429);

  const { data: settings } = await sb.from("veronos_settings").select("k,v");
  const S: Record<string, string> = Object.fromEntries((settings ?? []).map((r: { k: string; v: string }) => [r.k, r.v]));
  const to = s.live ? s.client_email : S.notify_email;
  const from = S.forms_from || S.notify_from || "Website enquiries <logan@seriessupply.com>";

  const { data: row } = await sb.from("veronos_form_leads").insert({ site, name, email, phone, matter, message, ip_hash, delivered_to: to }).select("id").single();

  const lines = [
    s.live ? "" : `[PREVIEW TEST] On the live site this would go to ${s.client_email}.\n`,
    `New enquiry from the ${s.client_name} website`,
    ``,
    `Name: ${name}`,
    `Phone: ${phone || "(not given)"}`,
    `Email: ${email || "(not given)"}`,
    `About: ${matter || "(not chosen)"}`,
    ``,
    message ? `Message:\n${message}` : "(No message added)",
    ``,
    email ? `Hit reply to answer ${name} directly.` : `Call ${name} back at ${phone}.`,
  ].filter((l, i) => i > 0 || l);

  const key = Deno.env.get("RESEND_API_KEY");
  let delivered = false, error = "";
  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from, to: [to],
        subject: `${s.live ? "" : "[Preview] "}New website enquiry: ${name}${matter ? ` (${matter})` : ""}`,
        text: lines.join("\n"),
        ...(email ? { reply_to: email } : {}),
      }),
    });
    delivered = r.ok; if (!r.ok) error = (await r.text()).slice(0, 300);
  } catch (e) { error = String(e).slice(0, 300); }
  if (row) await sb.from("veronos_form_leads").update({ delivered, error: error || null }).eq("id", row.id);

  if (!delivered) return J({ ok: false, error: "We couldn't send that just now. Please call the office." }, 502);
  return J({ ok: true });
});
