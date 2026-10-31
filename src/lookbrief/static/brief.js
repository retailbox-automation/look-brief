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

  // the photo the bride agrees to (snapshot.target): what it is, for the alt text and the visible caption
  function targetText(snap) {
    if (snap.target === "even") return "foundation in her shade over the transfer (YouCam Makeup VTO)";
    if (snap.target === "render") return `${role === "bride" ? "your" : "the bride's"} adjusted look, re-rendered with YouCam Makeup VTO`;
    return snap.order === "hair_first" ? "YouCam Hair Transfer + Makeup Transfer" : "YouCam Makeup Transfer";
  }

  function zoneInfo(z) { return view.snapshot.zones.find((x) => x.zone === z) || { zone: z, label: "Hair" }; }

  function render() {
    const im = view.images;
    $("b-before").src = im.bride || ""; $("b-inspo").src = im.inspiration || "";
    $("b-after").src = im[view.snapshot.target] || im.look || "";
    $("b-after").alt = `Agreed look: ${targetText(view.snapshot)}`;
    $("b-after-cap").textContent = `Agreed look: ${targetText(view.snapshot)}`;
    if (im.hair) $("b-hair").src = im.hair; else $("b-hair").closest("figure").hidden = true;
    const signed = !!view.attestation;
    const rows = view.snapshot.review_zones.map((z) => {
      const zi = zoneInfo(z), r = view.reviews[z] || {};
      const detail = z === "skin"
        ? `<span class="swatch" style="background:${esc(zi.product_hex)}" aria-hidden="true"></span> Foundation in her own shade ${esc(zi.product_hex)} · intensity ${esc(zi.intensity)} — evens redness, applied over the transfer`
        : zi.product_hex ? `<span class="swatch" style="background:${esc(zi.product_hex)}" aria-hidden="true"></span> ${esc(zi.product_hex)} · intensity ${esc(zi.intensity)} · coverage ${Math.round((zi.coverage || 0) * 100)}%` : "Hair as in the makeup + hair preview below";
      if (role !== "artist" || signed) {
        return `<fieldset class="review readonly" data-testid="review-${z}"><legend>${esc(zi.label)}</legend><p class="rv-detail">${detail}</p><p class="rv-answer"><strong>Artist:</strong> ${r.status ? esc(LABELS[r.status]) : "not reviewed yet"}${r.note ? ` — “${esc(r.note)}”` : ""}</p></fieldset>`;
      }
      const radios = Object.entries(LABELS).map(([k, l]) => `<label class="seg"><input type="radio" name="st-${z}" value="${k}" ${r.status === k ? "checked" : ""}><span>${esc(l)}</span></label>`).join("");
      const hint = zi.product_hex ? "" : `<p class="rv-detail">${detail}</p>`;
      return `<fieldset class="review" data-testid="review-${z}"><legend>${esc(zi.label)}</legend>
        <div class="segs">${radios}</div>
        <label class="rv-note"><span class="sr-only">Note for the bride about ${esc(zi.label)}</span><input type="text" maxlength="300" name="note-${z}" value="${esc(z in dirty ? dirty[z] : (r.note || ""))}" placeholder="Note for the bride"></label>${hint}</fieldset>`;
    }).join("");
    $("reviews").innerHTML = rows;
    $("reviews").querySelectorAll("input[type=radio]").forEach((el) => el.addEventListener("change", () => save(el.name.slice(3))));
    $("reviews").querySelectorAll("input[type=text]").forEach((el) => {
      el.addEventListener("input", () => { dirty[el.name.slice(5)] = el.value; });
      el.addEventListener("change", () => save(el.name.slice(5)));
    });
    $("shades").innerHTML = view.snapshot.zones.map((z) => `<li><span class="shade-dot" style="background:${esc(z.product_hex)}" aria-hidden="true"></span><span class="shade-name">${esc(z.label)}</span><code class="shade-hex">${esc(String(z.product_hex || "").toUpperCase())}</code><span class="shade-meta">${z.zone === "skin" ? `foundation in her shade · intensity ${esc(z.intensity)}` : `intensity ${esc(z.intensity)} · coverage ${Math.round((z.coverage || 0) * 100)}%`}</span></li>`).join("");
    const a = view.agreed;
    const me = a[role];
    const other = role === "artist" ? "bride" : "artist";
    let help = "";
    if (signed) help = "Both agreed — this version is signed by the server.";
    else if (!view.can_agree && role === "bride") help = view.open_discussions.length ? "Your artist wants to discuss a zone — talk it through, then they update the answer." : "Waiting for your makeup artist to answer every zone.";
    else if (!view.can_agree) help = view.open_discussions.length ? "Resolve “Let's discuss” zones with the bride first." : "Choose an answer for every zone first.";
    else help = me ? `You agreed at ${me}. Waiting for the ${other}.` : (a[other] ? `The ${other} agreed ✓ · waiting for you.` : "");
    $("agree-help").textContent = help;
    $("agree").disabled = signed || !view.can_agree || !!me;
    $("b-status").textContent = `Version ${view.version}${view.snapshot.mode === "replay" ? " · sample (recorded real YouCam API results)" : ""}`;
    if (signed || a.bride || a.artist) { $("card-a").href = `/card/${bid}?t=${token}`; $("card-link").hidden = false; }
  }

  function keepFocus(fn) { // re-rendering the form must not drop keyboard focus
    const a = document.activeElement;
    const sel = a && a.name ? (a.type === "radio" ? `input[name="${a.name}"][value="${a.value}"]` : `input[name="${a.name}"]`) : (a && a.id ? `#${a.id}` : "");
    fn();
    const b = sel && document.querySelector(sel);
    if (b && b !== document.activeElement && !b.disabled) b.focus();
  }

  async function load() {
    const { ok, body } = await api(`/api/briefs/${bid}?t=${encodeURIComponent(token)}`);
    if (!ok) return;
    const a = document.activeElement;
    if (view && a && a.type === "text" && root.contains(a)) return; // don't wipe a note being typed
    view = body; keepFocus(render);
  }

  let pending = Promise.resolve();  // reviews are saved one after another, never racing an agreement
  const dirty = {};  // notes typed but not yet confirmed by the server survive re-renders

  async function saveNow(zone) {
    const st = document.querySelector(`input[name="st-${zone}"]:checked`);
    if (!st) return;
    const note = zone in dirty ? dirty[zone] : ((document.querySelector(`input[name="note-${zone}"]`) || {}).value || "");
    const { ok, body } = await api(`/api/briefs/${bid}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token, zone, status: st.value, note }) });
    if (ok) {
      if (dirty[zone] !== undefined && ((body.reviews[zone] || {}).note || "") === dirty[zone].trim()) delete dirty[zone];
      view = body; keepFocus(render);
    }
  }

  function save(zone) {
    pending = pending.then(() => saveNow(zone)).catch(() => {});
    return pending;
  }

  function flushNotes() {
    // a note typed but not yet saved (no blur yet) is saved before agreeing
    if (!view || role !== "artist") return pending;
    Object.keys(dirty).forEach((zone) => {
      const saved = (view.reviews[zone] || {}).note || "";
      if (dirty[zone].trim() !== saved) save(zone);
    });
    return pending;
  }

  $("agree").addEventListener("click", async () => {
    await flushNotes();
    const { ok, body } = await api(`/api/briefs/${bid}/agree`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token }) });
    if (ok) { view = body; render(); } else { $("agree-help").textContent = body.detail || "Couldn't agree yet."; }
  });
  const rev = $("revise");
  if (rev) rev.addEventListener("click", async () => {
    const { ok, body } = await api(`/api/briefs/${bid}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token }) });
    if (!ok) { $("agree-help").textContent = body.detail || "Couldn't update the brief."; return; }
    view = body; render();
    if (body.unchanged) $("agree-help").textContent = "Your brief is already up to date — no new edits.";
  });
  load();
  setInterval(load, 8000);
})();
