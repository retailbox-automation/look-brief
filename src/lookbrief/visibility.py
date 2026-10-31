"""Does every edit button visibly change the face? Measured on the recorded renders of a sample.

For each zone edit the recorded re-render is compared with the re-render without edits (render:base), inside the
outline of that zone as the app draws it: mean dE2000 and the share of pixels above the just-noticeable 2.3. Every
pair of edits of one zone is compared the same way (tapping one button after another must change the photo too).
Thresholds (visible at a glance on a phone, checked by eye on 1:1 zone crops, decision 31.10): mean >= 3.5 with
>= 60 % of pixels over 2.3 against the base render, and mean >= 3.0 between two edits of one zone.

Covers the zones with an outline (eyes, cheeks, lips); a button on the edge of its ladder or range is off and not
measured. Lighter / Deeper are read from the render of the neighbour circle.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import landmarks, makeup_map
from .color import delta_e2000
from .recipe import EDIT_OPS, blocked, edit_key, resolve_edit

JND = 2.3
MIN_MEAN = 3.5
MIN_SHARE = 0.60
MIN_PAIR_MEAN = 3.0


def zone_masks(face: landmarks.FaceGeometry) -> dict[str, np.ndarray]:
    """The outlined area of each zone (the shapes session.js draws): eyelids of both eyes, both cheeks, lips.
    The open eye and the open mouth inside the outlines are left out: makeup never lands on them."""
    polys = landmarks.core_polygons(face)
    w, h = face.width, face.height
    p = face.points
    mouth = landmarks._fill([p[landmarks.LIPS_INNER]], w, h)
    eyes_open = landmarks._fill([np.concatenate([p[landmarks.R_UPPER_LID], p[landmarks.R_LOWER_LID][::-1]]),
                                 np.concatenate([p[landmarks.L_UPPER_LID], p[landmarks.L_LOWER_LID][::-1]])], w, h)
    return {
        "eyes": landmarks._fill(polys["eyes"][:1] + polys["eyes"][3:4], w, h) & ~eyes_open,
        "cheeks": landmarks._fill(polys["cheeks"], w, h),
        "lips": landmarks._fill(polys["lips"], w, h) & ~mouth,
    }


def _stat(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> dict:
    de = delta_e2000(a[m], b[m])
    return {"mean": round(float(de.mean()), 2), "share": round(float((de > JND).mean()), 3)}


def zone_strength(bare: np.ndarray, render: np.ndarray, masks: dict[str, np.ndarray]) -> dict[str, float]:
    """Mean dE2000 inside each zone outline between the bare face and the base render (Lab arrays): its whole makeup."""
    return {z: round(float(delta_e2000(bare[m], render[m]).mean()), 2) for z, m in masks.items() if m.any()}


def edit_visibility(sample_dir: Path) -> dict:
    """{'edits': {'lips:bolder': {'mean', 'share', 'ok'}}, 'pairs': {'lips:bolder>lighter': {...}},
    'strength': {zone: dE}, 'offered': ['lips:bolder', ...], 'missing': [...], 'ok': bool}."""
    mf = json.loads((sample_dir / "manifest.json").read_text())
    steps = mf["steps"]
    bare_name = steps["hair_transfer"]["image"] if mf.get("order") == "hair_first" else "bride.jpg"
    bare = Image.open(sample_dir / bare_name).convert("RGB")
    face = landmarks.detect(np.asarray(bare, dtype=np.uint8))
    if face is None:
        raise ValueError(f"no face on {sample_dir / bare_name}")
    masks = zone_masks(face)

    def lab(key: str) -> np.ndarray:
        img = Image.open(sample_dir / steps[key]["image"])
        return makeup_map._lab(makeup_map.to_rgb_array(img, size=bare.size))

    base = lab("render:base")
    bare_lab = makeup_map._lab(makeup_map.to_rgb_array(bare))
    recipe = steps["render:base"]["recipe"]
    zones = [z for z in masks if z in recipe["zones"]]
    strength = zone_strength(bare_lab, base, {z: masks[z] for z in zones})
    renders = {(z, op): f"render:{edit_key([resolve_edit(recipe, z, op)])}" for z in zones for op in EDIT_OPS
               if not blocked(recipe, z, op)}
    offered = [f"{z}:{op}" for z, op in renders]
    missing = [f"{z}:{op}" for (z, op), key in renders.items() if key not in steps]
    edits, pairs = {}, {}
    for z in zones:
        ops = [op for op in EDIT_OPS if renders.get((z, op)) in steps]
        imgs = {op: lab(renders[(z, op)]) for op in ops}
        for op in ops:
            s = _stat(base, imgs[op], masks[z])
            edits[f"{z}:{op}"] = {**s, "ok": s["mean"] >= MIN_MEAN and s["share"] >= MIN_SHARE}
        for a, b in itertools.combinations(ops, 2):
            s = _stat(imgs[a], imgs[b], masks[z])
            pairs[f"{z}:{a}>{b}"] = {**s, "ok": s["mean"] >= MIN_PAIR_MEAN}
    ok = bool(edits) and not missing and all(e["ok"] for e in edits.values()) and all(p["ok"] for p in pairs.values())
    return {"edits": edits, "pairs": pairs, "strength": strength, "offered": offered, "missing": missing, "ok": ok}
