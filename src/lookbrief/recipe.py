"""A look on nine zones -> an editable AI Makeup VTO recipe, and the edits a bride or artist can ask for.

The recipe comes from the palette (lookbrief.palettes), not from the transfer: the look sets every zone, and on a live
photo the inspiration picks the colour family of lips, cheeks and lids from the ladder. An edit picks another shade of
the palette, so no path can send a colour of its own: on lids, cheeks and lips Softer and Bolder step to the next shade
of the same colour family closer to her skin or further from it (strength alone barely moves a render: dE2000 0.6-1.3
for +-10, probe of 2026-10-31); in the thin zones the named styles are the choice.
How far the re-render lands from the transfer is measured per zone (makeup_map.compare); the recipe is not fitted to it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import numpy as np

from . import palettes
from .color import hex_to_lab
from .makeup_map import MakeupMap

RECIPE_VERSION = 2
EDIT_OPS = ("softer", "bolder")
EDIT_ZONES = tuple(palettes.ZONES)
EDIT_LABELS = {"softer": "softer", "bolder": "bolder"}
BLOCK_NOTES = {  # why a button is off
    "softest": "This is the softest shade in your palette.",
    "boldest": "This is the boldest shade in your palette.",
    "current": "",
    "not_recorded": "This change isn't in the recorded set.",
    "quiet": "This change would not show on the photo.",
}
SHADE_PREFIX = "shade:"
LOOK_ZONE = "look"  # an edit ["look", "evening"] swaps the whole recipe
TONE_ZONES = ("lips", "cheeks", "eyes")  # the zones whose shade follows the inspiration on a live photo
MIN_CHANGED_PX = 200  # fewer changed pixels: the transfer says nothing about this zone
TONE_WEIGHTS = np.array([0.25, 1.0, 1.0])  # L*, a*, b*

NO_SMOOTHING = {"category": "skin_smooth", "skinSmoothStrength": 0, "skinSmoothColorIntensity": 0}
# Finish numbers accepted by the API in the probes of 2026-10-31 (the same in every look).
LIP_FINISH = {"sheer": {"gloss": 45, "transparencyIntensity": 30}}  # texture gloss leaves drops of shine: not used
LIP_LINE_FINISH = {"thickness": 30, "smoothness": 70}
FOUNDATION_INTENSITY = 40  # 50 lifted the heroine's forehead L* by 1.7; the target is 1.5 at most
FOUNDATION_GLOW = 20


def _zone(group: str, zone: str, spec: palettes.ZoneLook, shade_id: str | None = None) -> dict:
    s = palettes.shade(group, zone, shade_id or spec.shade)
    pattern = spec.pattern or s.pattern or palettes.ZONE_PATTERNS.get(zone, "")
    z = {"category": palettes.ZONES[zone], "shade_id": s.id, "shade_name": s.name, "palette": list(s.colors),
         "texture": s.texture, "pattern": pattern, "intensity": spec.intensity}
    if zone == "eyes":
        z |= {"slot_intensity": list(spec.slots), "shimmer": list(spec.shimmer)}
    elif zone == "highlight":
        z["glow"] = dict(palettes.HIGHLIGHT_GLOW_MEDIUM if group == "medium" else palettes.HIGHLIGHT_GLOW)
    elif zone == "cheeks":
        z["glow"] = spec.glow
    return z


def look_recipe(group: str, look: str, skin_hex: str, shades: dict[str, str] | None = None) -> dict:
    """The look as it stands on the palette; `shades` swaps single zones ({zone: shade id}). `skin_hex`: her skin,
    the point Softer and Bolder measure from."""
    if group not in palettes.GROUPS or look not in palettes.LOOK_IDS:
        raise ValueError(f"unknown look {group}/{look}")
    picks = shades or {}
    spec = palettes.LOOKS[group][look]
    if set(picks) - set(spec):
        raise ValueError(f"the {look} look has no zones {sorted(set(picks) - set(spec))}")
    zones = {z: _zone(group, z, zl, picks.get(z)) for z, zl in spec.items()}
    under = palettes.LIP_LINE_UNDER.get(picks.get("lips", ""))
    if under and "lip_line" not in picks:  # a red lip takes the liner under it
        zones["lip_line"] = _zone(group, "lip_line", replace(spec["lip_line"], intensity=under[1]), under[0])
    return {"version": RECIPE_VERSION, "group": group, "look": look, "skin_hex": skin_hex, "zones": zones}


def _nearest_tone(group: str, zone: str, color: str) -> str:
    """The ladder step closest to a colour: hue and chroma decide the family (a transfer lands lighter or darker than
    the product), lightness counts a quarter, enough to tell a ruby from a coral of the same hue."""
    target = hex_to_lab(color) * TONE_WEIGHTS

    def distance(s: palettes.Shade) -> float:
        return float(np.linalg.norm(hex_to_lab(s.main) * TONE_WEIGHTS - target))

    return min(palettes.ladder(group, zone), key=distance).id


def base_recipe(m: MakeupMap | None, group: str, skin_hex: str, look: str = palettes.DEFAULT_LOOK,
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
    return look_recipe(group, look, skin_hex, {**picks, **(shades or {})})


def _check(recipe: dict, zone: object, op: object) -> None:
    if not isinstance(op, str):
        raise ValueError(f"unknown edit {zone}/{op}")
    if zone == LOOK_ZONE:
        if op not in palettes.LOOK_IDS:
            raise ValueError(f"unknown look {op}")
        return
    if zone not in EDIT_ZONES or not ((op in EDIT_OPS and zone in palettes.STEP_ZONES) or op.startswith(SHADE_PREFIX)):
        raise ValueError(f"unknown edit {zone}/{op}")
    if zone not in recipe["zones"]:
        raise ValueError(f"zone {zone} is not in this look")
    if op.startswith(SHADE_PREFIX):
        s = palettes.shade(recipe["group"], str(zone), op.removeprefix(SHADE_PREFIX))
        if not any(c.id == s.id for c in palettes.circles(recipe["group"], str(zone))):
            raise ValueError(f"{s.id} is not a choice")


def _step(recipe: dict, zone: str, op: str) -> str | None:
    return palettes.step_from(recipe["group"], zone, recipe["skin_hex"], recipe["zones"][zone]["shade_id"], op)


def blocked(recipe: dict, zone: str, op: str) -> str | None:
    """Why this edit cannot be made now (a key of BLOCK_NOTES), or None. An unknown edit raises ValueError."""
    _check(recipe, zone, op)
    if zone == LOOK_ZONE:
        return "current" if op == recipe["look"] else None
    z = recipe["zones"][zone]
    if op.startswith(SHADE_PREFIX):
        return "current" if op.removeprefix(SHADE_PREFIX) == z["shade_id"] else None
    if _step(recipe, zone, op) is None:
        return "softest" if op == "softer" else "boldest"
    return None


def resolve_edit(recipe: dict, zone: str, op: str) -> list[str]:
    """The edit as it is stored and recorded: Softer / Bolder are the neighbour circle (the same render)."""
    reason = blocked(recipe, zone, op)
    if reason and reason != "current":
        raise ValueError(f"{zone}/{op}: {reason}")
    if op in EDIT_OPS and zone != LOOK_ZONE:
        return [zone, f"{SHADE_PREFIX}{_step(recipe, zone, op)}"]
    return [zone, op]


def apply_edit(recipe: dict, zone: str, op: str) -> dict:
    zone, op = resolve_edit(recipe, zone, op)
    if zone == LOOK_ZONE:
        return look_recipe(recipe["group"], op, recipe["skin_hex"])
    out = copy.deepcopy(recipe)
    z = out["zones"][zone]
    s = palettes.shade(recipe["group"], zone, op.removeprefix(SHADE_PREFIX))
    z.update(shade_id=s.id, shade_name=s.name, palette=list(s.colors), texture=s.texture)
    if s.intensity is not None:
        z["intensity"] = s.intensity
    if s.pattern:
        z["pattern"] = s.pattern
    if zone == "eyes":  # every circle of the lids carries the strengths of the base look
        slots, shimmer = palettes.EYE_SLOTS[recipe["group"]]
        z |= {"slot_intensity": list(slots), "shimmer": list(shimmer), "intensity": slots[0]}
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
    kept = [e for e in edits if e[0] != zone]
    start = SHADE_PREFIX + apply_edits(base, kept)["zones"][zone]["shade_id"]
    return kept if op == start else [*kept, [zone, op]]


def edit_key(edits: list[list[str]]) -> str:
    """Stable key for a list of edits (used to look up recorded renders in Replay)."""
    if not edits:
        return "base"
    return "+".join(f"{z}:{o}" for z, o in edits)


def quiet_key(recipe: dict, zone: str, op: str) -> str:
    """The key of a button in a sample's `quiet_edits`. Softer / Bolder are a step between two shades, so theirs names
    the shade she wears: from another shade it is another step."""
    if op in EDIT_OPS:
        return f"{zone}:{op}@{recipe['zones'][zone]['shade_id']}"
    return edit_key([[zone, op]])


def record_grid(base: dict) -> list[list[list[str]]]:
    """Every single change a sample records over its base render: all circles and styles but the selected one, the
    other looks. Softer / Bolder need no render of their own."""
    group = base["group"]
    grid = [[[z, SHADE_PREFIX + s.id]] for z, zl in base["zones"].items() for s in palettes.circles(group, z)
            if s.id != zl["shade_id"]]
    grid += [[[LOOK_ZONE, look]] for look in palettes.LOOK_IDS if look != base["look"]]
    return grid


def _eye_slot(color: str, texture: str, strength: int, shimmer: int) -> dict:
    if shimmer and texture == "metallic":
        return {"color": color, "texture": "metallic", "shimmerColor": color, "shimmerIntensity": shimmer,
                "metallicIntensity": shimmer, "colorIntensity": strength}
    if shimmer and texture == "shimmer":
        return {"color": color, "texture": "shimmer", "shimmerColor": color, "shimmerIntensity": shimmer,
                "colorIntensity": strength}
    return {"color": color, "texture": "matte", "colorIntensity": strength}


def _palettes(z: dict) -> list[dict]:
    cat, i, color = z["category"], z["intensity"], z["palette"][0]
    if cat == "eye_shadow":
        return [_eye_slot(c, z["texture"], strength, shimmer)
                for c, strength, shimmer in zip(z["palette"], z["slot_intensity"], z["shimmer"], strict=True)]
    if cat in ("eyelashes", "bronzer"):
        return [{"color": color, "colorIntensity": i}]
    if cat == "blush":
        return [{"color": color, "texture": z["texture"], "glowStrength": z["glow"], "colorIntensity": i}]
    if cat == "highlighter":
        return [{"color": color, **z["glow"], "colorIntensity": i}]
    if cat == "lip_color":
        return [{"color": color, "texture": z["texture"], "colorIntensity": i, **LIP_FINISH.get(z["texture"], {})}]
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
    effects.append(concealer_effect(recipe["skin_hex"]))
    zones = recipe["zones"]
    effects += [_effect(zones[z]) for z in palettes.ZONES if z in zones and zones[z]["palette"]]  # "none": left out
    return effects


EVEN_OUT_LABEL = "foundation in her shade over the transfer"


def foundation_effect(skin_hex: str, coverage: int = 30) -> dict:
    return {"category": "foundation", "palettes": [
        {"color": skin_hex, "colorIntensity": FOUNDATION_INTENSITY, "glowIntensity": FOUNDATION_GLOW,
         "coverageIntensity": int(coverage)}]}


def concealer_effect(skin_hex: str) -> dict:
    """A layer under every look, not a zone: nothing to choose, the artist reads it in the Skin row of the brief."""
    return {"category": "concealer", "palettes": [{"color": skin_hex, **palettes.CONCEALER_FINISH}]}


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
        if not z["palette"]:  # the bride left this product out
            continue
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
