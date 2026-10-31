"""The palette: skin groups, nine zones, ladders of shades, three looks per group.

Every colour the app can send to Makeup VTO is a shade here: an edit picks another shade, it never computes a colour.
All hex values are ours (from wording in beauty sources), except the looks of the light and deep groups: those are the
request bodies the API accepted on 2026-10-31, and the critic and the client approved by eye
(tests/fixtures/approved_looks.json; ladders: PALETTE-V3 of the project docs). The medium and olive groups are built the
same way and have not been rendered on a real face yet.

A zone is a ladder of colours (eyes, cheeks, lips: circles, Softer and Bolder) or a few styles with a name (liner,
lashes, brows, highlighter, lip liner: a style brings its own pattern and strength). Bronzer has no choice: a light
layer that is part of the look. `LOOK_SHADES` hold what only an approved look wears: never a circle, never a target of
Softer or Bolder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .color import hex_delta_e2000, hex_to_lab, lab_to_hex

GROUPS = ("light", "medium", "olive", "deep")
ZONES = {  # zone -> Makeup VTO category, in the order of the request body
    "eyes": "eye_shadow",
    "liner": "eye_liner",
    "lashes": "eyelashes",
    "brows": "eyebrows",
    "cheeks": "blush",
    "bronzer": "bronzer",
    "highlight": "highlighter",
    "lips": "lip_color",
    "lip_line": "lip_liner",
}
ZONE_LABELS = {"eyes": "Eyelids", "liner": "Eyeliner", "lashes": "Lashes", "brows": "Brows", "cheeks": "Cheeks",
               "bronzer": "Bronzer", "highlight": "Highlighter", "lips": "Lips", "lip_line": "Lip liner"}
ZONE_GROUPS = (("Eyes", ("eyes", "liner", "lashes", "brows")), ("Face", ("cheeks", "bronzer", "highlight")),
               ("Lips", ("lips", "lip_line")))
LOOK_IDS = ("softglam", "fresh", "evening")
LOOK_LABELS = {"softglam": "Soft glam", "fresh": "Fresh", "evening": "Evening"}
DEFAULT_LOOK = "softglam"

# Skin group from the forehead (cheeks read too red to use: s0 17.5, s3 16.0). A heuristic fitted on four faces only:
# ITA s0 43.9, s1 56.1, s2 55.7, s3 22.8. The hue threshold has no face behind it yet.
LIGHT_MIN_ITA = 40.0
DEEP_BELOW_ITA = 28.0
OLIVE_MIN_HUE = 60.0  # h* of the forehead; above this the middle band reads yellow-green, not rosy

STEP_ZONES = ("eyes", "cheeks", "lips")  # Softer and Bolder live here; elsewhere the named styles are the choice
STYLE_ZONES = ("liner", "lashes", "brows", "highlight", "lip_line")
FIXED_ZONES = {"bronzer": "A light warm layer is part of this look."}  # no choice: the zone says why
NONE_ZONES = ("highlight", "lip_line")  # the product can be left out (elsewhere it would not show, or not truly go)
NONE_ID = "none"
# Softer / Bolder stay in the colour family: the raw order of distance to her skin jumped from berry rose to fuchsia.
FAMILY_HUE = 30.0  # the next shade differs by at most this much of hue h* ...
FAMILY_CHROMA_RISE = 15.0  # ... and gains at most this much chroma C*
NEUTRAL_CHROMA = 6.0  # below this a colour has no hue to keep

# Concealer: a layer under every look, not a zone. Its colour is her skin 4 L* lighter; the two faces of the approved
# looks keep the colours measured on them.
CONCEALER_LIFT_L = 4.0
CONCEALER_FINISH = {"colorIntensity": 55, "colorUnderEyeIntensity": 85, "coverageLevel": 70}
CONCEALER_FINISH_DEEP = {"colorIntensity": 45, "colorUnderEyeIntensity": 55, "coverageLevel": 45}
CONCEALER_MEASURED = {"#dfa588": "#E8B79C", "#be8567": "#C88F6E"}
# A red lip takes the lip liner under it: shade of the lips -> (lip liner, strength).
LIP_LINE_UNDER = {"ruby": ("red", 45)}
# Strength and shimmer of the two lid colours (lid, outer corner) on the ladder shades.
EYE_SLOTS = {"light": ((92, 88), (70, 0)), "medium": ((93, 89), (74, 0)), "olive": ((94, 89), (76, 0)),
             "deep": ((95, 90), (80, 0))}
EYE_PATTERN = "2colors279"
LASH_COLOR = "#17110f"
ZONE_PATTERNS = {"eyes": EYE_PATTERN, "brows": "color", "bronzer": "Bronzer1", "highlight": "OvalFace28",
                 "lips": "original", "lip_line": "Natural1"}


@dataclass(frozen=True)
class Shade:
    id: str  # ends up in render file names: lowercase letters, digits, hyphens
    name: str
    colors: tuple[str, ...]  # eyes: lid, outer corner; other zones: one colour; "none": no colour
    texture: str = "matte"  # "" where the API has no texture field (lashes, bronzer, highlighter)
    intensity: int | None = None  # the strength this shade brings; None: the look keeps its own
    pattern: str = ""  # the pattern this shade brings; "": the zone's
    step: bool = True  # False: a circle of its own, never where Softer or Bolder lands

    @property
    def main(self) -> str:
        """The colour that reads on the face: the lid colour of an eye shade, else the only colour."""
        return self.colors[0]


@dataclass(frozen=True)
class ZoneLook:
    shade: str
    intensity: int
    pattern: str = ""  # "": the pattern of the shade or the zone
    slots: tuple[int, ...] = ()  # eyes: strength of each colour
    shimmer: tuple[int, ...] = ()  # eyes: shimmer of each colour
    glow: int = 0  # cheeks: glowStrength of the satin finish


def shade_lightness(s: Shade) -> float:
    return float(hex_to_lab(s.main)[0])


def _ladder(*shades: Shade) -> tuple[Shade, ...]:
    return tuple(sorted(shades, key=shade_lightness, reverse=True))


def _eye(id_: str, name: str, lid: str, corner: str, texture: str = "shimmer") -> Shade:
    return Shade(id_, name, (lid, corner), texture)


def _blush(id_: str, name: str, color: str, intensity: int | None = None) -> Shade:
    return Shade(id_, name, (color,), "satin", intensity)


def _lip(id_: str, name: str, color: str, texture: str = "satin") -> Shade:
    return Shade(id_, name, (color,), texture)


def _gloss(id_: str, name: str, color: str) -> Shade:
    return Shade(id_, name, (color,), "sheer", step=False)


def _style(id_: str, name: str, color: str, intensity: int | None = None, pattern: str = "") -> Shade:
    return Shade(id_, name, (color,), "matte", intensity, pattern)


def _bare(id_: str, name: str, color: str, intensity: int | None = None, pattern: str = "") -> Shade:
    return Shade(id_, name, (color,), "", intensity, pattern)


def _lashes(natural: int, fluttery: int, volume: int) -> tuple[Shade, ...]:
    return (_bare("natural", "Natural", LASH_COLOR, natural, "Natural17"),
            _bare("fluttery", "Fluttery", LASH_COLOR, fluttery, "Natural145"),
            _bare("volume", "Volume", LASH_COLOR, volume, "UpperDense1"))


def _liner(classic: tuple[str, int], flick: tuple[str, int], wing: tuple[str, int]) -> tuple[Shade, ...]:
    return (_style("classic", "Classic", *classic, "Upper1"), _style("flick", "Flick", *flick, "Upper246"),
            _style("wing", "Wing", *wing, "Upper4"))


LADDERS: dict[str, dict[str, tuple[Shade, ...]]] = {
    "light": {
        "eyes": _ladder(
            _eye("rose-gold", "Rose gold", "#B9745F", "#5C342A"),
            _eye("champagne", "Champagne", "#D9B080", "#7A5240", "metallic"),
            _eye("bronze", "Bronze", "#A8683F", "#4A2A1E", "metallic"),
            _eye("plum", "Plum", "#8A5570", "#3F2430"),
            _eye("chocolate", "Chocolate", "#7A5040", "#2F1C16", "matte"),
            _eye("warm-taupe", "Warm taupe", "#A88670", "#4F3A30", "matte")),
        "liner": _liner(("#2B1B17", 60), ("#2B1B17", 68), ("#2B1B17", 76)),
        "lashes": _lashes(75, 80, 80),
        "brows": (_style("natural", "Natural", "#5A4034", 35), _style("soft", "Soft", "#8A6A5C", 18),
                  _style("defined", "Defined", "#3B2A22", 85)),
        "cheeks": _ladder(
            _blush("muted-rose", "Muted rose", "#D58C95", 36),
            _blush("peach", "Peach", "#EE8F6A", 50),
            _blush("terracotta", "Terracotta", "#C8603C", 50),
            _blush("rose", "Rose", "#DE6A72", 46),
            _blush("plum-rose", "Plum rose", "#A84868", 44)),
        "bronzer": (_bare("natural", "Natural", "#C08A55", 20),),
        "highlight": (_bare("natural", "Natural", "#F3E3D0", 40), _bare("radiant", "Radiant", "#F3D3B5", 78)),
        "lips": _ladder(
            _lip("dusty-rose", "Dusty rose", "#B96F78"),
            _lip("light-pink", "Light pink", "#E8A0A8", "sheer"),
            _lip("peach-pink", "Peach pink", "#E9A08C", "sheer"),
            _lip("rosy-peach", "Rosy peach", "#D98C86", "sheer"),
            _lip("nude-rose", "Nude rose", "#B9766F"),
            _lip("warm-coral", "Warm coral", "#D9705F"),
            _lip("warm-rose", "Warm rose", "#B0605C"),
            _lip("raspberry", "Raspberry", "#B03050"),
            _lip("ruby", "Ruby", "#B0102E", "matte"),
            _gloss("rose-gloss", "Rose gloss", "#B96F78")),
        "lip_line": (_style("natural", "Natural", "#A63A50", 40), _style("defined", "Defined", "#A85A62", 55)),
    },
    "medium": {
        "eyes": _ladder(
            _eye("rose-gold", "Rose gold", "#B8705C", "#5C342A"),
            _eye("champagne", "Champagne", "#D4A87C", "#7A5240", "metallic"),
            _eye("bronze", "Bronze", "#A8613A", "#3F2620", "metallic"),
            _eye("plum", "Plum", "#6E4A5E", "#3F2430"),
            _eye("chocolate", "Chocolate", "#6E4A38", "#2B1B17", "matte"),
            _eye("warm-taupe", "Warm taupe", "#9C7B6B", "#4A2F27", "matte")),
        "liner": _liner(("#2B1B17", 64), ("#2B1B17", 70), ("#2B1B17", 78)),
        "lashes": _lashes(78, 82, 82),
        "brows": (_style("natural", "Natural", "#5A4034", 36), _style("soft", "Soft", "#7A5C52", 20),
                  _style("defined", "Defined", "#3B2F2F", 85)),
        "cheeks": _ladder(
            _blush("muted-rose", "Muted rose", "#C97C84", 40),
            _blush("warm-peach", "Warm peach", "#F2A27E", 50),
            _blush("radiant-coral", "Radiant coral", "#F08A6E", 48),
            _blush("warm-pink", "Warm pink", "#E27A8A", 46),
            _blush("warm-berry", "Warm berry", "#B04A5E", 44)),
        "bronzer": (_bare("natural", "Natural", "#B97A4C", 21),),
        "highlight": (_bare("natural", "Natural", "#E5BE8A", 41), _bare("radiant", "Radiant", "#F0CFA8", 70)),
        "lips": _ladder(
            _lip("rose-brown", "Rose brown", "#A5685E"),
            _lip("warm-nude", "Warm nude", "#B9776E"),
            _lip("coral-rose", "Coral rose", "#C8736B", "sheer"),
            _lip("cool-brown", "Cool brown", "#8D5F58"),
            _lip("dusty-mauve", "Dusty mauve", "#A8697A"),
            _lip("warm-coral", "Warm coral", "#D9705F"),
            _lip("raspberry", "Raspberry", "#B03050"),
            _lip("ruby", "Ruby", "#B0102E", "matte"),
            _lip("wine", "Wine", "#6A1B2C", "matte"),
            _gloss("rose-gloss", "Rose gloss", "#A5685E")),
        "lip_line": (_style("natural", "Natural", "#A63A50", 46), _style("defined", "Defined", "#A85A62", 58)),
    },
    "olive": {
        "eyes": _ladder(
            _eye("copper-rose", "Copper rose", "#B8705A", "#5C342A"),
            _eye("warm-gold", "Warm gold", "#C9A24A", "#6E4A28", "metallic"),
            _eye("bronze", "Bronze", "#A8683F", "#3F2620", "metallic"),
            _eye("plum", "Plum", "#5E3F48", "#2F1710"),
            _eye("burgundy", "Burgundy", "#6E1A2E", "#2F1710", "matte"),
            _eye("chocolate", "Chocolate", "#4A2F27", "#2B1B17", "matte")),
        "liner": _liner(("#2B1B17", 66), ("#2B1B17", 72), ("#2B1B17", 78)),
        "lashes": _lashes(78, 82, 82),
        "brows": (_style("natural", "Natural", "#3B2F2F", 36), _style("soft", "Soft", "#5A4034", 20),
                  _style("defined", "Defined", "#33241E", 85)),
        "cheeks": _ladder(
            _blush("burnt-rose", "Burnt rose", "#B06A68", 40),
            _blush("peach-terracotta", "Peach terracotta", "#D9805E", 50),
            _blush("coral", "Coral", "#F08060", 48),
            _blush("bronzed-terracotta", "Bronzed terracotta", "#B8663E", 44),
            _blush("warm-berry", "Warm berry", "#B04A5E", 44)),
        "bronzer": (_bare("natural", "Natural", "#A8683F", 21),),
        "highlight": (_bare("natural", "Natural", "#E5BE8A", 41), _bare("radiant", "Radiant", "#D9A066", 70)),
        "lips": _ladder(
            _lip("rose-brown", "Rose brown", "#A5685E"),
            _lip("peach", "Peach", "#E8967E", "sheer"),
            _lip("peach-nude", "Peach nude", "#C4806B"),
            _lip("coral-rose", "Coral rose", "#C8736B"),
            _lip("brick", "Brick", "#A8412F", "matte"),
            _lip("warm-red", "Warm red", "#A8281B", "matte"),
            _lip("plum", "Plum", "#6E2A3E"),
            _lip("oxblood", "Oxblood", "#7A0F1E", "matte"),
            _gloss("rose-gloss", "Rose gloss", "#A5685E")),
        "lip_line": (_style("natural", "Natural", "#6A1B2C", 46), _style("defined", "Defined", "#5A2A2E", 66)),
    },
    "deep": {
        "eyes": _ladder(
            _eye("gold", "Gold", "#C9A050", "#3F1F14"),
            _eye("copper", "Copper", "#B5653D", "#3A1C12", "metallic"),
            _eye("bronze", "Bronze", "#8A5A36", "#2F1710"),
            _eye("plum", "Plum", "#6E2A4A", "#2A1220"),
            _eye("burgundy", "Burgundy", "#6E1A2E", "#2A0E14", "matte"),
            _eye("emerald", "Emerald", "#0F6B4A", "#0E2A20")),
        "liner": _liner(("#120c0a", 70), ("#17110f", 74), ("#17110f", 80)),
        "lashes": _lashes(80, 84, 84),
        "brows": (_style("natural", "Natural", "#33241E", 40), _style("soft", "Soft", "#3B2F2F", 22),
                  _style("defined", "Defined", "#2B1B17", 82)),
        # warm deep shades only: pinks and berries turn to mud (probes r1, v3), orange and loud reds are out
        "cheeks": _ladder(
            _blush("mulled-rose", "Mulled rose", "#8E3A3C", 36),
            _blush("terracotta-rose", "Terracotta rose", "#A8553F", 54),
            _blush("warm-berry", "Warm berry", "#8C3A4A", 50),
            _blush("plum-wine", "Plum wine", "#6E2A3A", 50)),
        "bronzer": (_bare("natural", "Natural", "#8A5230", 22),),
        "highlight": (_bare("natural", "Natural", "#E3B98C", 42), _bare("radiant", "Radiant", "#D9A066", 66)),
        "lips": _ladder(
            _lip("berry-rose", "Berry rose", "#8A2F45"),
            _lip("caramel-nude", "Caramel nude", "#A8645A"),
            _lip("bronze", "Bronze", "#9C5B3A"),
            _lip("brick", "Brick", "#A8412F", "matte"),
            _lip("deep-red", "Deep red", "#8E0F23", "matte"),
            _lip("plum", "Plum", "#6E2A3E"),
            _lip("oxblood", "Oxblood", "#7A0F1E", "matte"),
            _lip("dark-berry", "Dark berry", "#4A1230", "matte"),
            _gloss("berry-gloss", "Berry gloss", "#8A2F45")),
        "lip_line": (_style("natural", "Natural", "#6A1B2C", 55), _style("defined", "Defined", "#5A2A2E", 70)),
    },
}

LOOK_SHADES: dict[str, dict[str, tuple[Shade, ...]]] = {
    "light": {
        "eyes": (_eye("sunlit-taupe", "Sunlit taupe", "#D9B08C", "#8A6450"),
                 _eye("copper-umber", "Copper umber", "#A8613A", "#2F1C16")),
        "liner": (_style("taupe-brown", "Taupe brown", "#7A5C52", pattern="Upper283"),),
        "cheeks": (_blush("soft-peach", "Soft peach", "#F0A090"), _blush("deep-rose", "Deep rose", "#D0707E")),
        "lip_line": (_style("red", "Red", "#8E0F1A"), _style("ruby-line", "Ruby", "#A01028")),
    },
    "medium": {
        "eyes": (_eye("sunlit-taupe", "Sunlit taupe", "#D4A87C", "#8A6450"),
                 _eye("copper-umber", "Copper umber", "#A8613A", "#2F1C16")),
        "liner": (_style("chocolate", "Chocolate", "#4A2F27", pattern="Upper283"),),
        "bronzer": (_bare("honey", "Honey", "#C08A55"),),
        "lip_line": (_style("cool-brown", "Cool brown", "#8D5F58"), _style("red", "Red", "#8E0F1A")),
    },
    "olive": {
        "eyes": (_eye("warm-gold-taupe", "Warm gold taupe", "#C9A24A", "#8A5A3A"),
                 _eye("copper-night", "Copper night", "#A8683F", "#3F2620")),
        "liner": (_style("plum-brown", "Plum brown", "#5E3F48", pattern="Upper283"),),
        "bronzer": (_bare("amber", "Amber", "#B97A4C"),),
        "lip_line": (_style("rose-brown", "Rose brown", "#A5685E"), _style("wine", "Wine", "#6A1B2C")),
    },
    "deep": {
        "eyes": (_eye("gold-bronze", "Gold bronze", "#C9A050", "#6E4A2A"),
                 _eye("copper-night", "Copper night", "#C98A48", "#2A140E")),
        "liner": (_style("smudge", "Smudge", "#2B1B17", pattern="Upper283"),),
        "cheeks": (_blush("warm-rose", "Warm rose", "#B5535A"), _blush("dark-cherry", "Dark cherry", "#7E2A38")),
        "bronzer": (_bare("deep-bronze", "Deep bronze", "#8A4A2B"), _bare("dark-bronze", "Dark bronze", "#6B3F28")),
        "highlight": (_bare("deep-gold", "Deep gold", "#C9A24A"),),
        "lip_line": (_style("dark-berry", "Dark berry", "#4A1230"),),
    },
}


def _look(eyes: tuple[str, tuple[int, ...], tuple[int, ...]], liner: tuple[str, int], lashes: tuple[str, int],
          brows: tuple[str, int], cheeks: tuple[str, int, str, int], bronzer: tuple[str, int],
          highlight: tuple[str, int], lips: tuple[str, int], lip_line: tuple[str, int] = (NONE_ID, 0)
          ) -> dict[str, ZoneLook]:
    """eyes: (shade, strength of each colour, shimmer of each colour); cheeks: (shade, intensity, pattern, glow); other
    zones: (shade, intensity). The lid strength is the zone's `intensity`."""
    plain = {"liner": liner, "lashes": lashes, "brows": brows, "bronzer": bronzer, "highlight": highlight, "lips": lips,
             "lip_line": lip_line}
    zones = {z: ZoneLook(v[0], v[1]) for z, v in plain.items()}
    zones["eyes"] = ZoneLook(eyes[0], eyes[1][0], slots=eyes[1], shimmer=eyes[2])
    zones["cheeks"] = ZoneLook(cheeks[0], cheeks[1], pattern=cheeks[2], glow=cheeks[3])
    return {z: zones[z] for z in ZONES}


LOOKS: dict[str, dict[str, dict[str, ZoneLook]]] = {
    "light": {
        "fresh": _look(("sunlit-taupe", (70, 62), (60, 0)), ("taupe-brown", 50), ("natural", 60), ("natural", 35),
                       ("soft-peach", 30, "1color2", 30), ("natural", 20), ("natural", 40), ("rosy-peach", 55)),
        "softglam": _look(("rose-gold", (92, 88), (70, 0)), ("classic", 60), ("natural", 75), ("natural", 35),
                          ("muted-rose", 36, "1color2", 30), ("natural", 20), ("natural", 40), ("dusty-rose", 68),
                          ("natural", 40)),
        "evening": _look(("copper-umber", (94, 92), (75, 0)), ("wing", 76), ("volume", 80), ("natural", 42),
                         ("deep-rose", 40, "1color2", 30), ("natural", 26), ("natural", 45), ("ruby", 80),
                         ("ruby-line", 40)),
    },
    "medium": {
        "fresh": _look(("sunlit-taupe", (72, 64), (62, 0)), ("chocolate", 52), ("natural", 65), ("natural", 36),
                       ("warm-peach", 34, "1color2", 30), ("honey", 16), ("radiant", 36), ("coral-rose", 58),
                       ("cool-brown", 42)),
        "softglam": _look(("rose-gold", (93, 89), (74, 0)), ("classic", 64), ("natural", 78), ("natural", 36),
                          ("muted-rose", 40, "1color2", 30), ("natural", 21), ("natural", 41), ("rose-brown", 72),
                          ("natural", 46)),
        "evening": _look(("copper-umber", (94, 92), (76, 0)), ("wing", 78), ("volume", 82), ("defined", 42),
                         ("warm-berry", 42, "1color2", 30), ("natural", 26), ("natural", 45), ("ruby", 82),
                         ("red", 56)),
    },
    "olive": {
        "fresh": _look(("warm-gold-taupe", (74, 66), (62, 0)), ("plum-brown", 55), ("natural", 66), ("natural", 36),
                       ("peach-terracotta", 38, "1color2", 30), ("amber", 16), ("natural", 38), ("peach-nude", 62),
                       ("rose-brown", 44)),
        "softglam": _look(("copper-rose", (94, 89), (76, 0)), ("classic", 66), ("natural", 78), ("natural", 36),
                          ("burnt-rose", 40, "1color2", 30), ("natural", 21), ("natural", 41), ("rose-brown", 72),
                          ("natural", 46)),
        "evening": _look(("copper-night", (95, 92), (78, 0)), ("wing", 78), ("volume", 82), ("defined", 42),
                         ("warm-berry", 42, "1color2", 30), ("natural", 26), ("radiant", 45), ("warm-red", 84),
                         ("wine", 58)),
    },
    "deep": {
        "fresh": _look(("gold-bronze", (80, 70), (65, 0)), ("smudge", 60), ("natural", 70), ("soft", 30),
                       ("warm-rose", 46, "1color2", 30), ("deep-bronze", 18), ("radiant", 40), ("caramel-nude", 70),
                       ("defined", 45)),
        "softglam": _look(("gold", (95, 90), (80, 0)), ("classic", 70), ("natural", 80), ("natural", 40),
                          ("mulled-rose", 36, "1color5", 25), ("natural", 22), ("natural", 42), ("berry-rose", 76),
                          ("natural", 55)),
        "evening": _look(("copper-night", (96, 92), (80, 0)), ("wing", 80), ("volume", 84), ("defined", 42),
                         ("dark-cherry", 38, "1color5", 25), ("dark-bronze", 26), ("deep-gold", 45), ("deep-red", 86),
                         ("dark-berry", 60)),
    },
}


def ladder(group: str, zone: str) -> tuple[Shade, ...]:
    return LADDERS[group][zone]


def circles(group: str, zone: str) -> tuple[Shade, ...]:
    """What the sheet offers in a zone: the ladder, plus "none" where the product can be left out; nothing in a zone
    without a choice."""
    if zone in FIXED_ZONES:
        return ()
    if zone not in NONE_ZONES:
        return LADDERS[group][zone]
    return (*LADDERS[group][zone], Shade(NONE_ID, "None", (), ""))


def shade(group: str, zone: str, shade_id: str) -> Shade:
    for s in (*circles(group, zone), *LADDERS[group][zone], *LOOK_SHADES[group].get(zone, ())):
        if s.id == shade_id:
            return s
    raise ValueError(f"no shade {shade_id!r} for {zone} in the {group} palette")


def _distance(s: Shade, skin_hex: str) -> list[float]:
    return [float(hex_delta_e2000(c, skin_hex)) for c in s.colors]


def skin_order(group: str, zone: str, skin_hex: str) -> list[Shade]:
    """The shades of a zone from the closest to her skin to the farthest (CIEDE2000; lids: the lid colour, the corner
    breaks a tie). Softer and Bolder walk this order."""
    return sorted(LADDERS[group][zone], key=lambda s: _distance(s, skin_hex))


def same_family(color: str, other: str) -> bool:
    """Can `other` be the next step from `color`: a close hue (the short way round), and not much more vivid."""
    lab, next_lab = hex_to_lab(color), hex_to_lab(other)
    chroma, next_chroma = float(np.hypot(*lab[1:])), float(np.hypot(*next_lab[1:]))
    if next_chroma > chroma + FAMILY_CHROMA_RISE:
        return False
    if min(chroma, next_chroma) < NEUTRAL_CHROMA:
        return True
    hue = math.degrees(math.atan2(lab[2], lab[1])) - math.degrees(math.atan2(next_lab[2], next_lab[1]))
    return abs((hue + 180) % 360 - 180) <= FAMILY_HUE


def step_from(group: str, zone: str, skin_hex: str, shade_id: str, op: str) -> str | None:
    """The shade Softer / Bolder lands on from `shade_id`: the next one in the order of her skin that stays in the
    colour family and shows another colour, or None at the end of the way. A look's own shade starts from its place in
    the order and is never a target; a gloss is a circle of its own, not a step."""
    here = shade(group, zone, shade_id)
    order = skin_order(group, zone, skin_hex)
    if here not in order:
        order = sorted([*order, here], key=lambda s: _distance(s, skin_hex))
    i = order.index(here)
    way = order[i + 1:] if op == "bolder" else order[i - 1::-1] if i else []
    ladder_ids = {s.id for s in LADDERS[group][zone]}
    candidates = (s for s in way if s.id in ladder_ids and s.step and s.main != here.main
                  and same_family(here.main, s.main))
    return next((s.id for s in candidates), None)


def concealer_hex(skin_hex: str) -> str:
    measured = CONCEALER_MEASURED.get(skin_hex.lower())
    if measured:
        return measured
    lab = hex_to_lab(skin_hex)
    lab[0] += CONCEALER_LIFT_L
    return lab_to_hex(lab)


def ita(lab: NDArray[np.float64]) -> float:
    """Individual Typology Angle of a skin colour, degrees."""
    return math.degrees(math.atan2(float(lab[0]) - 50.0, float(lab[2])))


def skin_group(forehead_lab: NDArray[np.float64]) -> str:
    angle = ita(forehead_lab)
    if angle >= LIGHT_MIN_ITA:
        return "light"
    if angle < DEEP_BELOW_ITA:
        return "deep"
    hue = math.degrees(math.atan2(float(forehead_lab[2]), float(forehead_lab[1]))) % 360
    return "olive" if hue >= OLIVE_MIN_HUE else "medium"
