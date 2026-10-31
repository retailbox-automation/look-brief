"use strict";
(() => {
  const form = document.getElementById("live-form");
  if (!form) return;
  const out = document.getElementById("live-out");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    out.textContent = "Checking your photos (no units are spent on this step)…";
    const r = await fetch("/api/live/sessions", { method: "POST", body: new FormData(form) });
    const body = await r.json().catch(() => ({}));
    if (r.ok) { location.href = body.url; return; }
    if (body.error === "photo_check") {
      out.innerHTML = Object.entries(body.checks).map(([role, c]) => c.issues.length
        ? `<p><strong>${role === "bride" ? "Your selfie" : "Inspiration photo"}:</strong> ${c.issues.map((i) => `${esc(i.title)} — ${esc(i.fix)}`).join("; ")}</p>` : "").join("");
      return;
    }
    out.textContent = body.reason || body.detail || "Something went wrong.";
  });
})();
