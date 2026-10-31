"use strict";
(() => {
  const app = document.getElementById("app");
  const sid = app.dataset.sid;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
  let state = null;
  let busy = false;
  let selZone = null;     // zone open in the sheet
  let heroView = "makeup"; // "makeup" | "hair" | "even"
  let heroInit = false; // hair-first looks open on "Even out redness": that is her look, and edits show there
  let zonesShown = true; // zone outlines show once; the first zone or edit tap hides them so the face change is visible

  // Where the zone labels sit around each outline (px from the anchor point).
  const PIN = {
    eyes: { side: "left", dx: 34, dy: -26 },
    cheeks: { side: "left", dx: 30, dy: 0 },
    lips: { side: "right", dx: 32, dy: 6 },
  };

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let body = null;
    try { body = await r.json(); } catch (e) { body = { error: "bad_response" }; }
    return { ok: r.ok, status: r.status, body };
  }

  function stepCaption(meta, what) {
    if (!meta) return "";
    const src = meta.mode === "replay" ? "Recorded real YouCam API result" : "Live YouCam API result";
    const when = meta.recorded_at ? ` · ${meta.recorded_at}` : "";
    return `${what} — ${src} · task ${taskFragment(meta.task_id)} · ${meta.seconds}s${when}`;
  }
  // YouCam ids of one session share a long prefix and a 22-char suffix: show a part that differs between tasks
  function taskFragment(id) {
    const t = String(id);
    return t.length >= 40 ? `${t.slice(0, 4)}…${t.slice(-30, -22)}` : `${t.slice(0, 10)}…`;
  }
  function setCaption(el, meta, what, fallback) {
    const known = !!(meta && meta.task_id);
    el.textContent = known || fallback === undefined ? stepCaption(meta, what) : fallback;
    el.title = known ? `YouCam task ${meta.task_id}` : "";
  }

  // ---------- photo: outlines + pins ----------
  const f4 = (n) => Math.round(n * 10000) / 10000;
  function centroid(poly) {
    let x = 0, y = 0;
    for (const [px, py] of poly) { x += px; y += py; }
    return [x / poly.length, y / poly.length];
  }
  // [keep at most N landmark points, corner-cutting passes] per zone; lips keep their pointed corners
  const SMOOTH = { eyes: [12, 4], cheeks: [99, 4], lips: [99, 2] };
  function smoothPath(poly, cfg) { // Chaikin corner cutting on the real landmark outline
    if (poly.length < 3) return "";
    const [keep, passes] = cfg;
    const stride = Math.max(1, Math.floor(poly.length / keep));
    let pts = poly.filter((_, i) => i % stride === 0);
    for (let k = 0; k < passes; k++) {
      const out = [];
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i], b = pts[(i + 1) % pts.length];
        out.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]], [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
      }
      pts = out;
    }
    return "M" + pts.map((q) => `${f4(q[0])},${f4(q[1])}`).join("L") + "Z";
  }
  function anchorFor(zone, polys) {
    const withC = polys.filter((p) => p && p.length >= 3).map((p) => ({ p, c: centroid(p) }));
    if (!withC.length) return null;
    withC.sort((a, b) => a.c[0] - b.c[0]); // the zone on the left of the photo
    const { p, c } = withC[0];
    if (zone === "lips") {
      const maxX = Math.max(...p.map((q) => q[0]));
      return [c[0] + 0.55 * (maxX - c[0]), c[1]];
    }
    return c;
  }

  function renderPhoto() {
    const outlines = state.outlines || {};
    const zones = (state.recipe && state.recipe.zones) || {};
    const map = state.map.zones || {};
    let paths = "", pins = "";
    Object.keys(zones).forEach((z) => {
      const polys = outlines[z] || [];
      polys.forEach((poly) => {
        const d = smoothPath(poly || [], SMOOTH[z] || [99, 2]);
        if (d) paths += `<path class="zone-outline" data-zone="${esc(z)}" d="${d}"/>`;
      });
      const a = anchorFor(z, polys);
      const cfg = PIN[z];
      if (!a || !cfg) return;
      const lx = cfg.side === "left" ? -cfg.dx : cfg.dx;
      const len = Math.hypot(lx, cfg.dy);
      const ang = Math.atan2(cfg.dy, lx) * 180 / Math.PI;
      const pos = cfg.side === "left" ? `right:${cfg.dx}px` : `left:${cfg.dx}px`;
      pins += `<button type="button" class="pin" tabindex="-1" data-zone="${esc(z)}" style="left:${(a[0] * 100).toFixed(2)}%;top:${(a[1] * 100).toFixed(2)}%">`
        + `<span class="pin-line" style="width:${len.toFixed(1)}px;transform:rotate(${ang.toFixed(1)}deg)"></span>`
        + `<span class="pin-dot"></span>`
        + `<span class="pin-label" style="${pos};top:${cfg.dy}px">${esc((map[z] || {}).label || z)}</span></button>`;
    });
    $("outlines").innerHTML = paths;
    $("pins").innerHTML = pins;
    $("outlines").querySelectorAll(".zone-outline").forEach((el) => el.addEventListener("click", () => selectZone(el.dataset.zone, true)));
    $("pins").querySelectorAll(".pin").forEach((el) => el.addEventListener("click", () => selectZone(el.dataset.zone, true)));
    showZones(zonesShown);
  }

  function showZones(on) {
    zonesShown = on;
    $("hero-img").classList.toggle("zones-off", !on);
    const b = $("zones-btn");
    b.textContent = on ? "Hide zones" : "Show zones";
    b.setAttribute("aria-pressed", String(on));
  }

  function renderHero() {
    const im = state.images || {};
    const edited = (state.edits || []).length > 0;
    const st = state.steps || {};
    const hairFirst = state.order === "hair_first";
    let src = im.look, alt = hairFirst ? "You with the inspiration hair and makeup (YouCam Hair Transfer, then Makeup Transfer)"
      : "You wearing the inspiration makeup (YouCam Makeup Transfer)";
    let cap = [st.mu_transfer, hairFirst ? "Hair Transfer + Makeup Transfer" : "Makeup Transfer"];
    const renderStep = st["render:" + (state.edits || []).map((e) => e.join(":")).join("+")];
    if (heroView === "hair" && im.hair) {
      src = im.hair; alt = "You with the inspiration makeup and hair (YouCam Hair Transfer)";
      cap = [st.hair_transfer, edited ? "Hair Transfer (your look before your changes; tap Makeup to see them)" : "Hair Transfer"];
    }
    else if (heroView === "even" && im.even && edited && im.render) {
      src = im.render; alt = "Your adjusted look: your edits re-rendered with YouCam Makeup VTO, with foundation in her shade";
      cap = [renderStep, "Your edits, re-rendered by Makeup VTO with the same foundation in her shade"];
    }
    else if (heroView === "even" && im.even) { src = im.even; alt = "Your look with foundation in her shade over the transfer (YouCam Makeup VTO)"; cap = [st.even_out, "Even out redness: foundation in her shade over the transfer"]; }
    else if (edited && im.render && !hairFirst) {
      src = im.render; alt = "Your adjusted look, re-rendered with YouCam Makeup VTO";
      cap = [renderStep, "Makeup VTO re-render"];
    }
    setCaption($("hero-cap"), ...cap);
    const hero = $("img-hero");
    if (src && hero.getAttribute("src") !== src) hero.src = src;
    hero.alt = alt;
    $("strip-inspo").src = im.inspiration; $("strip-you").src = im.bride;
    const tg = $("hero-toggle"), [b1, b2] = tg.querySelectorAll("button");
    if (hairFirst) {
      b1.dataset.view = "makeup"; b1.textContent = "Transfer";
      b2.dataset.view = "even"; b2.textContent = "Even out redness";
      tg.hidden = !im.even;
    } else {
      b1.dataset.view = "makeup"; b1.textContent = "Makeup";
      b2.dataset.view = "hair"; b2.textContent = "Makeup + hair";
      tg.hidden = !im.hair;
    }
    const chk = state.checks && state.checks.bride; // local photo check (older servers don't send it)
    if (chk && chk.ok) {
      const codes = (chk.issues || []).map((i) => i.code);
      const parts = [];
      if (!codes.includes("large_angle")) parts.push("front-facing");
      if (!codes.includes("eyes_closed")) parts.push("eyes open");
      $("hero-check").textContent = `Photo check ✓ ${parts.join(" · ")}`.trim();
      $("hero-check").hidden = false;
    } else {
      $("hero-check").hidden = true;
    }
    $("hero-toggle").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === heroView)));
  }

  // ---------- sheet: zone tabs + zone panels ----------
  function selectZone(z, byUser) {
    if (!z) return;
    if (byUser && zonesShown) showZones(false); // she started choosing: let the face show
    selZone = z;
    $("zone-tabs").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.zone === z)));
    $("zones").querySelectorAll(".zone").forEach((p) => { p.hidden = p.dataset.zone !== z; });
    document.querySelectorAll("#outlines .zone-outline, #pins .pin").forEach((el) => el.classList.toggle("on", el.dataset.zone === z));
  }

  function renderZones() {
    const opts = state.edit_options || [];
    const zones = (state.recipe && state.recipe.zones) || {};
    const map = state.map.zones;
    const keys = Object.keys(zones);
    if (!keys.includes(selZone)) selZone = keys[0] || null;
    $("zone-tabs").innerHTML = keys.map((z) =>
      `<button type="button" class="tab" data-zone="${esc(z)}" aria-pressed="false">${esc((map[z] || {}).label || z)}</button>`).join("");
    const html = keys.map((z) => {
      const r = zones[z];
      const m = map[z] || {};
      const g = ((state.gaps && state.gaps.zones) || {})[z] || {};
      const face = g.color_render || m.color_after || r.color; // measured on the current render
      const light = opts.some((o) => o.zone === z && o.reason === "light");
      const buttons = opts.filter((o) => o.zone === z).map((o) => {
        const why = o.reason === "light" ? ` aria-describedby="light-${esc(z)}"` : "";
        return `<button type="button" class="chip" data-zone="${z}" data-op="${o.op}" ${o.available ? "" : "disabled"}${why} aria-label="${esc(m.label)}: ${esc(o.label)}">${esc(cap(o.op))}</button>`;
      }).join("");
      const lightNote = light ? `<p class="chip-note" id="light-${esc(z)}" data-testid="light-${esc(z)}">Softer: already close to your bare skin.</p>` : "";
      return `<article class="zone" data-zone="${esc(z)}" data-testid="zone-${z}" aria-labelledby="zone-h-${esc(z)}">
        <div class="zone-head">
          <span class="zone-swatch" style="background:${esc(face)}" aria-hidden="true"></span>
          <div>
            <h3 id="zone-h-${esc(z)}">${esc(m.label || z)}</h3>
            <p class="zone-measure">Coverage ${Math.round((m.coverage || 0) * 100)}% · Strength ΔE ${Math.round(Number(m.strength_de) || 0)}</p>
            <p class="zone-product">On face ${esc(String(face).toUpperCase())} · product <code>${esc(String(r.color).toUpperCase())}</code> · intensity ${esc(r.intensity)}</p>
          </div>
        </div>
        <div class="chips" role="group" aria-label="Adjust ${esc(m.label)}">${buttons}</div>
        ${lightNote}
      </article>`;
    }).join("");
    $("zones").innerHTML = html;
    const extra = map.nose && map.nose.changed_px > 200 && map.nose.coverage >= 0.05 // 1% reads like a false warning
      ? `Also changed: nose &amp; contour (${Math.round(map.nose.coverage * 100)}% of that area) — not re-rendered, flag it with your artist.` : "";
    $("zone-extra").innerHTML = extra;
    $("zone-tabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => selectZone(b.dataset.zone, true)));
    $("zones").querySelectorAll("button.chip").forEach((b) => b.addEventListener("click", () => doEdit({ zone: b.dataset.zone, op: b.dataset.op })));
    const ed = state.edits || [];
    $("undo").disabled = ed.length === 0;
    $("reset").disabled = ed.length === 0;
    $("edit-tools").hidden = ed.length === 0;
    $("reset").textContent = state.order === "hair_first" && (state.images || {}).even ? "Back to my look" : "Back to the transferred look";
    selectZone(selZone);
  }

  function renderGaps() {
    const gz = (state.gaps && state.gaps.zones) || {};
    const rows = Object.values(gz).map((g) =>
      `<tr><th scope="row">${esc(g.label)}</th><td>${g.color_gap_de2000.toFixed(1)}</td><td>${Math.round(g.coverage_transfer * 100)}% → ${Math.round(g.coverage_render * 100)}%</td></tr>`).join("");
    document.querySelector("#gaps tbody").innerHTML = rows;
    const evened = state.gaps && state.gaps.reference === "even";
    $("gaps-ref").textContent = evened ? "Hair-first look: compared with the evened look (transfer + foundation in her shade), because every re-render carries the same foundation." : "";
    $("skin-note").textContent = evened
      ? `Skin control (forehead): the transfer changes it by ΔE76 ${state.map.skin_control_de}; the re-render, with foundation in her shade (coverage 30, no smoothing), by ${state.gaps.skin_control_render_de76}.`
      : `Skin control (forehead, no makeup): transfer changes it by ΔE76 ${state.map.skin_control_de}, recipe render by ${state.gaps.skin_control_render_de76} — your skin is kept, not beautified.`;
    const parts = Object.values(gz).map((g) => `${esc(g.label)} ${g.color_gap_de2000.toFixed(1)}`);
    $("accuracy").innerHTML = parts.length ? `Re-render accuracy (ΔE2000, lower is closer): ${parts.join(" · ")}` : "";
  }

  function render() {
    const im = state.images || {};
    const evenAfter = state.order === "hair_first" && im.even; // her look is the evened one
    $("img-before").src = im.bride; $("img-after").src = evenAfter ? im.even : im.look;
    $("img-inspo").src = im.inspiration; $("img-layer").src = im.layer; $("img-render").src = im.render;
    const hairImg = im.hair || (state.order === "hair_first" && im.base) || ""; // hair first: the Hair Transfer on her selfie is "base"
    if (hairImg) { $("img-hair").src = hairImg; } else { $("img-hair").closest("figure").hidden = true; }
    if (!im.hair && hairImg) $("img-hair").alt = "Your selfie with the inspiration hair (YouCam Hair Transfer)";
    const st = state.steps || {};
    if (evenAfter) setCaption($("cap-after"), st.even_out, "Hair Transfer + Makeup Transfer, then even out redness (foundation in her shade, Makeup VTO)");
    else setCaption($("cap-after"), st.mu_transfer, "Makeup Transfer");
    setCaption($("cap-hair"), st.hair_transfer, im.hair ? "Hair Transfer" : "Hair (YouCam Hair Transfer on your selfie)", "Hair preview unavailable");
    const key = (state.edits || []).length ? "render:" + state.edits.map((e) => e.join(":")).join("+") : "render:base";
    setCaption($("cap-render"), st[key], "Makeup VTO re-render");
    if (!heroInit) { heroInit = true; if (state.order === "hair_first" && im.even) heroView = "even"; }
    renderHero(); renderPhoto(); renderZones(); renderGaps();
    $("tech").textContent = JSON.stringify({ steps: state.steps, recipe: state.recipe, vto_effects: state.vto_effects, map: state.map }, null, 2);
    $("look").hidden = false;
  }

  async function poll() {
    const { ok, body } = await api(`/api/sessions/${sid}`);
    if (!ok) { $("status").textContent = "Session not found."; return; }
    state = body;
    if (body.status === "ready") {
      $("status").textContent = body.mode === "replay" ? "Replaying recorded real YouCam API results." : `Done. YouCam units used: ${body.units_spent}.`;
      $("status").classList.add("sr-only");
      render();
      return;
    }
    if (body.status === "error") {
      const h = body.error_hint || { title: "Something went wrong", fix: "" };
      $("status").innerHTML = `<strong>${esc(h.title)}.</strong> ${esc(h.fix)} <a href="/">Back</a>`;
      return;
    }
    $("status").textContent = body.mode === "replay" ? "Loading the recorded results…" : "Calling YouCam: hair transfer → makeup transfer → re-render → even out redness (about 30 seconds)…";
    setTimeout(poll, 1200);
  }

  async function doEdit(payload) {
    if (busy) return;
    const a = document.activeElement;
    const refocus = a && a.dataset ? (a.dataset.op ? `button.chip[data-zone="${a.dataset.zone}"][data-op="${a.dataset.op}"]` : (a.id ? `#${a.id}` : "")) : "";
    busy = true; $("edit-msg").textContent = "Re-rendering with YouCam Makeup VTO…";
    const { ok, body } = await api(`/api/sessions/${sid}/edits`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    busy = false;
    if (!ok) { $("edit-msg").textContent = body.reason || body.detail || "That change didn't work."; return; }
    const before = (state.edits || []).length;
    state = body;
    // the photo that carries the change: over her even tone (hair first), else the Makeup VTO view, never the hair preview
    heroView = state.order === "hair_first" && (state.images || {}).even ? "even" : "makeup";
    if (payload.zone && zonesShown) showZones(false);
    const opts = state.edit_options || [];
    const after = (state.edits || []).length;
    const replaced = state.mode === "replay" && payload.zone && before > 0 && after === before;
    const heldOne = state.mode === "replay" && after > 0 && opts.length > 0 && !opts.some((o) => o.available);
    $("edit-msg").textContent = replaced ? "Updated. Samples hold one recorded change at a time — this replaced your previous change."
      : heldOne ? "Updated. Samples hold one recorded change at a time — undo it to try another."
      : payload.action === "undo" ? "Undone."
      : payload.action === "reset" ? (state.order === "hair_first" && (state.images || {}).even ? "Back to your look." : "Back to the transferred look.")
      : "Updated.";
    render();
    const hr = $("img-hero").getBoundingClientRect(); // after a zone change, show the photo if less than half is on screen
    const scrolled = !!payload.zone && Math.min(hr.bottom, innerHeight) - Math.max(hr.top, 0) < hr.height / 2;
    // to the top of the look, not the photo's own top edge: on iPhone Safari the photo's top sits under the status bar
    if (scrolled) window.scrollTo({ top: Math.max(0, $("look").getBoundingClientRect().top + scrollY), behavior: "smooth" });
    const usable = (el) => el && !el.disabled && !el.closest("[hidden]");
    const back = refocus && document.querySelector(refocus);
    if (refocus && usable(back)) back.focus({ preventScroll: scrolled });
    else if (refocus && usable($("undo"))) $("undo").focus({ preventScroll: scrolled }); // the button pressed is gone or disabled
  }

  $("ba").addEventListener("input", (e) => { $("img-after").style.clipPath = `inset(0 0 0 ${e.target.value}%)`; });
  $("undo").addEventListener("click", () => doEdit({ action: "undo" }));
  $("reset").addEventListener("click", () => doEdit({ action: "reset" }));
  $("hero-toggle").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { heroView = b.dataset.view; if (state) renderHero(); }));
  $("zones-btn").addEventListener("click", () => showZones(!zonesShown));
  $("make-brief").addEventListener("click", async () => {
    const { ok, body } = await api(`/api/sessions/${sid}/brief`, { method: "POST" });
    if (!ok) { $("edit-msg").textContent = body.detail || "Couldn't create the brief link."; return; }
    const a = $("artist-link"), b = $("bride-link");
    if (a.getAttribute("href") !== body.artist_url) document.querySelector('[data-copy="artist-link"]').textContent = "Copy"; // new links: nothing copied yet
    a.href = body.artist_url; a.textContent = location.origin + body.artist_url;
    b.href = body.bride_url; b.textContent = location.origin + body.bride_url;
    $("brief-links").hidden = false;
  });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-copy]");
    if (t) { navigator.clipboard && navigator.clipboard.writeText($(t.dataset.copy).textContent); t.textContent = "Copied"; }
  });
  const del = $("delete");
  if (del) del.addEventListener("click", async () => { await api(`/api/sessions/${sid}/delete`, { method: "POST" }); location.href = "/"; });
  $("img-after").style.clipPath = "inset(0 0 0 50%)";
  poll();
})();
