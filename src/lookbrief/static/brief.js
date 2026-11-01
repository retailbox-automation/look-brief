"use strict";
(() => {
  const root = document.getElementById("brief");
  const { bid, token, role } = root.dataset;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const LABELS = { do: "I'll do this", swap: "I'll swap the product", discuss: "Let's discuss" };
  let view = null;
  let noteUntil = 0; // "already up to date" stays next to the state line for a few seconds, across poll re-renders
  const UP_TO_DATE = "Your brief is already up to date — no new edits.";

  async function api(path, opts) {
    let r;
    try { r = await fetch(path, opts); }
    catch (e) { return { ok: false, status: 0, body: { error: "network", reason: "We could not reach the server. Check your connection and try again." } }; }
    let body = null;
    try { body = await r.json(); } catch (e) { body = {}; }
    return { ok: r.ok, body };
  }

  const dotFill = (colors) => colors.length > 1 ? `linear-gradient(135deg, ${colors.map((c, i) => `${esc(c)} ${Math.round(100 * i / colors.length)}% ${Math.round(100 * (i + 1) / colors.length)}%`).join(", ")})` : esc(colors[0]);
  const finishText = (zi) => zi.texture ? `${esc(zi.texture)} · ` : "";

  function zoneInfo(z) { return view.snapshot.zones.find((x) => x.zone === z) || { zone: z, label: "Hair" }; }

  function render() {
    const im = view.images;
    $("b-before").src = im[view.snapshot.before] || ""; $("b-inspo").src = im.inspiration || "";
    const agreedText = `Agreed look: ${role === "bride" ? "your" : "the bride's"} recipe, rendered with YouCam Makeup VTO`;
    $("b-after").src = im[view.snapshot.target] || "";
    $("b-after").alt = agreedText;
    $("b-after-cap").textContent = agreedText;
    const hairFirst = view.snapshot.order === "hair_first";
    const hairImg = im.hair || (hairFirst && im.base) || ""; // hair first: the Hair Transfer on her selfie is "base"
    if (hairImg) $("b-hair").src = hairImg; else $("b-hair").closest("figure").hidden = true;
    if (!im.hair && hairImg) {
      $("b-hair").alt = "Bride's selfie with the inspiration hair (YouCam Hair Transfer)";
      $("b-hair-cap").textContent = "Hair (YouCam Hair Transfer on her selfie)";
      $("more-photos-h").textContent = "Inspiration photo and hair preview";
    }
    const signed = !!view.attestation;
    const rows = view.snapshot.review_zones.map((z) => {
      const zi = zoneInfo(z), r = view.reviews[z] || {};
      const dots = (zi.palette || []).map((c) => `<span class="swatch" style="background:${esc(c)}" aria-hidden="true"></span>`).join(" ");
      const codes = esc((zi.palette || []).join(" / ").toUpperCase());
      const detail = z === "skin"
        ? `${dots} ${esc(zi.shade_name)} · ${codes}`
        : zi.product_hex ? `${dots} ${esc(zi.shade_name)} · ${codes} · ${finishText(zi)}intensity ${esc(zi.intensity)}`
        : hairFirst ? "Hair as in the agreed look photo above (YouCam Hair Transfer)" : "Hair as in the makeup + hair preview below";
      if (role !== "artist" || signed) {
        return `<fieldset class="review readonly" data-testid="review-${z}"><legend>${esc(zi.label)}</legend><p class="rv-detail">${detail}</p><p class="rv-answer"><strong>Artist:</strong> ${r.status ? esc(LABELS[r.status]) : "not reviewed yet"}${r.note ? ` — “${esc(r.note)}”` : ""}</p></fieldset>`;
      }
      const radios = Object.entries(LABELS).map(([k, l]) => `<label class="seg"><input type="radio" name="st-${z}" value="${k}" ${r.status === k ? "checked" : ""}><span>${esc(l)}</span></label>`).join("");
      return `<fieldset class="review" data-testid="review-${z}"><legend>${esc(zi.label)}</legend><p class="rv-detail">${detail}</p>
        <div class="segs">${radios}</div>
        <label class="rv-note"><span class="sr-only">Note for the bride about ${esc(zi.label)}</span><input type="text" maxlength="300" name="note-${z}" value="${esc(z in dirty ? dirty[z] : (r.note || ""))}" placeholder="Note for the bride"></label></fieldset>`;
    }).join("");
    $("reviews").innerHTML = rows;
    $("reviews").querySelectorAll("input[type=radio]").forEach((el) => el.addEventListener("change", () => save(el.name.slice(3))));
    $("reviews").querySelectorAll("input[type=text]").forEach((el) => {
      el.addEventListener("input", () => { dirty[el.name.slice(5)] = el.value; });
      el.addEventListener("change", () => save(el.name.slice(5)));
    });
    $("shades").innerHTML = view.snapshot.zones.map((z) => `<li><span class="shade-dot" style="background:${dotFill(z.palette || [])}" aria-hidden="true"></span><span class="shade-name">${esc(z.label)}</span><span class="shade-meta">${esc(z.shade_name)}</span><code class="shade-hex">${esc((z.palette || []).join(" ").toUpperCase())}</code></li>`).join("");
    const a = view.agreed;
    const me = a[role];
    const other = role === "artist" ? "bride" : "artist";
    let help = "";
    if (signed) help = "Both agreed — this version is signed by the server.";
    else if (!view.can_agree && role === "bride") help = view.open_discussions.length ? "Your artist wants to discuss a zone — talk it through, then they update the answer." : "Waiting for your makeup artist to answer every zone.";
    else if (!view.can_agree) help = view.open_discussions.length ? "Resolve “Let's discuss” zones with the bride first." : "Choose an answer for every zone first.";
    else help = me ? `You agreed at ${me}. Waiting for the ${other}.` : (a[other] ? `The ${other} agreed ✓ · waiting for you.` : "");
    $("agree-help").textContent = Date.now() < noteUntil ? `${help} ${UP_TO_DATE}`.trim() : help;
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
    if (ok) { view = body; render(); } else { $("agree-help").textContent = body.reason || body.detail || "Couldn't agree yet."; }
  });
  const rev = $("revise");
  if (rev) rev.addEventListener("click", async () => {
    const { ok, body } = await api(`/api/briefs/${bid}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: token }) });
    if (!ok) { $("agree-help").textContent = body.reason || body.detail || "Couldn't update the brief."; return; }
    noteUntil = body.unchanged ? Date.now() + 6000 : 0;
    view = body; render();
  });
  load();
  setInterval(load, 8000);
})();
