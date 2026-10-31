"""A look on nine zones -> an editable AI Makeup VTO recipe, and the edits a bride or artist can ask for.

The recipe comes from the palette (lookbrief.palettes), not from the transfer: the look sets every zone, and on a live
photo the inspiration picks the colour family of lips, cheeks and lids from the ladder. An edit is a step on a ladder
or a strength inside a range, so no path can send a colour of its own. How far the re-render lands from the transfer
is measured per zone (makeup_map.compare); the recipe is no longer fitted to it.
"""

from __future__ import annotations

import copy
import hashlib
import json

import numpy as np

from . import palettes
from .color import hex_to_lab
from .makeup_map import MakeupMap

RECIPE_VERSION = 2
EDIT_OPS = ("softer", "bolder", "lighter", "deeper")
EDIT_ZONES = tuple(palettes.ZONES)
EDIT_LABELS = {
    "softer": "softer",
    "bolder": "bolder",
    "lighter": "a shade lighter",
    "deeper": "a shade deeper",
}
BLOCK_NOTES = {  # why a button is off
    "softest": "This is the softest this zone goes.",
    "boldest": "This is the boldest this zone goes.",
    "lightest": "This is the lightest shade in your palette.",
    "deepest": "This is the deepest shade in your palette.",
    "current": "",
    "not_recorded": "This change isn't in the recorded set.",
}
SHADE_PREFIX = "shade:"
LOOK_ZONE = "look"  # an edit ["look", "evening"] swaps the whole recipe
TONE_ZONES = ("lips", "cheeks", "eyes")  # the zones whose shade follows the inspiration on a live photo
MIN_CHANGED_PX = 200  # fewer changed pixels: the transfer says nothing about this zone

NO_SMOOTHING = {"category": "skin_smooth", "skinSmoothStrength": 0, "skinSmoothColorIntensity": 0}
# Finish numbers accepted by the API in the probes of 2026-10-31 (the same in every look).
HIGHLIGHT_FINISH = {"glowIntensity": 45, "shimmerIntensity": 25, "shimmerDensity": 35, "shimmerSize": 25}
SHEER_FINISH = {"gloss": 45, "transparencyIntensity": 30}
LIP_LINE_FINISH = {"thickness": 30, "smoothness": 70}
FOUNDATION_INTENSITY = 40  # 50 lifted the heroine's forehead L* by 1.7; the target is 1.5 at most
FOUNDATION_GLOW = 20


def _zone(group: str, zone: str, spec: palettes.ZoneLook, shade_id: str | None = None) -> dict:
    s = palettes.shade(group, zone, shade_id or spec.shade)
    z = {"category": palettes.ZONES[zone], "shade_id": s.id, "shade_name": s.name, "palette": list(s.colors),
         "texture": s.texture, "pattern": spec.pattern, "intensity": spec.intensity}
    if zone == "eyes":
        z |= {"shimmer": spec.shimmer, "crease_offset": spec.crease_offset}
    elif zone == "cheeks":
        z["glow"] = spec.glow
    return z


def look_recipe(group: str, look: str, shades: dict[str, str] | None = None) -> dict:
    """The look as it stands on the palette; `shades` swaps single zones ({zone: shade id})."""
    if group not in palettes.GROUPS or look not in palettes.LOOK_IDS:
        raise ValueError(f"unknown look {group}/{look}")
    picks = shades or {}
    spec = palettes.LOOKS[group][look]
    if set(picks) - set(spec):
        raise ValueError(f"the {look} look has no zones {sorted(set(picks) - set(spec))}")
    return {"version": RECIPE_VERSION, "group": group, "look": look,
            "zones": {z: _zone(group, z, zl, picks.get(z)) for z, zl in spec.items()}}


def _nearest_tone(group: str, zone: str, color: str) -> str:
    """The ladder step closest to a colour in the a*b* plane: hue and chroma decide the family, lightness does not
    (a transfer lands lighter or darker than the product, and a ruby and a peach pink share a hue)."""
    target = hex_to_lab(color)[1:]

    def distance(s: palettes.Shade) -> float:
        return float(np.linalg.norm(hex_to_lab(s.colors[0])[1:] - target))

    return min(palettes.ladder(group, zone), key=distance).id


def base_recipe(m: MakeupMap | None, group: str, look: str = palettes.DEFAULT_LOOK,
                shades: dict[str, str] | None = None) -> dict:
    """The look, with lips, cheeks and lids taken from the ladder by the colour the transfer put there, so the
    inspiration decides the family and the palette keeps it beautiful. `m=None` (a pinned sample): exactly the look.
    `shades` wins over the transfer."""
    picks: dict[str, str] = {}
    if m is not None:
        for zone in TONE_ZONES:
            stat = m.zones.get(zone)
            if stat is not None and stat.changed_px >= MIN_CHANGED_PX:
                picks[zone] = _nearest_tone(group, zone, stat.color_after)
    return look_recipe(group, look, {**picks, **(shades or {})})


def _check(recipe: dict, zone: object, op: object) -> None:
    if not isinstance(op, str):
        raise ValueError(f"unknown edit {zone}/{op}")
    if zone == LOOK_ZONE:
        if op not in palettes.LOOK_IDS:
            raise ValueError(f"unknown look {op}")
        return
    if zone not in EDIT_ZONES or not (op in EDIT_OPS or op.startswith(SHADE_PREFIX)):
        raise ValueError(f"unknown edit {zone}/{op}")
    if zone not in recipe["zones"]:
        raise ValueError(f"zone {zone} is not in this look")
    if op.startswith(SHADE_PREFIX):
        palettes.shade(recipe["group"], str(zone), op.removeprefix(SHADE_PREFIX))


def _ladder_ids(recipe: dict, zone: str) -> list[str]:
    return [s.id for s in palettes.ladder(recipe["group"], zone)]


def blocked(recipe: dict, zone: str, op: str) -> str | None:
    """Why this edit cannot be made now (a key of BLOCK_NOTES), or None. An unknown edit raises ValueError."""
    _check(recipe, zone, op)
    if zone == LOOK_ZONE:
        return "current" if op == recipe["look"] else None
    z = recipe["zones"][zone]
    if op.startswith(SHADE_PREFIX):
        return "current" if op.removeprefix(SHADE_PREFIX) == z["shade_id"] else None
    if op in ("softer", "bolder"):  # a step that would leave the range is off, not cut short
        lo, hi = palettes.RANGES[recipe["group"]][zone]
        step = palettes.INTENSITY_STEP[zone]
        if op == "softer":
            return "softest" if z["intensity"] - step < lo else None
        return "boldest" if z["intensity"] + step > hi else None
    ids = _ladder_ids(recipe, zone)
    i = ids.index(z["shade_id"])
    if op == "lighter":
        return "lightest" if i == 0 else None
    return "deepest" if i == len(ids) - 1 else None


def resolve_edit(recipe: dict, zone: str, op: str) -> list[str]:
    """The edit as it is stored and recorded: Lighter / Deeper are the neighbour circle (the same render)."""
    reason = blocked(recipe, zone, op)
    if reason and reason != "current":
        raise ValueError(f"{zone}/{op}: {reason}")
    if op in ("lighter", "deeper"):
        ids = _ladder_ids(recipe, zone)
        i = ids.index(recipe["zones"][zone]["shade_id"])
        return [zone, SHADE_PREFIX + ids[i - 1 if op == "lighter" else i + 1]]
    return [zone, op]


def apply_edit(recipe: dict, zone: str, op: str) -> dict:
    zone, op = resolve_edit(recipe, zone, op)
    if zone == LOOK_ZONE:
        return look_recipe(recipe["group"], op)
    out = copy.deepcopy(recipe)
    z = out["zones"][zone]
    if op.startswith(SHADE_PREFIX):
        s = palettes.shade(recipe["group"], zone, op.removeprefix(SHADE_PREFIX))
        z.update(shade_id=s.id, shade_name=s.name, palette=list(s.colors), texture=s.texture)
    else:
        step = palettes.INTENSITY_STEP[zone]
        z["intensity"] += step if op == "bolder" else -step
    return out


def apply_edits(recipe: dict, edits: list[list[str]]) -> dict:
    for zone, op in edits:
        recipe = apply_edit(recipe, zone, op)
    return recipe


def add_edit(base: dict, edits: list[list[str]], zone: str, op: str) -> list[list[str]]:
    """The edit list after one more resolved edit: a look replaces everything (the base look means no edits), a zone
    holds one shade, and a shade equal to where the zone started is no edit at all."""
    if zone == LOOK_ZONE:
        return [] if op == base["look"] else [[zone, op]]
    if not op.startswith(SHADE_PREFIX):
        return [*edits, [zone, op]]
    kept = [e for e in edits if not (e[0] == zone and e[1].startswith(SHADE_PREFIX))]
    start = apply_edits(base, kept)["zones"][zone]["shade_id"]
    return kept if op == SHADE_PREFIX + start else [*kept, [zone, op]]


def edit_key(edits: list[list[str]]) -> str:
    """Stable key for a list of edits (used to look up recorded renders in Replay)."""
    if not edits:
        return "base"
    return "+".join(f"{z}:{o}" for z, o in edits)


def record_grid(base: dict) -> list[list[list[str]]]:
    """Every single change a sample records over its base render: all circles but the selected one, Softer / Bolder
    where they are not on the edge, the other looks. Lighter / Deeper need no render of their own."""
    group = base["group"]
    grid = [[[z, SHADE_PREFIX + s.id]] for z, zl in base["zones"].items() for s in palettes.ladder(group, z)
            if s.id != zl["shade_id"]]
    grid += [[[z, op]] for z in base["zones"] for op in ("softer", "bolder") if not blocked(base, z, op)]
    grid += [[[LOOK_ZONE, look]] for look in palettes.LOOK_IDS if look != base["look"]]
    return grid


def _palettes(z: dict) -> list[dict]:
    cat, i, color = z["category"], z["intensity"], z["palette"][0]
    if cat == "eye_shadow":
        lid = {"color": color, "texture": "matte", "colorIntensity": i}
        if z["texture"] == "shimmer":
            lid = {"color": color, "texture": "shimmer", "shimmerColor": color, "shimmerIntensity": z["shimmer"],
                   "colorIntensity": i}
        return [lid, {"color": z["palette"][1], "texture": "matte", "colorIntensity": i + z["crease_offset"]}]
    if cat in ("eyelashes", "bronzer"):
        return [{"color": color, "colorIntensity": i}]
    if cat == "blush":
        return [{"color": color, "texture": z["texture"], "glowStrength": z["glow"], "colorIntensity": i}]
    if cat == "highlighter":
        return [{"color": color, **HIGHLIGHT_FINISH, "colorIntensity": i}]
    if cat == "lip_color":
        finish = SHEER_FINISH if z["texture"] == "sheer" else {}
        return [{"color": color, "texture": z["texture"], "colorIntensity": i, **finish}]
    if cat == "lip_liner":
        return [{"color": color, "texture": z["texture"], "colorIntensity": i, **LIP_LINE_FINISH}]
    return [{"color": color, "texture": z["texture"], "colorIntensity": i}]  # eye_liner, eyebrows


def _effect(z: dict) -> dict:
    pals = _palettes(z)
    if z["category"] == "lip_color":  # without `style` the API answers 400 (oneOf of 7 variants)
        return {"category": "lip_color", "shape": {"name": z["pattern"]}, "style": {"type": "full"}, "palettes": pals}
    if z["category"] == "eyebrows":  # her own brow shape, pigment only
        return {"category": "eyebrows", "pattern": {"type": z["pattern"]}, "palettes": pals}
    return {"category": z["category"], "pattern": {"name": z["pattern"]}, "palettes": pals}


def to_vto_effects(recipe: dict, even_out: dict | None = None) -> list[dict]:
    """Recipe -> `effects` for POST /s2s/v2.0/task/makeup-vto (schema: makeup_vto.yaml).

    `even_out` ({"skin_hex", "coverage"}): once the bride has the "Even out redness" step, every re-render carries
    the same foundation in her shade under the recipe, so an edit never brings the redness back."""
    effects: list[dict] = [dict(NO_SMOOTHING)]
    if even_out:
        effects.append(foundation_effect(even_out["skin_hex"], int(even_out.get("coverage", 30))))
    effects += [_effect(recipe["zones"][z]) for z in palettes.ZONES if z in recipe["zones"]]
    return effects


EVEN_OUT_LABEL = "foundation in her shade over the transfer"


def foundation_effect(skin_hex: str, coverage: int = 30) -> dict:
    return {"category": "foundation", "palettes": [
        {"color": skin_hex, "colorIntensity": FOUNDATION_INTENSITY, "glowIntensity": FOUNDATION_GLOW,
         "coverageIntensity": int(coverage)}]}


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
    """What the artist confirms: one line per zone with the product shade to bring to the trial. `on_face_hex` and
    `coverage` exist only for the zones the makeup map measures (eyes, cheeks, lips)."""
    rows = []
    for name, z in recipe["zones"].items():
        zs = m.zones.get(name)
        rows.append({
            "zone": name,
            "label": palettes.ZONE_LABELS[name],
            "category": z["category"],
            "shade_id": z["shade_id"],
            "shade_name": z["shade_name"],
            "palette": z["palette"],
            "texture": z["texture"],
            "pattern": z["pattern"],
            "product_hex": z["palette"][0],
            "intensity": z["intensity"],
            "on_face_hex": zs.color_after if zs else None,
            "coverage": zs.coverage if zs else None,
        })
    return rows
