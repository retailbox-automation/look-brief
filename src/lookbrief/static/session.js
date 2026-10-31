"use strict";
(() => {
  const app = document.getElementById("app");
  const sid = app.dataset.sid;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let state = null;
  let busy = false;

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
    return `${what} — ${src} · task ${String(meta.task_id).slice(0, 10)}… · ${meta.seconds}s${when}`;
  }

  function renderZones() {
    const opts = state.edit_options || [];
    const zones = (state.recipe && state.recipe.zones) || {};
    const map = state.map.zones;
    const html = Object.keys(zones).map((z) => {
      const r = zones[z];
      const m = map[z] || {};
      const buttons = opts.filter((o) => o.zone === z).map((o) =>
        `<button type="button" class="chip" data-zone="${z}" data-op="${o.op}" ${o.available ? "" : "disabled"} aria-label="${esc(m.label)}: ${esc(o.label)}">${esc(o.label[0].toUpperCase() + o.label.slice(1))}</button>`).join("");
      return `<article class="zone" data-testid="zone-${z}">
        <h3>${esc(m.label || z)}</h3>
        <p><span class="swatch" style="background:${esc(r.color)}" aria-hidden="true"></span> Product shade <code>${esc(r.color)}</code> · intensity ${esc(r.intensity)}</p>
        <p class="note">On your face: <span class="swatch sm" style="background:${esc(m.color_after)}" aria-hidden="true"></span> ${esc(m.color_after)} · coverage ${Math.round((m.coverage || 0) * 100)}% · strength ΔE ${esc(m.strength_de)}</p>
        <div class="chips" role="group" aria-label="Adjust ${esc(m.label)}">${buttons}</div>
      </article>`;
    }).join("");
    $("zones").innerHTML = html;
    const extra = map.nose && map.nose.changed_px > 200
      ? `<p class="note">Also changed: nose &amp; contour (${Math.round(map.nose.coverage * 100)}% of that area) — not re-rendered, flag it with your artist.</p>` : "";
    $("zones").insertAdjacentHTML("beforeend", extra);
    $("zones").querySelectorAll("button.chip").forEach((b) => b.addEventListener("click", () => doEdit({ zone: b.dataset.zone, op: b.dataset.op })));
    const ed = state.edits || [];
    $("undo").disabled = ed.length === 0;
    $("reset").disabled = ed.length === 0;
  }

  function renderGaps() {
    const rows = Object.values((state.gaps && state.gaps.zones) || {}).map((g) =>
      `<tr><th scope="row">${esc(g.label)}</th><td>${g.color_gap_de2000.toFixed(1)}</td><td>${Math.round(g.coverage_transfer * 100)}% → ${Math.round(g.coverage_render * 100)}%</td></tr>`).join("");
    document.querySelector("#gaps tbody").innerHTML = rows;
    $("skin-note").textContent = `Skin control (forehead, no makeup): transfer changes it by ΔE76 ${state.map.skin_control_de}, recipe render by ${state.gaps.skin_control_render_de76} — your skin is kept, not beautified.`;
  }

  function render() {
    const im = state.images || {};
    $("img-before").src = im.bride; $("img-after").src = im.look;
    $("img-inspo").src = im.inspiration; $("img-layer").src = im.layer; $("img-render").src = im.render;
    if (im.hair) { $("img-hair").src = im.hair; } else { $("img-hair").closest("figure").hidden = true; }
    const st = state.steps || {};
    $("cap-after").textContent = stepCaption(st.mu_transfer, "Makeup Transfer");
    $("cap-hair").textContent = st.hair_transfer && st.hair_transfer.task_id ? stepCaption(st.hair_transfer, "Hair Transfer") : "Hair preview unavailable";
    const key = (state.edits || []).length ? "render:" + state.edits.map((e) => e.join(":")).join("+") : "render:base";
    $("cap-render").textContent = stepCaption(st[key], "Makeup VTO re-render");
    renderZones(); renderGaps();
    $("tech").textContent = JSON.stringify({ steps: state.steps, recipe: state.recipe, vto_effects: state.vto_effects, map: state.map }, null, 2);
    $("look").hidden = false;
  }

  async function poll() {
    const { ok, body } = await api(`/api/sessions/${sid}`);
    if (!ok) { $("status").textContent = "Session not found."; return; }
    state = body;
    if (body.status === "ready") { $("status").textContent = body.mode === "replay" ? "Replaying recorded real YouCam API results." : `Done. YouCam units used: ${body.units_spent}.`; render(); return; }
    if (body.status === "error") {
      const h = body.error_hint || { title: "Something went wrong", fix: "" };
      $("status").innerHTML = `<strong>${esc(h.title)}.</strong> ${esc(h.fix)} <a href="/">Back</a>`;
      return;
    }
    $("status").textContent = body.mode === "replay" ? "Loading the recorded results…" : "Calling YouCam: makeup transfer → hair → re-render (about 25 seconds)…";
    setTimeout(poll, 1200);
  }

  async function doEdit(payload) {
    if (busy) return;
    busy = true; $("edit-msg").textContent = "Re-rendering with YouCam Makeup VTO…";
    const { ok, body } = await api(`/api/sessions/${sid}/edits`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    busy = false;
    if (!ok) { $("edit-msg").textContent = body.reason || body.detail || "That change didn't work."; return; }
    state = body; $("edit-msg").textContent = "Updated."; render();
  }

  $("ba").addEventListener("input", (e) => { $("img-after").style.clipPath = `inset(0 0 0 ${e.target.value}%)`; });
  $("undo").addEventListener("click", () => doEdit({ action: "undo" }));
  $("reset").addEventListener("click", () => doEdit({ action: "reset" }));
  $("make-brief").addEventListener("click", async () => {
    const { ok, body } = await api(`/api/sessions/${sid}/brief`, { method: "POST" });
    if (!ok) return;
    const a = $("artist-link"), b = $("bride-link");
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
