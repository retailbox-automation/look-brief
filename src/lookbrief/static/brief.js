"use strict";
(() => {
  const root = document.getElementById("brief");
  const { bid, token, role } = root.dataset;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const LABELS = { do: "I'll do this", swap: "I'll swap the product", discuss: "Let's discuss" };
  let view = null;

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let body = null;
    try { body = await r.json(); } catch (e) { body = {}; }
    return { ok: r.ok, body };
  }

  function zoneInfo(z) { return view.snapshot.zones.find((x) => x.zone === z) || { zone: z, label: "Hair" }; }

  function render() {
    const im = view.images;
    $("b-before").src = im.bride || ""; $("b-after").src = im.look || ""; $("b-inspo").src = im.inspiration || "";
    if (im.hair) $("b-hair").src = im.hair; else $("b-hair").closest("figure").hidden = true;
    const signed = !!view.attestation;
    const rows = view.snapshot.review_zones.map((z) => {
      const zi = zoneInfo(z), r = view.reviews[z] || {};
      const detail = zi.product_hex ? `<span class="swatch" style="background:${esc(zi.product_hex)}" aria-hidden="true"></span> ${esc(zi.product_hex)} · intensity ${esc(zi.intensity)} · coverage ${Math.round((zi.coverage || 0) * 100)}%` : "Hair from the inspiration photo (see preview)";
      if (role !== "artist" || signed) {
        return `<fieldset class="review" data-testid="review-${z}"><legend>${esc(zi.label)}</legend><p>${detail}</p><p><strong>Artist:</strong> ${r.status ? esc(LABELS[r.status]) : "not reviewed yet"}${r.note ? ` — “${esc(r.note)}”` : ""}</p></fieldset>`;
      }
      const radios = Object.entries(LABELS).map(([k, l]) => `<label class="seg"><input type="radio" name="st-${z}" value="${k}" ${r.status === k ? "checked" : ""}> ${esc(l)}</label>`).join("");
      return `<fieldset class="review" data-testid="review-${z}"><legend>${esc(zi.label)}</legend><p>${detail}</p>
        <div class="segs">${radios}</div>
        <label>Note for the bride <input type="text" maxlength="300" name="note-${z}" value="${esc(r.note || "")}" placeholder="e.g. I'll use a cooler pink"></label></fieldset>`;
    }).join("");
    $("reviews").innerHTML = rows;
    $("reviews").querySelectorAll("input[type=radio]").forEach((el) => el.addEventListener("change", () => save(el.name.slice(3))));
    $("reviews").querySelectorAll("input[type=text]").forEach((el) => el.addEventListener("change", () => save(el.name.slice(5))));
    $("shades").innerHTML = view.snapshot.zones.map((z) => `<li><span class="swatch" style="background:${esc(z.product_hex)}" aria-hidden="true"></span> ${esc(z.label)} <code>${esc(z.product_hex)}</code> · intensity ${esc(z.intensity)}</li>`).join("");
    const a = view.agreed;
    const me = a[role];
    const other = role === "artist" ? "bride" : "artist";
    let help = "";
    if (signed) help = "Both agreed — this version is signed by the server.";
    else if (!view.can_agree) help = view.open_discussions.length ? "Resolve “Let's discuss” zones with the bride first." : "Choose an answer for every zone first.";
    else help = me ? `You agreed at ${me}. Waiting for the ${other}.` : (a[other] ? `The ${other} agreed ✓ · waiting for you.` : "");
    $("agree-help").textContent = help;
    $("agree").disabled = signed || !view.can_agree || !!me;
    $("b-status").textContent = `Version ${view.version}${view.snapshot.mode === "replay" ? " · sample (recorded real YouCam API results)" : ""}`;
    if (signed || a.bride || a.artist) { $("card-a").href = `/card/${bid}?t=${token}`; $("card-link").hidden = false; }
  }

  async function load() { const { ok, body } = await api(`/api/briefs/${bid}?t=${encodeURIComponent(token)}`); if (ok) { view = body; render(); } }

  async function save(zone) {
    const st = document.querySelector(`input[name="st-${zone}"]:checked`);
    if (!st) return;
    const note = (document.querySelector(`input[name="note-${zone}"]`) || {}).value || "";
    const { ok, body } = await api(`/api/briefs/${bid}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token, zone, status: st.value, note }) });
    if (ok) { view = body; render(); }
  }

  $("agree").addEventListener("click", async () => {
    const { ok, body } = await api(`/api/briefs/${bid}/agree`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token }) });
    if (ok) { view = body; render(); } else { $("agree-help").textContent = body.detail || "Couldn't agree yet."; }
  });
  const rev = $("revise");
  if (rev) rev.addEventListener("click", async () => {
    const { ok, body } = await api(`/api/briefs/${bid}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token }) });
    if (ok) { view = body; render(); }
  });
  load();
  setInterval(load, 8000);
})();
