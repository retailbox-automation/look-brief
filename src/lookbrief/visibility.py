"""Does every button visibly change the face? Measured on the recorded renders of a sample.

Inside the zone, mean dE2000 and the share of pixels above the just-noticeable 2.3: a circle or a finish against the
render without edits (render:base); Softer and Bolder as the pair of shade renders they step between, for every step
of the skin order. Thresholds (visible at a glance on a phone, checked by eye on 1:1 zone crops, decision 31.10):
mean >= 3.5 with >= 60 % of pixels over 2.3. A step below them is `quiet`: the sample lists it in `quiet_edits` and
the button is not offered (scripts/edit_visibility_report.py --write).
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import numpy as np
from PIL import Image

from . import landmarks, makeup_map, palettes
from .color import delta_e2000
from .recipe import LOOK_ZONE, edit_key, record_grid

JND = 2.3
MIN_MEAN = 3.5
MIN_SHARE = 0.60
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
    mean, share = round(float(de.mean()), 2), round(float((de > JND).mean()), 3)
    return {"mean": mean, "share": share, "ok": mean >= MIN_MEAN and share >= MIN_SHARE}


def edit_visibility(sample_dir: Path) -> dict:
    """{'edits': {key: {'mean', 'share', 'ok'}}, 'quiet': [keys below the thresholds], 'missing': [keys, no render]}.
    Keys are recipe.quiet_key: 'lips:shade:ruby', 'lips:finish:gloss', 'lips:softer@dusty-rose'."""
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

        chain = [s.id for s in palettes.skin_order(recipe["group"], zone, recipe["skin_hex"])]
        if zone in palettes.THIN_ZONES:
            chain.insert(0, palettes.NONE_ID)
        for a, b in pairwise(chain):
            measure(f"{zone}:bolder@{a}", render_of(a), render_of(b), zone)
            if a != palettes.NONE_ID:
                measure(f"{zone}:softer@{b}", render_of(a), render_of(b), zone)
    return {"edits": edits, "quiet": [k for k, v in edits.items() if not v["ok"]], "missing": missing}
