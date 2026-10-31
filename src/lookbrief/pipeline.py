"""One bride session, end to end: transfer -> hair -> makeup map -> recipe -> re-render -> metric.

Two orders. transfer_first (the recorded samples s2/s3): Makeup Transfer on the selfie, Hair Transfer on that.
hair_first: Hair Transfer on the selfie gives the "base" (her face with the inspiration hair), Makeup Transfer runs
on the base, and the map, metric and every re-render use the base, so Hair Transfer's relighting never reads as
makeup. hair_first also records "Even out redness": a foundation in her own shade over the transfer.

All files of a session live in one folder; the returned `state` dict is what the API serves.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from . import landmarks, makeup_map
from . import recipe as rcp
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


def build_look(engine: Engine, ctx: SessionCtx, workdir: Path, recorder=None, order: str = "transfer_first") -> dict:
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
        try:
            hair = engine.hair_transfer(ctx)
            state["steps"]["hair_transfer"] = asdict(hair.meta)
            state["images"]["hair"] = _save(workdir, "hair", hair)
        except (YouCamError, NotRecorded) as e:  # the hair preview is optional; the brief still works
            code = getattr(e, "code", "not_recorded")
            state["steps"]["hair_transfer"] = {"error": code}
            state["notes"].append(f"Hair preview unavailable ({code}).")

    face = face_of(workdir, state["bare"])
    if order == "hair_first":
        skin = skin_hex_of(workdir, state["bare"], face)
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
    base = base or rcp.base_recipe(mmap)
    state["recipe_base"] = base
    state["edits"] = []
    return rerender(engine, ctx, workdir, state, [], face=face)


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
    """The foundation every re-render carries once the even-out step exists (hair-first looks)."""
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
    # After "Even out redness" every re-render carries the same foundation, and accuracy is measured against the
    # evened look the bride is shown (otherwise an edit brings the redness back and is compared to the patchy transfer).
    even = even_out_of(state)
    res = engine.render(ctx, recipe, edits, on="base" if state.get("order") == "hair_first" else "bride", even_out=even)
    name = _save(workdir, render_name(edits), res)
    face = face or face_of(workdir, bare_name)
    reference = state["images"]["even"] if even else state["images"]["look"]
    bare, transfer = _arrays(workdir, reference, bare_name)
    _, render = _arrays(workdir, name, bare_name)
    gaps = makeup_map.compare(bare, transfer, render, face)
    gaps["reference"] = "even" if even else "transfer"
    state["steps"][f"render:{rcp.edit_key(edits)}"] = asdict(res.meta)
    state["images"]["render"] = name
    state["edits"] = edits
    state["recipe"] = recipe
    state["recipe_sha256"] = rcp.recipe_sha256(recipe)
    state["vto_effects"] = rcp.to_vto_effects(recipe, even)
    state["gaps"] = gaps
    if not edits:
        state["gaps_base"] = gaps
    state["shades"] = rcp.shade_list(recipe, makeup_map.MakeupMap.from_dict(state["map"]))
    return state


def edit_options(state: dict, recorded_keys: set[str] | None = None) -> list[dict]:
    """Edits offered next. With `recorded_keys` (Replay) an edit is available when the combination is recorded,
    or when the single edit is recorded: then it replaces the current one (`replaces`; one change at a time)."""
    current = state.get("edits") or []
    zones = list((state.get("recipe_base") or {}).get("zones", {}))
    opts = []
    for z in zones:
        for op in rcp.EDIT_OPS:
            nxt = [*current, [z, op]]
            available = recorded_keys is None or rcp.edit_key(nxt) in recorded_keys
            replaces = not available and bool(current) and rcp.edit_key([[z, op]]) in (recorded_keys or ())
            opts.append({"zone": z, "op": op, "label": rcp.EDIT_LABELS[op], "available": available or replaces,
                         "replaces": replaces})
    return opts
