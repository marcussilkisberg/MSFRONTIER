// Supabase Edge Function "contact": receives the site's forms, checks the spam test, stores the message in
// bank.inbox and emails it to Marcus through Resend. Replying to the email replies to the sender.
//
// Secrets to set in Supabase (Edge Functions → Secrets): RESEND_API_KEY, ALERT_EMAIL, TURNSTILE_SECRET,
// and optionally ALERT_FROM (e.g. "MSFrontier forms <forms@msfrontier.org>") and ALLOWED_ORIGINS
// (comma-separated, e.g. "https://msfrontier.org,https://www.msfrontier.org,https://screenshot-to-pixel-perfect-519.lovable.app").
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided by Supabase automatically.
// In the function's settings, turn OFF "Enforce JWT verification": the site calls it with the publishable key and the
// Turnstile check protects it instead.

import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const KINDS: Record<string, string> = {
  contact: "Contact form",
  results_known: "I know where the results are",
  claim_suggestion: "Suggest a claim to check",
  correction: "Report an error",
  other: "Message",
};

const env = (k: string) => Deno.env.get(k) ?? "";
const allowed = env("ALLOWED_ORIGINS").split(",").map((s) => s.trim()).filter(Boolean);

function cors(origin: string | null) {
  const ok = origin && (allowed.length === 0 || allowed.includes(origin));
  return {
    "Access-Control-Allow-Origin": ok ? origin! : allowed[0] ?? "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Vary": "Origin",
  };
}

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
const clip = (v: unknown, n: number) => (typeof v === "string" ? v.trim().slice(0, n) : "");

Deno.serve(async (req) => {
  const headers = { ...cors(req.headers.get("origin")), "Content-Type": "application/json" };
  if (req.method === "OPTIONS") return new Response("ok", { headers });
  if (req.method !== "POST") return new Response(JSON.stringify({ ok: false }), { status: 405, headers });

  let b: Record<string, unknown>;
  try {
    b = await req.json();
  } catch {
    return new Response(JSON.stringify({ ok: false, error: "bad_request" }), { status: 400, headers });
  }

  // Honeypot: a hidden field people never fill in. Pretend success so bots learn nothing.
  if (clip(b.website, 200)) return new Response(JSON.stringify({ ok: true }), { headers });

  // Cloudflare Turnstile spam test
  const token = clip(b.turnstile_token, 4000);
  const v = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body: new URLSearchParams({ secret: env("TURNSTILE_SECRET"), response: token }),
  }).then((r) => r.json()).catch(() => ({ success: false }));
  if (!v.success) return new Response(JSON.stringify({ ok: false, error: "spam_check" }), { status: 400, headers });

  const kind = KINDS[clip(b.kind, 40)] ? clip(b.kind, 40) : "other";
  const row = {
    kind,
    name: clip(b.name, 200) || null,
    email: clip(b.email, 320) || null,
    subject: clip(b.subject, 300) || null,
    message: clip(b.message, 10000),
    page: clip(b.page, 500) || null,
    trial_id: clip(b.trial_id, 100) || null,
  };
  if (!row.message) return new Response(JSON.stringify({ ok: false, error: "empty" }), { status: 400, headers });
  if (row.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.email)) {
    return new Response(JSON.stringify({ ok: false, error: "email" }), { status: 400, headers });
  }

  const db = createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), { db: { schema: "bank" } });
  const { data, error } = await db.from("inbox").insert(row).select("id").single();
  if (error) {
    console.error(error);
    return new Response(JSON.stringify({ ok: false, error: "store" }), { status: 500, headers });
  }

  const lines = [
    `<p><b>${KINDS[kind]}</b> · message ${data.id}</p>`,
    row.name ? `<p>From: ${esc(row.name)}${row.email ? ` &lt;${esc(row.email)}&gt;` : ""}</p>` : "",
    !row.name && row.email ? `<p>From: ${esc(row.email)}</p>` : "",
    row.trial_id ? `<p>Trial: ${esc(row.trial_id)}</p>` : "",
    row.page ? `<p>Page: ${esc(row.page)}</p>` : "",
    `<hr><p style="white-space:pre-wrap">${esc(row.message)}</p>`,
  ].join("");
  const subject = `[MSFrontier] ${KINDS[kind]}${row.subject ? `: ${row.subject}` : ""}${row.trial_id ? ` (${row.trial_id})` : ""}`;

  const sent = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env("RESEND_API_KEY")}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: env("ALERT_FROM") || "MSFrontier forms <onboarding@resend.dev>",
      to: [env("ALERT_EMAIL")],
      subject: subject.slice(0, 250),
      html: lines,
      ...(row.email ? { reply_to: row.email } : {}),
    }),
  });
  if (!sent.ok) console.error("resend", sent.status, await sent.text());

  // The message is stored even if the email fails, and the weekly report counts messages still marked new.
  return new Response(JSON.stringify({ ok: true }), { headers });
});
