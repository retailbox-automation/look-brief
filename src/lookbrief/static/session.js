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
  let heroView = "makeup"; // "makeup" | "hair"
  let zonesShown = true; // zone outlines show once; the first zone or edit tap hides them so the face change is visible

  // Where the zone labels sit around each outline (px from the anchor point). Only zones with an outline have a pin.
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
    $("zones-btn").textContent = on ? "Hide zones" : "Show zones"; // the label says the action (no pressed state)
  }

  const renderKey = () => ((state.edits || []).length ? "render:" + state.edits.map((e) => e.join(":")).join("+") : "render:base");
  const lookCaption = () => `${(state.edits || []).length ? "Your edits, rendered" : "Your look, rendered"} by Makeup VTO${state.even_out ? " with foundation in your shade" : ""}`;

  // ---------- photo: close up on the chosen zone ----------
  // zone -> [outline it centres on, scale]. Brows, liner and lashes live around the eyes.
  const ZOOM = {
    eyes: ["eyes", 2.3], liner: ["eyes", 2.3], lashes: ["eyes", 2.3], brows: ["eyes", 2.3],
    lips: ["lips", 2.3], lip_line: ["lips", 2.3],
    cheeks: ["cheeks", 1.5], bronzer: ["cheeks", 1.5], highlight: ["cheeks", 1.5],
  };
  const FRAME_SHARE = 3.8 / 4; // the frame shows this share of the photo's height (aspect 3:3.8 over 3:4)
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function zoomTo(z) { // z null: the whole face
    const [polys, scale] = ZOOM[z] || [];
    const pts = ((state.outlines || {})[polys] || []).flat();
    const box = $("hero-img");
    const on = pts.length > 0;
    box.closest(".hero-frame").classList.toggle("zoomed", on);
    $("whole-btn").hidden = !on;
    box.style.setProperty("--zoom", on ? scale : 1);
    if (!on) { box.style.transform = ""; return; }
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    // centre the zone in the frame, in % of the photo's own box; the clamp keeps the frame fully covered
    const tx = clamp(0.5 - scale * cx, 1 - scale, 0), ty = clamp(FRAME_SHARE / 2 - scale * cy, FRAME_SHARE - scale, 0);
    box.style.transform = `translate(${(tx * 100).toFixed(2)}%, ${(ty * 100).toFixed(2)}%) scale(${scale})`;
  }

  function renderHero() {
    const im = state.images || {};
    const v = state.views || {};
    const st = state.steps || {};
    const edited = (state.edits || []).length > 0;
    let src = im[v.hero], alt = "Your look: the makeup recipe on your photo (YouCam Makeup VTO)";
    let cap = [st[renderKey()], lookCaption()];
    if (heroView === "hair" && im.hair) {
      src = im.hair; alt = "Your look with the inspiration hair (YouCam Hair Transfer)";
      cap = [st.hair_transfer, edited ? "Hair Transfer (your look before your changes; tap Makeup to see them)" : "Hair Transfer on your look"];
    }
    setCaption($("hero-cap"), ...cap);
    const hero = $("img-hero");
    if (src && hero.getAttribute("src") !== src) hero.src = src;
    hero.alt = alt;
    $("strip-inspo").src = im.inspiration; $("strip-you").src = im.bride;
    $("hero-toggle").hidden = !im.hair; // hair first: the render already wears the new hair
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

  // ---------- sheet: looks, zone tabs, zone panels ----------
  function selectZone(z, byUser) {
    if (!z) return;
    if (byUser && zonesShown) showZones(false); // she started choosing: let the face show
    if (byUser) zoomTo(z);
    selZone = z;
    const tabs = $("zone-tabs");
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.zone === z)));
    $("zones").querySelectorAll(".zone").forEach((p) => { p.hidden = p.dataset.zone !== z; });
    document.querySelectorAll("#outlines .zone-outline, #pins .pin").forEach((el) => el.classList.toggle("on", el.dataset.zone === z));
    const tab = tabs.querySelector('button[aria-pressed="true"]'); // the row scrolls sideways: keep her tab in view
    if (!tab) return;
    const r = tab.getBoundingClientRect(), box = tabs.getBoundingClientRect(), pad = 17;
    if (r.left < box.left + pad) tabs.scrollLeft -= box.left + pad - r.left;
    else if (r.right > box.right - pad) tabs.scrollLeft += r.right - box.right + pad;
  }

  const dotFill = (colors) => colors.length > 1 ? `linear-gradient(135deg, ${colors.map((c, i) => `${esc(c)} ${Math.round(100 * i / colors.length)}% ${Math.round(100 * (i + 1) / colors.length)}%`).join(", ")})` : esc(colors[0]);

  function circleHtml(o, label) {
    const dot = o.colors.length ? `<span class="dot" style="background:${dotFill(o.colors)}" aria-hidden="true"></span>` : '<span class="dot none" aria-hidden="true"></span>';
    return `<button type="button" class="circle" data-zone="${esc(o.zone)}" data-op="${esc(o.op)}" aria-pressed="${o.selected}" aria-label="${esc(label)}: ${esc(o.name)}" ${o.available || o.selected ? "" : "disabled"}>${dot}<span class="circle-name">${esc(o.name)}</span></button>`;
  }

  function chipHtml(o, label) {
    return `<button type="button" class="chip" data-zone="${esc(o.zone)}" data-op="${esc(o.op)}" ${o.available ? "" : "disabled"} aria-label="${esc(label)}: ${esc(o.label)}">${esc(cap(o.op))}</button>`;
  }

  function styleHtml(o, label) { // thin zones: the step is a style with a name, not a colour
    return `<button type="button" class="chip" data-zone="${esc(o.zone)}" data-op="${esc(o.op)}" aria-pressed="${o.selected}" aria-label="${esc(label)}: ${esc(o.name)}" ${o.available || o.selected ? "" : "disabled"}>${esc(o.name)}</button>`;
  }

  function renderLooks() {
    const opts = (state.edit_options || []).filter((o) => o.zone === "look");
    $("look-row").innerHTML = opts.map((o) => `<button type="button" class="look-btn" data-zone="look" data-op="${esc(o.op)}" aria-pressed="${o.selected}" ${o.available || o.selected ? "" : "disabled"}>${esc(o.label)}</button>`).join("");
  }

  function zonePanel(z, label, style, note) {
    const opts = (state.edit_options || []).filter((o) => o.zone === z);
    const r = state.recipe.zones[z];
    const steps = opts.filter((o) => o.op === "softer" || o.op === "bolder");
    const shades = opts.filter((o) => o.op.startsWith("shade:"));
    const notes = [...new Set(steps.filter((o) => !o.available && o.note).map((o) => o.note))];
    const finish = !style && r.texture ? ` · ${esc(cap(r.texture))}` : "";
    const choice = note ? `<p class="zone-note" data-testid="note-${esc(z)}">${esc(note)}</p>` : style
      ? `<div class="styles" role="group" aria-label="${esc(label)} styles">${shades.map((o) => styleHtml(o, label)).join("")}</div>`
      : `<div class="circles" role="group" aria-label="${esc(label)} shades">${shades.map((o) => circleHtml(o, label)).join("")}</div>`;
    return `<article class="zone" data-zone="${esc(z)}" data-testid="zone-${esc(z)}" aria-labelledby="zone-h-${esc(z)}">
      <div class="zone-head"><h3 id="zone-h-${esc(z)}">${esc(label)}</h3><p class="zone-shade" data-testid="shade-${esc(z)}">${esc(r.shade_name)}${finish}</p></div>
      ${choice}
      ${steps.length ? `<div class="chips" role="group" aria-label="Adjust ${esc(label)}">${steps.map((o) => chipHtml(o, label)).join("")}</div>` : ""}
      ${notes.map((n) => `<p class="chip-note" data-testid="note-${esc(z)}">${esc(n)}</p>`).join("")}
    </article>`;
  }

  function renderZones() {
    const groups = state.zone_groups || [];
    const zones = (state.recipe && state.recipe.zones) || {};
    const keys = groups.flatMap((g) => g.zones.map((z) => z.zone)).filter((z) => z in zones);
    if (!keys.includes(selZone)) selZone = keys[0] || null;
    const scroll = $("zone-tabs").scrollLeft;
    $("zone-tabs").innerHTML = groups.map((g) => `<div class="tab-group"><span class="tab-group-name">${esc(g.label)}</span><div class="tab-row">${g.zones.filter((z) => z.zone in zones).map((z) => `<button type="button" class="tab" data-zone="${esc(z.zone)}" aria-pressed="false">${esc(z.label)}</button>`).join("")}</div></div>`).join("");
    $("zone-tabs").scrollLeft = scroll;
    $("zones").innerHTML = groups.flatMap((g) => g.zones).filter((z) => z.zone in zones).map((z) => zonePanel(z.zone, z.label, z.style, z.note)).join("");
    $("zone-tabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => selectZone(b.dataset.zone, true)));
    document.querySelectorAll("#zones button[data-op], #look-row button[data-op]").forEach((b) => b.addEventListener("click", () => {
      if (b.getAttribute("aria-pressed") !== "true") doEdit({ zone: b.dataset.zone, op: b.dataset.op });
    }));
    const ed = state.edits || [];
    $("undo").disabled = ed.length === 0;
    $("reset").disabled = ed.length === 0;
    $("edit-tools").hidden = ed.length === 0;
    selectZone(selZone);
  }

  function renderNumbers() {
    const map = state.map.zones || {};
    const shades = state.shades || [];
    document.querySelector("#zone-numbers tbody").innerHTML = shades.map((r) =>
      `<tr><th scope="row">${esc(r.label)}</th><td>${esc(r.shade_name)}</td><td>${esc(r.palette.join(" / ").toUpperCase())}</td><td>${esc(r.intensity)}</td></tr>`).join("");
    const measured = shades.filter((r) => map[r.zone]).map((r) => {
      const m = map[r.zone];
      return `${esc(r.label)} ${Math.round((m.coverage || 0) * 100)}% coverage, strength ΔE ${Math.round(Number(m.strength_de) || 0)}`;
    });
    $("measure-note").textContent = measured.length ? `What the transfer changed: ${measured.join(" · ")}.` : "";
  }

  function renderGaps() {
    const gz = (state.gaps && state.gaps.zones) || {};
    const rows = Object.values(gz).map((g) =>
      `<tr><th scope="row">${esc(g.label)}</th><td>${g.color_gap_de2000.toFixed(1)}</td><td>${Math.round(g.coverage_transfer * 100)}% → ${Math.round(g.coverage_render * 100)}%</td></tr>`).join("");
    document.querySelector("#gaps tbody").innerHTML = rows;
    const evened = state.gaps && state.gaps.reference === "even";
    $("gaps-ref").textContent = evened ? "Hair-first look: compared with the transfer under foundation in your shade, because the recipe carries the same foundation." : "";
    $("skin-note").textContent = evened
      ? `Skin control (forehead): the transfer changes it by ΔE76 ${state.map.skin_control_de}; the recipe, with foundation in your shade, by ${state.gaps.skin_control_render_de76}.`
      : `Skin control (forehead, no makeup): the transfer changes it by ΔE76 ${state.map.skin_control_de}, the recipe by ${state.gaps.skin_control_render_de76} — your skin is kept, not beautified.`;
  }

  function render() {
    const im = state.images || {};
    const v = state.views || {};
    $("img-before").src = im[v.before]; $("img-after").src = im[v.after];
    $("img-inspo").src = im.inspiration; $("img-layer").src = im.layer; $("img-look").src = im.look;
    const hairImg = im.hair || (state.order === "hair_first" && im.base) || ""; // hair first: the Hair Transfer on her selfie is "base"
    if (hairImg) { $("img-hair").src = hairImg; } else { $("img-hair").closest("figure").hidden = true; }
    if (!im.hair && hairImg) $("img-hair").alt = "Your selfie with the inspiration hair (YouCam Hair Transfer)";
    const st = state.steps || {};
    setCaption($("cap-after"), st[renderKey()], lookCaption());
    setCaption($("cap-look"), st.mu_transfer, "Inspiration read by Makeup Transfer");
    setCaption($("cap-hair"), st.hair_transfer, im.hair ? "Hair Transfer on your look" : "Hair (YouCam Hair Transfer on your selfie)", "Hair preview unavailable");
    renderHero(); renderPhoto(); renderLooks(); renderZones(); renderNumbers(); renderGaps();
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
    $("status").textContent = body.mode === "replay" ? "Loading the recorded results…" : "Calling YouCam: reading your inspiration and rendering your look (about 30 seconds)…";
    setTimeout(poll, 1200);
  }

  async function doEdit(payload) {
    if (busy) return;
    const a = document.activeElement;
    const refocus = a && a.dataset ? (a.dataset.op ? `button[data-zone="${a.dataset.zone}"][data-op="${a.dataset.op}"]` : (a.id ? `#${a.id}` : "")) : "";
    busy = true; $("edit-msg").textContent = state.mode === "replay" ? "One moment…" : "Rendering with YouCam Makeup VTO…";
    const { ok, body } = await api(`/api/sessions/${sid}/edits`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    busy = false;
    if (!ok) { $("edit-msg").textContent = body.reason || body.detail || "That change didn't work."; return; }
    const was = state.edits || [];
    state = body;
    heroView = "makeup"; // the view that carries the change, never the hair preview
    if (payload.zone && zonesShown) showZones(false);
    if (payload.zone === "look") zoomTo(null); // a look reads on the whole face
    const opts = state.edit_options || [];
    const now = state.edits || [];
    // a change in the same zone is the next choice there; in another zone it took the place of the earlier change
    const replaced = state.mode === "replay" && payload.zone && now.length > 0 && was.length === now.length
      && was[0][0] !== now[0][0] && was[0][0] !== "look" && now[0][0] !== "look";
    const heldOne = state.mode === "replay" && now.length > 0 && opts.length > 0 && !opts.some((o) => o.available);
    $("edit-msg").textContent = replaced ? "Updated. Samples hold one recorded change at a time — this replaced your previous change."
      : heldOne ? "Updated. Samples hold one recorded change at a time — undo it to try another."
      : payload.action === "undo" ? "Undone."
      : payload.action === "reset" ? "Back to your look."
      : "Updated.";
    render();
    const hr = $("img-hero").getBoundingClientRect(); // after a zone change, show the photo if less than half is on screen
    const scrolled = !!payload.zone && Math.min(hr.bottom, innerHeight) - Math.max(hr.top, 0) < hr.height / 2;
    // to the top of the page (the look starts it), not to the photo's top edge: on iPhone Safari the page top keeps
    // the safe-area padding, while the photo's edge (= the top of #look) lands under the status bar with the pills
    if (scrolled) window.scrollTo({ top: 0, behavior: "smooth" });
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
  $("whole-btn").addEventListener("click", () => zoomTo(null));
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
