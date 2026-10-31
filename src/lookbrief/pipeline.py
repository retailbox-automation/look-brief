"""One bride session, end to end: transfer -> hair -> makeup map -> recipe -> re-render -> metric.

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


def _arrays(workdir: Path, look_name: str) -> tuple[np.ndarray, np.ndarray]:
    bare_img = Image.open(workdir / "bride.jpg").convert("RGB")
    bare = makeup_map.to_rgb_array(bare_img)
    look = makeup_map.to_rgb_array(Image.open(workdir / look_name), size=bare_img.size)
    return bare, look


def face_of(workdir: Path) -> landmarks.FaceGeometry:
    bare = np.asarray(Image.open(workdir / "bride.jpg").convert("RGB"), dtype=np.uint8)
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


def build_look(engine: Engine, ctx: SessionCtx, workdir: Path, recorder=None) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "bride.jpg").write_bytes(ctx.bride_jpeg)
    (workdir / "inspiration.jpg").write_bytes(ctx.inspiration_jpeg)
    state: dict = {"steps": {}, "images": {"bride": "bride.jpg", "inspiration": "inspiration.jpg"}, "notes": []}

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

    face = face_of(workdir)
    bare, look = _arrays(workdir, state["images"]["look"])
    mmap = None
    if isinstance(engine, ReplayEngine) and engine.recorded_map():
        mmap = makeup_map.MakeupMap.from_dict(engine.recorded_map())  # exactly what was rendered
    if mmap is None:
        mmap = makeup_map.compute(bare, look, face)
        if recorder is not None:
            recorder.set_map(mmap.to_dict())
    makeup_map.heatmap(bare, look).save(workdir / "layer.png")
    state["images"]["layer"] = "layer.png"
    state["map"] = mmap.to_dict()

    base = engine.recorded_recipe([]) if isinstance(engine, ReplayEngine) else None
    base = base or rcp.base_recipe(mmap)
    state["recipe_base"] = base
    state["edits"] = []
    return rerender(engine, ctx, workdir, state, [], face=face)


def rerender(engine: Engine, ctx: SessionCtx, workdir: Path, state: dict, edits: list[list[str]],
             face: landmarks.FaceGeometry | None = None) -> dict:
    recipe = None
    if isinstance(engine, ReplayEngine):
        recipe = engine.recorded_recipe(edits)
        if recipe is None:
            raise NotRecorded(rcp.edit_key(edits))
    recipe = recipe or rcp.apply_edits(state["recipe_base"], edits)
    res = engine.render(ctx, recipe, edits)
    name = _save(workdir, render_name(edits), res)
    face = face or face_of(workdir)
    bare, transfer = _arrays(workdir, state["images"]["look"])
    _, render = _arrays(workdir, name)
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


def edit_options(state: dict, recorded_keys: set[str] | None = None) -> list[dict]:
    """Edits offered next. With `recorded_keys` (Replay) only recorded combinations are available."""
    current = state.get("edits") or []
    zones = list((state.get("recipe_base") or {}).get("zones", {}))
    opts = []
    for z in zones:
        for op in rcp.EDIT_OPS:
            nxt = [*current, [z, op]]
            available = recorded_keys is None or rcp.edit_key(nxt) in recorded_keys
            opts.append({"zone": z, "op": op, "label": rcp.EDIT_LABELS[op], "available": available})
    return opts
