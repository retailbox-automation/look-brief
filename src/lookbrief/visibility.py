"""Does every button visibly change the face? Measured on the recorded renders of a sample.

Inside the zone, the 90th percentile of dE2000: a circle or a style against the render without edits (render:base);
Softer and Bolder between the two shade renders they step between, from every shade. A mean over the mask dilutes thin
elements (a wing liner: mean 3.7, p90 10.5), and the look screen shows a chosen zone close up, so the strongest tenth
of the zone is what she sees. p90 >= 2.5 was checked by eye by the critic on close-up crops. A step below it is
`quiet`: the sample lists it in `quiet_edits` and the button is not offered (scripts/edit_visibility_report.py --write).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import landmarks, makeup_map, palettes
from .color import delta_e2000
from .recipe import EDIT_OPS, LOOK_ZONE, edit_key, record_grid

MIN_P90 = 2.5
LINER_REACH = 0.05  # height of the band above the upper lid, x inter-ocular distance
LASHES_REACH = 0.09
LIP_RING = 0.03  # half width of the ring on the lip edge, x inter-ocular distance


def _ring(mask: np.ndarray, half_width: int) -> np.ndarray:
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * half_width + 1, 2 * half_width + 1))
    m = mask.astype(np.uint8)
    return cv2.dilate(m, kernel).astype(bool) & ~cv2.erode(m, kernel).astype(bool)


def zone_masks(face: landmarks.FaceGeometry) -> dict[str, np.ndarray]:
    """Where each zone's product shows. The open eye and the open mouth are left out: makeup never lands on them.
    Eyes, cheeks and lips are the shapes session.js draws; thin zones have a mask of their own."""
    polys = landmarks.core_polygons(face)
    placed = landmarks.product_polygons(face)
    w, h = face.width, face.height
    p = face.points
    mouth = landmarks._fill([p[landmarks.LIPS_INNER]], w, h)
    eyes_open = landmarks._fill([np.concatenate([p[landmarks.R_UPPER_LID], p[landmarks.R_LOWER_LID][::-1]]),
                                 np.concatenate([p[landmarks.L_UPPER_LID], p[landmarks.L_LOWER_LID][::-1]])], w, h)
    lips = landmarks._fill(polys["lips"], w, h)
    ring = max(2, round(LIP_RING * face.interocular_px))
    return {
        "eyes": landmarks._fill(polys["eyes"][:1] + polys["eyes"][3:4], w, h) & ~eyes_open,
        "liner": landmarks._fill(landmarks.lid_rim_polygons(face, LINER_REACH), w, h) & ~eyes_open,
        "lashes": landmarks._fill(landmarks.lid_rim_polygons(face, LASHES_REACH), w, h) & ~eyes_open,
        "brows": landmarks._fill(polys["brows"], w, h),
        "cheeks": landmarks._fill(polys["cheeks"], w, h),
        "bronzer": landmarks._fill(placed["bronzer"], w, h),
        "highlight": landmarks._fill(placed["highlight"], w, h),
        "lips": lips & ~mouth,
        "lip_line": _ring(lips, ring) & ~mouth,
    }


def _stat(a: np.ndarray, b: np.ndarray) -> dict:
    de = delta_e2000(a, b)
    p90 = round(float(np.percentile(de, 90)), 2)
    return {"p90": p90, "mean": round(float(de.mean()), 2), "ok": p90 >= MIN_P90}


def edit_visibility(sample_dir: Path) -> dict:
    """{'edits': {key: {'p90', 'mean', 'ok'}}, 'quiet': [keys below the threshold], 'missing': [keys, no render]}.
    Keys are recipe.quiet_key: 'lips:shade:ruby', 'lips:softer@dusty-rose'."""
    mf = json.loads((sample_dir / "manifest.json").read_text())
    steps = mf["steps"]
    bare_name = steps["hair_transfer"]["image"] if mf.get("order") == "hair_first" else "bride.jpg"
    bare = Image.open(sample_dir / bare_name).convert("RGB")
    face = landmarks.detect(np.asarray(bare, dtype=np.uint8))
    if face is None:
        raise ValueError(f"no face on {sample_dir / bare_name}")
    masks = zone_masks(face)
    recipe = steps["render:base"]["recipe"]
    pixels: dict[tuple[str, str], np.ndarray] = {}

    def zone_lab(key: str, zone: str) -> np.ndarray:  # only the zone is kept: 46 full frames would hold 800 MB
        if (key, zone) not in pixels:
            img = Image.open(sample_dir / steps[key]["image"])
            pixels[key, zone] = makeup_map._lab(makeup_map.to_rgb_array(img, size=bare.size))[masks[zone]]
        return pixels[key, zone]

    edits: dict[str, dict] = {}
    missing: list[str] = []

    def measure(name: str, a: str, b: str, zone: str) -> None:
        if a in steps and b in steps:
            edits[name] = _stat(zone_lab(a, zone), zone_lab(b, zone))
        else:
            missing.append(name)

    for change in record_grid(recipe):
        zone, _ = change[0]
        if zone != LOOK_ZONE:
            measure(edit_key(change), "render:base", f"render:{edit_key(change)}", zone)
    for zone, z in recipe["zones"].items():

        def render_of(shade: str, zone: str = zone, start: str = z["shade_id"]) -> str:
            return "render:base" if shade == start else f"render:{zone}:shade:{shade}"

        for s in palettes.ladder(recipe["group"], zone) if zone in palettes.STEP_ZONES else ():
            for op in EDIT_OPS:
                target = palettes.step_from(recipe["group"], zone, recipe["skin_hex"], s.id, op)
                if target:
                    measure(f"{zone}:{op}@{s.id}", render_of(s.id), render_of(target), zone)
    return {"edits": edits, "quiet": [k for k, v in edits.items() if not v["ok"]], "missing": missing}
