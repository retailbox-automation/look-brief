"""One bride session, end to end: transfer -> makeup map -> recipe -> re-render -> metric, with hair before or after.

Two orders. transfer_first (the recorded samples s2/s3): Makeup Transfer on the selfie, then the recipe's base render,
then Hair Transfer on that render, so the hair preview wears the new look. hair_first: Hair Transfer on the selfie
gives the "base" (her face with the inspiration hair), Makeup Transfer runs on the base, and the map, metric and every
re-render use the base, so Hair Transfer's relighting never reads as makeup. hair_first also records a foundation in
her own shade over the transfer: the map reads that evened transfer, the renders do not carry it.

The look she is shown is the recipe's render (`views`), not the transfer: the transfer only gives the map and the
colour family, and stays visible further down the page.

All files of a session live in one folder; the returned `state` dict is what the API serves.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from . import landmarks, makeup_map, palettes
from . import recipe as rcp
from .color import hex_to_lab
from .engine import LiveEngine, NotRecorded, ReplayEngine, SessionCtx, StepResult, image_ext
from .youcam import YouCamError

type Engine = LiveEngine | ReplayEngine


ORDERS = ("transfer_first", "hair_first")


def _arrays(workdir: Path, look_name: str, bare_name: str = "bride.jpg") -> tuple[np.ndarray, np.ndarray]:
    bare_img = Image.open(workdir / bare_name).convert("RGB")
    bare = makeup_map.to_rgb_array(bare_img)
    look = makeup_map.to_rgb_array(Image.open(workdir / look_name), size=bare_img.size)
    return bare, look


def face_of(workdir: Path, bare_name: str = "bride.jpg") -> landmarks.FaceGeometry:
    bare = np.asarray(Image.open(workdir / bare_name).convert("RGB"), dtype=np.uint8)
    face = landmarks.detect(bare)
    if face is None:
        raise ValueError("no face found on the bride selfie")
    return face


def _save(workdir: Path, stem: str, res: StepResult) -> str:
    name = stem + image_ext(res.image)
    (workdir / name).write_bytes(res.image)
    return name


def render_name(edits: list[list[str]]) -> str:
    key = rcp.edit_key(edits).replace(":", "-").replace("+", "_")
    return f"render-{key}"


def zone_outlines(face: landmarks.FaceGeometry) -> dict[str, list[list[list[float]]]]:
    """Zone outlines for drawing on the photo: polygons in 0..1 image coordinates (from face landmarks)."""
    polys = landmarks.core_polygons(face)
    out: dict[str, list[list[list[float]]]] = {}
    for zone in ("eyes", "cheeks", "lips"):
        shapes = polys[zone][:1] + polys[zone][3:4] if zone == "eyes" else polys[zone]  # eyelid area of each eye
        out[zone] = [[[round(float(x) / face.width, 4), round(float(y) / face.height, 4)] for x, y in poly]
                     for poly in shapes]
    return out


def skin_hex_of(workdir: Path, bare_name: str, face: landmarks.FaceGeometry) -> str:
    """Her own skin shade: median colour of the forehead (no makeup) on the bare reference."""
    from .color import lab_to_hex, srgb_to_lab

    arr = np.asarray(Image.open(workdir / bare_name).convert("RGB"), dtype=np.uint8)
    forehead = landmarks.zone_cells(face)["skin"]
    return lab_to_hex(np.median(srgb_to_lab(arr[forehead].astype(np.float64) / 255.0), axis=0))


def build_look(engine: Engine, ctx: SessionCtx, workdir: Path, recorder=None, order: str = "transfer_first",
               pins: dict | None = None) -> dict:
    """`pins` (sample.json `recipe_pins`: group, look, shades; `skin_hex` to fix her skin): the recipe of a sample,
    exactly as approved; without pins the group comes from her forehead and the inspiration picks the shades of lips,
    cheeks and lids."""
    if order not in ORDERS:
        raise ValueError(f"unknown order {order}")
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "bride.jpg").write_bytes(ctx.bride_jpeg)
    (workdir / "inspiration.jpg").write_bytes(ctx.inspiration_jpeg)
    state: dict = {"steps": {}, "images": {"bride": "bride.jpg", "inspiration": "inspiration.jpg"}, "notes": [],
                   "order": order, "bare": "bride.jpg"}
    if recorder is not None:
        recorder.set_order(order)

    if order == "hair_first":
        hair = engine.hair_transfer(ctx, on="selfie")  # no fallback: the base is required in this order
        state["steps"]["hair_transfer"] = asdict(hair.meta)
        state["images"]["base"] = state["bare"] = _save(workdir, "base", hair)
        ctx.ids["base_jpeg"] = hair.image
        mu = engine.makeup_transfer(ctx, on="base")
        state["steps"]["mu_transfer"] = asdict(mu.meta)
        state["images"]["look"] = _save(workdir, "look", mu)
        ctx.ids["mu_jpeg"] = mu.image
    else:
        mu = engine.makeup_transfer(ctx)
        state["steps"]["mu_transfer"] = asdict(mu.meta)
        state["images"]["look"] = _save(workdir, "look", mu)

    face = face_of(workdir, state["bare"])
    skin = skin_hex_of(workdir, state["bare"], face)
    if order == "hair_first":
        try:
            ev = engine.even_out(ctx, skin)
            state["steps"]["even_out"] = asdict(ev.meta)
            state["images"]["even"] = _save(workdir, "even", ev)
            state["even_out"] = {"skin_hex": skin, "coverage": 30, "label": rcp.EVEN_OUT_LABEL}
        except (YouCamError, NotRecorded) as e:  # optional step
            state["notes"].append(f"Even-out preview unavailable ({getattr(e, 'code', 'not_recorded')}).")

    recorded = engine.recorded_map() if isinstance(engine, ReplayEngine) else None
    mmap = measure_map(workdir, state, face, recorded)
    if recorder is not None and not recorded:
        recorder.set_map(mmap.to_dict())

    base = engine.recorded_recipe([]) if isinstance(engine, ReplayEngine) else None
    if base is None and pins:
        base = rcp.base_recipe(None, pins["group"], pins.get("skin_hex") or skin, pins["look"], pins.get("shades"))
    state["recipe_base"] = base or rcp.base_recipe(mmap, palettes.skin_group(hex_to_lab(skin)), skin)
    state["quiet_edits"] = engine.quiet_edits() if isinstance(engine, ReplayEngine) else []
    state["edits"] = []
    state["views"] = {"hero": "render", "before": "base" if order == "hair_first" else "bride", "after": "render"}
    state = rerender(engine, ctx, workdir, state, [], face=face)
    if order == "transfer_first":
        try:
            hair = engine.hair_transfer(ctx, on="render")
            state["steps"]["hair_transfer"] = asdict(hair.meta)
            state["images"]["hair"] = _save(workdir, "hair", hair)
        except (YouCamError, NotRecorded) as e:  # the hair preview is optional; the brief still works
            code = getattr(e, "code", "not_recorded")
            state["steps"]["hair_transfer"] = {"error": code}
            state["notes"].append(f"Hair preview unavailable ({code}).")
    return state


def map_reference(state: dict) -> str:
    """The look the makeup map is read from: the evened look once it exists (hair first), else the transfer.
    On a face with natural redness the raw transfer adds blotchy blush (PLATFORM-FINDINGS §10); reading the
    recipe from it would bake that artifact into the cheeks."""
    return state["images"]["even"] if even_out_of(state) else state["images"]["look"]


def measure_map(workdir: Path, state: dict, face: landmarks.FaceGeometry,
                recorded: dict | None = None) -> makeup_map.MakeupMap:
    """Makeup map (recorded one in Replay), the heat layer and the zone outlines, written into `state`."""
    bare, ref = _arrays(workdir, map_reference(state), state["bare"])
    mmap = makeup_map.MakeupMap.from_dict(recorded) if recorded else makeup_map.compute(bare, ref, face)
    makeup_map.heatmap(bare, ref).save(workdir / "layer.png")
    state["images"]["layer"] = "layer.png"
    state["map"] = mmap.to_dict()
    state["map_reference"] = "even" if even_out_of(state) else "transfer"
    state["outlines"] = zone_outlines(face)
    return mmap


def even_out_of(state: dict) -> dict | None:
    """The even-out step of a hair-first look: the transfer the map is read from. Renders do not carry it."""
    ev = state.get("even_out")
    if ev and "even" in state.get("images", {}):
        return {"skin_hex": ev["skin_hex"], "coverage": int(ev.get("coverage", 30))}
    return None


def rerender(engine: Engine, ctx: SessionCtx, workdir: Path, state: dict, edits: list[list[str]],
             face: landmarks.FaceGeometry | None = None) -> dict:
    recipe = None
    if isinstance(engine, ReplayEngine):
        recipe = engine.recorded_recipe(edits)
        if recipe is None:
            raise NotRecorded(rcp.edit_key(edits))
    recipe = recipe or rcp.apply_edits(state["recipe_base"], edits)
    bare_name = state.get("bare", "bride.jpg")
    res = engine.render(ctx, recipe, edits, on="base" if state.get("order") == "hair_first" else "bride")
    name = _save(workdir, render_name(edits), res)
    face = face or face_of(workdir, bare_name)
    bare, transfer = _arrays(workdir, state["images"]["look"], bare_name)
    _, render = _arrays(workdir, name, bare_name)
    gaps = makeup_map.compare(bare, transfer, render, face)
    state["steps"][f"render:{rcp.edit_key(edits)}"] = asdict(res.meta)
    state["images"]["render"] = name
    state["edits"] = edits
    state["recipe"] = recipe
    state["recipe_sha256"] = rcp.recipe_sha256(recipe)
    state["vto_effects"] = rcp.to_vto_effects(recipe)
    state["gaps"] = gaps
    if not edits:
        state["gaps_base"] = gaps
    state["shades"] = rcp.shade_list(recipe, makeup_map.MakeupMap.from_dict(state["map"]))
    return state


def plan_edit(state: dict, zone: str, op: str, recorded: set[str] | None = None) -> dict:
    """What pressing a button does now. {"edits": [...], "replaces": bool}, or {"reason": <key of rcp.BLOCK_NOTES>}.
    `recorded` (Replay): the edit must land on a recorded render; if the combination is not recorded but the single
    change is, it replaces the current one (one change at a time). Buttons and the server share this rule."""
    base = state["recipe_base"]
    now = state.get("recipe") or base
    edits = state.get("edits") or []
    reason = rcp.blocked(now, zone, op)
    if reason:
        return {"reason": reason}
    if rcp.quiet_key(now, zone, op) in (state.get("quiet_edits") or ()):
        return {"reason": "quiet"}
    step = rcp.resolve_edit(now, zone, op)
    nxt = rcp.add_edit(base, edits, *step)
    if recorded is None or rcp.edit_key(nxt) in recorded:
        return {"edits": nxt, "replaces": False}
    single = rcp.add_edit(base, [], *step)
    if rcp.edit_key(single) in recorded:
        return {"edits": single, "replaces": True}
    return {"reason": "not_recorded"}


def _option(state: dict, zone: str, op: str, label: str, recorded: set[str] | None, **extra) -> dict:
    plan = plan_edit(state, zone, op, recorded)
    reason = plan.get("reason")
    opt = {"zone": zone, "op": op, "label": label, "available": reason is None,
           "replaces": bool(plan.get("replaces")), **extra}
    if reason:
        opt |= {"reason": reason, "note": rcp.BLOCK_NOTES[reason]}
    return opt


def no_choice_zones(state: dict) -> list[str]:
    """Zones where no step from the base shade shows on this photo: the sheet names her shade and offers nothing."""
    base = state["recipe_base"]
    quiet = set(state.get("quiet_edits") or ())
    zones = []
    for zone, z in base["zones"].items():
        others = [rcp.quiet_key(base, zone, rcp.SHADE_PREFIX + s.id) for s in palettes.circles(base["group"], zone)
                  if s.id != z["shade_id"]]
        if others and quiet.issuperset(others):
            zones.append(zone)
    return zones


def edit_options(state: dict, recorded_keys: set[str] | None = None) -> list[dict]:
    """Every button of the look screen: {zone, op, label, available, replaces[, reason, note]}. `zone` "look" holds the
    look buttons (+`selected`); op "softer" / "bolder" the steps of lids, cheeks and lips; op "shade:<id>" the circles
    and named styles of a zone (+`name`, `hex`, `colors`, `texture`, `selected`; `hex` is None on "none"). A button that
    is off says why; a button whose step does not show is not offered."""
    now = state.get("recipe") or state["recipe_base"]
    opts = [_option(state, rcp.LOOK_ZONE, look, palettes.LOOK_LABELS[look], recorded_keys, selected=look == now["look"])
            for look in palettes.LOOK_IDS]
    none_left = no_choice_zones(state)
    for zone, z in now["zones"].items():
        if zone in none_left:
            continue
        if zone in palettes.STEP_ZONES:
            opts += [_option(state, zone, op, rcp.EDIT_LABELS[op], recorded_keys) for op in rcp.EDIT_OPS]
        opts += [_option(state, zone, rcp.SHADE_PREFIX + s.id, s.name, recorded_keys, name=s.name,
                         hex=s.main if s.colors else None, colors=list(s.colors), texture=s.texture,
                         selected=s.id == z["shade_id"]) for s in palettes.circles(now["group"], zone)]
    return [o for o in opts if o.get("reason") != "quiet"]
