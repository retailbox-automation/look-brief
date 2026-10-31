"""Zones -> an editable AI Makeup VTO recipe, and the per-zone edits a bride or artist can ask for.

The measured colour on the face is skin + product. Makeup VTO wants the product colour and an
intensity, so the product colour is pushed away from the bare skin colour by `gain` (a heuristic,
calibrated on recorded renders) and intensity grows with the measured strength. How close the
re-render lands to the transfer is not assumed: it is measured per zone (makeup_map.compare).
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

import numpy as np

from .color import hex_to_lab, lab_to_hex
from .makeup_map import MakeupMap

EDIT_OPS = ("softer", "bolder", "lighter", "deeper")
EDIT_ZONES = ("eyes", "cheeks", "lips")
EDIT_LABELS = {
    "softer": "softer",
    "bolder": "bolder",
    "lighter": "a shade lighter",
    "deeper": "a shade deeper",
}
# Edit steps. Makeup VTO barely moves the photo for intensity +-20 or a shade +-8 L* (recorded renders, 31.10: mean
# dE2000 0.5-1.5 inside the zone, below what a bride sees), so every edit moves the product shade by a fixed step:
# softer -> most of the way to her skin (and less intensity), bolder -> more vivid (chroma up, a little darker),
# lighter/deeper -> L*. Bolder moves mostly in chroma so it never looks like lighter/deeper (switching must show).
# Each recorded edit is checked to change its zone visibly (lookbrief.visibility, tests/test_edit_visibility.py);
# softer is not offered where the zone's whole makeup is already too light to soften visibly.
INTENSITY_STEP = 20
SOFTER_KEEP = {"eyes": 0.0, "cheeks": 0.2, "lips": 0.1}  # softer: product shade = skin + keep * (shade - skin)
SOFTER_INTENSITY = {"eyes": 0.25, "cheeks": 0.4, "lips": 0.3}  # softer: intensity x this
BOLDER_STEP = {"eyes": 28.0, "cheeks": 34.0, "lips": 18.0}  # bolder: chroma (C*ab) up by this, hue kept
BOLDER_DARKEN = {"eyes": 6.0, "cheeks": 8.0, "lips": 0.0}  # bolder: and L* down by this
SHADE_STEP_L = {"eyes": 24.0, "cheeks": 26.0, "lips": 14.0}  # lighter / deeper, L*
LIGHTER_ABOVE_SKIN = {"eyes": 14.0}  # lighter lids end at least this far above her skin's L*, or they read as softer
L_FLOOR = 5.0  # deeper: what the L* step cannot take below this floor goes into chroma (a richer shade)


@dataclass(frozen=True)
class ZoneTuning:
    """Fitted on recorded renders (docs/CALIBRATION.md): intensity follows the transfer's coverage,
    the product shade is pushed away from the skin by `gain`, and lips get lighter by `l_offset`
    because Makeup VTO lands lip colour darker than the hex it is given."""

    category: str
    pattern: str  # label from the pattern catalog (eyeshadow.json / blush.json) or lip shape
    gain: float  # product colour = skin + gain * (look - skin), in Lab
    base_intensity: float  # intensity at coverage == coverage_ref
    intensity_per_coverage: float  # extra intensity per unit of coverage above coverage_ref
    coverage_ref: float
    min_intensity: int
    max_intensity: int
    l_offset: float = 0.0  # added to the product L*
    intensity_from_strength: float = 0.0  # if > 0: intensity = strength_dE * this (lips)


TUNING = {
    "eyes": ZoneTuning("eye_shadow", "1color1", gain=1.8, base_intensity=80, intensity_per_coverage=130,
                       coverage_ref=0.325, min_intensity=40, max_intensity=100),
    "cheeks": ZoneTuning("blush", "1color1", gain=2.5, base_intensity=56, intensity_per_coverage=120,
                         coverage_ref=0.0, min_intensity=40, max_intensity=100),
    "lips": ZoneTuning("lip_color", "original", gain=1.15, base_intensity=0, intensity_per_coverage=0,
                       coverage_ref=0.0, min_intensity=35, max_intensity=90, l_offset=8.0,
                       intensity_from_strength=5.5),
}

NO_SMOOTHING = {"category": "skin_smooth", "skinSmoothStrength": 0, "skinSmoothColorIntensity": 0}


def _clip_int(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


def product_color(color_before: str, color_after: str, gain: float, l_offset: float = 0.0) -> str:
    skin, look = hex_to_lab(color_before), hex_to_lab(color_after)
    prod = skin + gain * (look - skin)
    prod[0] = float(np.clip(prod[0] + l_offset, 5, 95))
    return lab_to_hex(prod)


def zone_intensity(tune: ZoneTuning, coverage: float, strength_de: float) -> int:
    if tune.intensity_from_strength > 0:
        raw = strength_de * tune.intensity_from_strength
    else:
        raw = tune.base_intensity + tune.intensity_per_coverage * (coverage - tune.coverage_ref)
    return _clip_int(raw, tune.min_intensity, tune.max_intensity)


def base_recipe(m: MakeupMap) -> dict:
    """Recipe state: one entry per makeup zone that the transfer actually changed."""
    zones: dict[str, dict] = {}
    for name, tune in TUNING.items():
        z = m.zones.get(name)
        if z is None or z.changed_px < 200:
            continue
        zones[name] = {
            "category": tune.category,
            "pattern": tune.pattern,
            "color": product_color(z.color_before, z.color_after, tune.gain, tune.l_offset),
            "intensity": zone_intensity(tune, z.coverage, z.strength_de),
            "skin": z.color_before,
        }
    return {"version": 1, "zones": zones}


def _more_vivid(z: dict, step: float, darken: float = 0.0) -> str:
    """The product shade with its chroma raised by `step` and L* lowered by `darken` (hue kept); a near-grey shade
    takes her skin's hue."""
    col = hex_to_lab(z["color"])
    ab = col[1:].copy()
    c = float(np.hypot(*ab))
    if c < 1.0:
        ab = hex_to_lab(z.get("skin", z["color"]))[1:]
        c = float(np.hypot(*ab)) or 1.0
        col[1:] = 0.0
    col[1:] = col[1:] + step * ab / c
    col[0] = float(np.clip(col[0] - darken, 5, 95))
    return lab_to_hex(col)


def apply_edit(recipe: dict, zone: str, op: str) -> dict:
    if zone not in EDIT_ZONES or op not in EDIT_OPS:
        raise ValueError(f"unknown edit {zone}/{op}")
    out = copy.deepcopy(recipe)
    z = out["zones"].get(zone)
    if z is None:
        raise ValueError(f"zone {zone} is not in this look")
    if op == "softer":
        skin, col = hex_to_lab(z.get("skin", z["color"])), hex_to_lab(z["color"])
        z["color"] = lab_to_hex(skin + SOFTER_KEEP[zone] * (col - skin))
        z["intensity"] = _clip_int(z["intensity"] * SOFTER_INTENSITY[zone], 10, 100)
    elif op == "bolder":
        z["color"] = _more_vivid(z, BOLDER_STEP[zone], BOLDER_DARKEN[zone])
        z["intensity"] = _clip_int(z["intensity"] + INTENSITY_STEP, 10, 100)
    elif op == "lighter":
        lab = hex_to_lab(z["color"])
        target = lab[0] + SHADE_STEP_L[zone]
        if zone in LIGHTER_ABOVE_SKIN:
            target = max(target, hex_to_lab(z.get("skin", z["color"]))[0] + LIGHTER_ABOVE_SKIN[zone])
        lab[0] = float(np.clip(target, 5, 95))
        z["color"] = lab_to_hex(lab)
    else:  # deeper
        lab = hex_to_lab(z["color"])
        target = lab[0] - SHADE_STEP_L[zone]
        lab[0] = float(max(target, L_FLOOR))
        z["color"] = lab_to_hex(lab)
        if target < L_FLOOR:
            z["color"] = _more_vivid(z, L_FLOOR - target)
    return out


def apply_edits(recipe: dict, edits: list[list[str]]) -> dict:
    for zone, op in edits:
        recipe = apply_edit(recipe, zone, op)
    return recipe


def edit_key(edits: list[list[str]]) -> str:
    """Stable key for a list of edits (used to look up recorded renders in Replay)."""
    if not edits:
        return "base"
    return "+".join(f"{z}:{o}" for z, o in edits)


def to_vto_effects(recipe: dict, even_out: dict | None = None) -> list[dict]:
    """Recipe -> `effects` for POST /s2s/v2.0/task/makeup-vto (schema: makeup_vto.yaml).

    `even_out` ({"skin_hex", "coverage"}): once the bride has the "Even out redness" step, every re-render carries
    the same foundation in her shade under the recipe, so an edit never brings the redness back."""
    effects: list[dict] = [dict(NO_SMOOTHING)]
    if even_out:
        effects.append(foundation_effect(even_out["skin_hex"], int(even_out.get("coverage", 30))))
    zones = recipe["zones"]
    if "eyes" in zones:
        z = zones["eyes"]
        effects.append({
            "category": "eye_shadow",
            "pattern": {"name": z.get("pattern", "1color1")},
            "palettes": [{"color": z["color"], "texture": "matte", "colorIntensity": z["intensity"]}],
        })
    if "cheeks" in zones:
        z = zones["cheeks"]
        effects.append({
            "category": "blush",
            "pattern": {"name": z.get("pattern", "1color1")},
            "palettes": [{"color": z["color"], "texture": "matte", "colorIntensity": z["intensity"]}],
        })
    if "lips" in zones:
        z = zones["lips"]
        effects.append({
            "category": "lip_color",
            "shape": {"name": z.get("pattern", "original")},
            "palettes": [{"color": z["color"], "texture": "matte", "colorIntensity": z["intensity"]}],
            "style": {"type": "full"},  # without `style` the API answers 400 (oneOf of 7 variants)
        })
    return effects


EVEN_OUT_LABEL = "foundation in her shade over the transfer"


def foundation_effect(skin_hex: str, coverage: int = 30) -> dict:
    return {"category": "foundation", "palettes": [
        {"color": skin_hex, "colorIntensity": 50, "glowIntensity": 0, "coverageIntensity": int(coverage)}]}


def even_out_effects(skin_hex: str, coverage: int = 30) -> list[dict]:
    """'Even out redness': a foundation in the bride's own shade, applied by Makeup VTO ON TOP of the
    Makeup Transfer result (lips and eyes stay as transferred). No smoothing."""
    return [dict(NO_SMOOTHING), foundation_effect(skin_hex, coverage)]


def vto_body(recipe: dict, even_out: dict | None = None) -> dict:
    return {"version": "1.0", "effects": to_vto_effects(recipe, even_out)}


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def recipe_sha256(recipe: dict) -> str:
    return hashlib.sha256(canonical(recipe)).hexdigest()


def shade_list(recipe: dict, m: MakeupMap) -> list[dict]:
    """What the artist confirms: one line per zone with the product shade to bring to the trial."""
    rows = []
    for name, z in recipe["zones"].items():
        zs = m.zones.get(name)
        rows.append({
            "zone": name,
            "label": zs.label if zs else name,
            "category": z["category"],
            "product_hex": z["color"],
            "intensity": z["intensity"],
            "on_face_hex": zs.color_after if zs else None,
            "coverage": zs.coverage if zs else None,
        })
    return rows
