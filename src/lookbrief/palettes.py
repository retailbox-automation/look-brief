"""The palette: skin groups, nine zones, ladders of shades, three looks per group.

Every colour the app can send to Makeup VTO is a step of a ladder here: an edit moves to another step, it never
computes a colour. All hex values are ours (from wording in beauty sources), except
the looks of the light and deep groups: those are the request bodies the API accepted on 2026-10-31 and the client
approved by eye (tests/fixtures/approved_looks.json). The medium and olive groups are built the same way and have not
been rendered on a real face yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .color import hex_delta_e2000, hex_to_lab

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
LOOK_IDS = ("softglam", "fresh", "evening")
LOOK_LABELS = {"softglam": "Soft glam", "fresh": "Fresh", "evening": "Evening"}
DEFAULT_LOOK = "softglam"

# Skin group from the forehead (cheeks read too red to use: s0 17.5, s3 16.0). A heuristic fitted on four faces only:
# ITA s0 43.9, s1 56.1, s2 55.7, s3 22.8. The hue threshold has no face behind it yet.
LIGHT_MIN_ITA = 40.0
DEEP_BELOW_ITA = 28.0
OLIVE_MIN_HUE = 60.0  # h* of the forehead; above this the middle band reads yellow-green, not rosy

# Few steps on a thin line of product: a step differs in colour and in strength, and the product can be left out.
THIN_ZONES = ("bronzer", "highlight", "liner", "lip_line")
NONE_ID = "none"


@dataclass(frozen=True)
class Shade:
    id: str  # ends up in render file names: lowercase letters, digits, hyphens
    name: str
    colors: tuple[str, ...]  # eyes: lid, crease; other zones: one colour; the "none" circle: no colour
    texture: str = "matte"  # "" where the API has no texture field (lashes, bronzer, highlighter)
    intensity: int | None = None  # thin zones: the strength this step brings; else the look keeps its own


@dataclass(frozen=True)
class ZoneLook:
    shade: str
    intensity: int
    pattern: str
    shimmer: int = 0  # eyes: shimmer of the lid colour
    crease_offset: int = 0  # eyes: intensity of the crease colour relative to the lid
    glow: int = 0  # cheeks: glowStrength of the satin finish


def shade_lightness(s: Shade) -> float:
    return float(np.mean([hex_to_lab(c)[0] for c in s.colors]))


def _s(id_: str, name: str, *colors: str, texture: str = "matte", intensity: int | None = None) -> Shade:
    return Shade(id_, name, colors, texture, intensity)


def _sheer(id_: str, name: str, color: str) -> Shade:
    return _s(id_, name, color, texture="sheer")


def _satin(id_: str, name: str, color: str) -> Shade:
    return _s(id_, name, color, texture="satin")


def _shimmer(id_: str, name: str, lid: str, crease: str) -> Shade:
    return _s(id_, name, lid, crease, texture="shimmer")


def _bare(id_: str, name: str, color: str, intensity: int | None = None) -> Shade:
    return _s(id_, name, color, texture="", intensity=intensity)


def _ladder(*shades: Shade) -> tuple[Shade, ...]:
    return tuple(sorted(shades, key=shade_lightness, reverse=True))


_NONE = Shade(NONE_ID, "None", (), "")
_LASHES = _ladder(_bare("soft-brown", "Soft brown", "#4A2F27"), _bare("soft-black", "Soft black", "#17110f"),
                  _bare("jet-black", "Jet black", "#000000"))
_DEEP_LASHES = _ladder(_bare("espresso", "Espresso", "#2B1B17"), _bare("soft-black", "Soft black", "#17110f"),
                       _bare("jet-black", "Jet black", "#000000"))

LADDERS: dict[str, dict[str, tuple[Shade, ...]]] = {
    "light": {
        "eyes": _ladder(
            _shimmer("champagne-taupe", "Champagne taupe", "#E6CFA8", "#9C7B6B"),
            _shimmer("peach-rose", "Peach rose", "#E8A98C", "#7D5A55"),
            _shimmer("rose-gold-smoke", "Rose gold smoke", "#C98F7E", "#5C342A"),
            _s("soft-taupe", "Soft taupe", "#A89080", "#4A2F27"),
            _shimmer("plum-haze", "Plum haze", "#8E6A80", "#4A2F27"),
            _shimmer("copper-umber", "Copper umber", "#A8613A", "#3F2620"),
            _shimmer("rose-brown", "Rose brown", "#7D5A55", "#4A2F27"),
            _s("chocolate-smoke", "Chocolate smoke", "#4A2F27", "#2B1B17")),
        "liner": _ladder(_s("taupe-brown", "Taupe brown", "#7A5C52", intensity=45),
                         _s("espresso", "Espresso", "#2B1B17", intensity=62),
                         _s("soft-black", "Soft black", "#17110f", intensity=78)),
        "lashes": _LASHES,
        "brows": _ladder(_s("soft-taupe", "Soft taupe", "#8A6A5C"), _s("smoky-taupe", "Smoky taupe", "#7A5C52"),
                         _s("brown", "Brown", "#5A4034")),
        "cheeks": _ladder(
            _satin("soft-peach", "Soft peach", "#F0A090"),
            _satin("dusty-pink", "Dusty pink", "#E19F9F"),
            _satin("rosy-beige", "Rosy beige", "#D9A394"),
            _satin("vivid-pink", "Vivid pink", "#F08CA8"),
            _satin("salmon", "Salmon", "#F08A7E"),
            _satin("muted-rose", "Muted rose", "#D58C95"),
            _satin("rose-mauve", "Rose mauve", "#C98A8A"),
            _satin("deep-rose", "Deep rose", "#D0707E")),
        "bronzer": _ladder(_bare("golden-peach", "Golden peach", "#D9A57A", 12), _bare("honey", "Honey", "#C08A55", 22),
                           _bare("amber", "Amber", "#B97A4C", 32)),
        "highlight": _ladder(_bare("pearl-champagne", "Pearl champagne", "#F3E3D0", 32),
                             _bare("pearl", "Pearl", "#EBD7CF", 44),
                             _bare("rose-gold", "Rose gold", "#E8B9A0", 56)),
        "lips": _ladder(
            _sheer("peach-pink", "Peach pink", "#E9A08C"),
            _sheer("light-pink", "Light pink", "#E8A0A8"),
            _sheer("rosy-peach", "Rosy peach", "#D98C86"),
            _satin("candy-pink", "Candy pink", "#E4719A"),
            _satin("nude-rose", "Nude rose", "#B9766F"),
            _satin("dusty-rose", "Dusty rose", "#B96F78"),
            _satin("smoky-rose", "Smoky rose", "#8E4F5E"),
            _satin("orchid-berry", "Orchid berry", "#A32A6B"),
            _s("ruby", "Ruby", "#B0102E")),
        "lip_line": _ladder(_s("cool-brown", "Cool brown", "#8D5F58", intensity=30),
                            _s("rose", "Rose", "#A63A50", intensity=45),
                            _s("red", "Red", "#8E0F1A", intensity=60)),
    },
    "medium": {
        "eyes": _ladder(
            _shimmer("champagne-taupe", "Champagne taupe", "#E6CBA8", "#9C7B6B"),
            _shimmer("gold-bronze", "Gold bronze", "#D4A94E", "#8C5A2E"),
            _shimmer("rose-gold-smoke", "Rose gold smoke", "#C98B7A", "#5C342A"),
            _s("warm-taupe", "Warm taupe", "#9C7B6B", "#4A2F27"),
            _shimmer("copper-umber", "Copper umber", "#A8613A", "#3F2620"),
            _shimmer("bronze-smoke", "Bronze smoke", "#8C5A2E", "#3F2620"),
            _shimmer("plum-smoke", "Plum smoke", "#5E3F48", "#2F1710"),
            _s("chocolate-smoke", "Chocolate smoke", "#4A2F27", "#2B1B17")),
        "liner": _ladder(_s("chocolate", "Chocolate", "#4A2F27", intensity=48),
                         _s("espresso", "Espresso", "#2B1B17", intensity=64),
                         _s("soft-black", "Soft black", "#17110f", intensity=80)),
        "lashes": _LASHES,
        "brows": _ladder(_s("smoky-taupe", "Smoky taupe", "#7A5C52"), _s("brown", "Brown", "#5A4034"),
                         _s("soft-black-brown", "Soft black brown", "#3B2F2F")),
        "cheeks": _ladder(
            _satin("golden-peach", "Golden peach", "#F0A868"),
            _satin("apricot", "Apricot", "#F0A58A"),
            _satin("warm-peach", "Warm peach", "#F2A27E"),
            _satin("peach", "Peach", "#EE9A82"),
            _satin("radiant-coral", "Radiant coral", "#F08A6E"),
            _satin("warm-pink", "Warm pink", "#E27A8A"),
            _satin("muted-rose", "Muted rose", "#C97C84"),
            _satin("warm-berry", "Warm berry", "#B04A5E")),
        "bronzer": _ladder(_bare("honey", "Honey", "#C08A55", 12), _bare("amber", "Amber", "#B97A4C", 22),
                           _bare("copper", "Copper", "#A8683F", 32)),
        "highlight": _ladder(_bare("warm-champagne", "Warm champagne", "#F0CFA8", 32),
                             _bare("gold", "Gold", "#E5BE8A", 44),
                             _bare("rose-gold", "Rose gold", "#E8B9A0", 56)),
        "lips": _ladder(
            _satin("candy-pink", "Candy pink", "#E4719A"),
            _sheer("coral-rose", "Coral rose", "#C8736B"),
            _satin("fuchsia", "Fuchsia", "#D6247F"),
            _satin("warm-nude", "Warm nude", "#B9776E"),
            _satin("rose-brown", "Rose brown", "#A5685E"),
            _satin("dusty-mauve", "Dusty mauve", "#A8697A"),
            _satin("cool-brown", "Cool brown", "#8D5F58"),
            _s("ruby", "Ruby", "#B0102E"),
            _s("wine", "Wine", "#6A1B2C")),
        "lip_line": _ladder(_s("cool-brown", "Cool brown", "#8D5F58", intensity=34),
                            _s("rose", "Rose", "#A63A50", intensity=48),
                            _s("red", "Red", "#8E0F1A", intensity=62)),
    },
    "olive": {
        "eyes": _ladder(
            _shimmer("warm-gold", "Warm gold", "#C9A24A", "#8A5A3A"),
            _shimmer("copper-rose", "Copper rose", "#B8705A", "#5C342A"),
            _shimmer("copper-bronze", "Copper bronze", "#A8683F", "#3F2620"),
            _shimmer("bronze-sepia", "Bronze sepia", "#8A5A3A", "#4A2F27"),
            _shimmer("sepia-smoke", "Sepia smoke", "#6B4730", "#2F1710"),
            _shimmer("plum-smoke", "Plum smoke", "#5E3F48", "#2F1710"),
            _shimmer("burgundy-night", "Burgundy night", "#6E1A2E", "#2F1710"),
            _s("chocolate-smoke", "Chocolate smoke", "#4A2F27", "#2B1B17")),
        "liner": _ladder(_s("plum-brown", "Plum brown", "#5E3F48", intensity=50),
                         _s("espresso", "Espresso", "#2B1B17", intensity=66),
                         _s("soft-black", "Soft black", "#17110f", intensity=82)),
        "lashes": _LASHES,
        "brows": _ladder(_s("brown", "Brown", "#5A4034"), _s("soft-black-brown", "Soft black brown", "#3B2F2F"),
                         _s("dark-brown", "Dark brown", "#33241E")),
        "cheeks": _ladder(
            _satin("amber-peach", "Amber peach", "#F0A060"),
            _satin("coral", "Coral", "#F08060"),
            _satin("peach-terracotta", "Peach terracotta", "#D9805E"),
            _satin("terracotta", "Terracotta", "#C9704F"),
            _satin("burnt-rose", "Burnt rose", "#B06A68"),
            _satin("bronzed-terracotta", "Bronzed terracotta", "#B8663E"),
            _satin("cherry-red", "Cherry red", "#D2223A"),
            _satin("warm-berry", "Warm berry", "#B04A5E")),
        "bronzer": _ladder(_bare("amber", "Amber", "#B97A4C", 12), _bare("copper", "Copper", "#A8683F", 22),
                           _bare("deep-tan", "Deep tan", "#8A5230", 32)),
        "highlight": _ladder(_bare("warm-champagne", "Warm champagne", "#F0CFA8", 32),
                             _bare("gold", "Gold", "#E5BE8A", 44),
                             _bare("gold-bronze", "Gold bronze", "#D9A066", 56)),
        "lips": _ladder(
            _sheer("peach", "Peach", "#E8967E"),
            _satin("peach-nude", "Peach nude", "#C4806B"),
            _satin("coral-rose", "Coral rose", "#C8736B"),
            _satin("fuchsia", "Fuchsia", "#D6247F"),
            _satin("rose-brown", "Rose brown", "#A5685E"),
            _s("brick", "Brick", "#A8412F"),
            _s("warm-red", "Warm red", "#A8281B"),
            _satin("plum", "Plum", "#6E2A3E"),
            _s("oxblood", "Oxblood", "#7A0F1E")),
        "lip_line": _ladder(_s("rose-brown", "Rose brown", "#A5685E", intensity=34),
                            _s("red", "Red", "#8E0F1A", intensity=48),
                            _s("wine", "Wine", "#6A1B2C", intensity=62)),
    },
    "deep": {
        "eyes": _ladder(
            _shimmer("gold-glow", "Gold glow", "#D4A94E", "#B98A4E"),
            _shimmer("gold-copper", "Gold copper", "#C9A24A", "#A8683F"),
            _shimmer("copper-chocolate", "Copper chocolate", "#A8683F", "#4A2F27"),
            _shimmer("bronze-smoke", "Bronze smoke", "#B98A4E", "#3F1F14"),
            _shimmer("bronze-night", "Bronze night", "#B98A4E", "#2F1710"),
            _shimmer("emerald-night", "Emerald night", "#0F6B4A", "#2F1710"),
            _shimmer("burgundy-night", "Burgundy night", "#6E1A2E", "#2F1710"),
            _shimmer("purple-night", "Purple night", "#5B2A86", "#2F1710")),
        "liner": _ladder(_s("bronze", "Bronze", "#8A5A3A", intensity=50),
                         _s("espresso", "Espresso", "#2B1B17", intensity=62),
                         _s("soft-black", "Soft black", "#120c0a", intensity=74),
                         _s("black", "Black", "#0d0908", intensity=86)),
        "lashes": _DEEP_LASHES,
        "brows": _ladder(_s("soft-black-brown", "Soft black brown", "#3B2F2F"),
                         _s("dark-brown", "Dark brown", "#33241E"), _s("espresso", "Espresso", "#2B1B17")),
        # warm deep shades only: pinks and berries turn to mud on deep skin (probes r1, v3)
        "cheeks": _ladder(
            _satin("rose-orange", "Rose orange", "#D9785E"),
            _satin("copper-sunset", "Copper sunset", "#C86A5A"),
            _satin("warm-rose", "Warm rose", "#B5535A"),
            _satin("matte-red", "Warm red", "#C0262C"),
            _satin("brick", "Brick", "#A8412F"),
            _satin("mulled-rose", "Mulled rose", "#8E3A3C"),
            _satin("dark-cherry", "Dark cherry", "#7E2A38"),
            _satin("deep-sienna", "Deep sienna", "#6B2A2A")),
        "bronzer": _ladder(_bare("deep-tan", "Deep tan", "#8A5230", 16),
                           _bare("deep-bronze", "Deep bronze", "#8A4A2B", 24),
                           _bare("dark-bronze", "Dark bronze", "#6B3F28", 34)),
        "highlight": _ladder(_bare("warm-gold", "Warm gold", "#E3B98C", 34),
                             _bare("gold-bronze", "Gold bronze", "#D9A066", 46),
                             _bare("deep-gold", "Deep gold", "#C9A24A", 58)),
        "lips": _ladder(
            _satin("fuchsia", "Fuchsia", "#D6247F"),
            _satin("caramel-nude", "Caramel nude", "#A8645A"),
            _satin("bronze", "Bronze", "#9C5B3A"),
            _s("brick", "Brick", "#A8412F"),
            _satin("berry-rose", "Berry rose", "#8A2F45"),
            _s("deep-red", "Deep red", "#8E0F23"),
            _satin("plum", "Plum", "#6E2A3E"),
            _s("oxblood", "Oxblood", "#7A0F1E"),
            _s("dark-berry", "Dark berry", "#4A1230")),
        "lip_line": _ladder(_s("wine", "Wine", "#6A1B2C", intensity=40),
                            _s("chocolate-berry", "Chocolate berry", "#5A2A2E", intensity=54),
                            _s("dark-berry", "Dark berry", "#4A1230", intensity=68)),
    },
}

_LOOK_PATTERNS = {
    "fresh": {"eyes": "2colors1", "liner": "Upper283", "lashes": "Natural17"},
    "softglam": {"eyes": "2colors168", "liner": "Upper1", "lashes": "Natural17"},
    "evening": {"eyes": "2colors168", "liner": "Upper4", "lashes": "Upper&Lower4"},
}
_ZONE_PATTERNS = {"brows": "color", "bronzer": "Bronzer1", "highlight": "OvalFace28", "lips": "original",
                  "lip_line": "Natural1"}


def _look(kind: str, eyes: tuple[str, int, int, int], liner: tuple[str, int], lashes: tuple[str, int],
          brows: tuple[str, int], cheeks: tuple[str, int, str, int], bronzer: tuple[str, int],
          highlight: tuple[str, int], lips: tuple[str, int], lip_line: tuple[str, int] | None = None
          ) -> dict[str, ZoneLook]:
    """eyes: (shade, intensity, shimmer, crease offset); cheeks: (shade, intensity, pattern, glow); other zones:
    (shade, intensity). No `lip_line` = no lip liner in this look, as approved for the fresh look of the light group."""
    fixed = _LOOK_PATTERNS[kind]
    plain = {"brows": brows, "bronzer": bronzer, "highlight": highlight, "lips": lips,
             "lip_line": lip_line or (NONE_ID, 0)}
    zones = {
        "eyes": ZoneLook(eyes[0], eyes[1], fixed["eyes"], shimmer=eyes[2], crease_offset=eyes[3]),
        "liner": ZoneLook(liner[0], liner[1], fixed["liner"]),
        "lashes": ZoneLook(lashes[0], lashes[1], fixed["lashes"]),
        "cheeks": ZoneLook(cheeks[0], cheeks[1], cheeks[2], glow=cheeks[3]),
    }
    zones.update({z: ZoneLook(v[0], v[1], _ZONE_PATTERNS[z]) for z, v in plain.items()})
    return {z: zones[z] for z in ZONES}


LOOKS: dict[str, dict[str, dict[str, ZoneLook]]] = {
    "light": {
        "fresh": _look("fresh", ("champagne-taupe", 55, 55, 0), ("taupe-brown", 50), ("soft-black", 60),
                       ("soft-taupe", 28), ("soft-peach", 30, "1color2", 30), ("golden-peach", 14),
                       ("pearl-champagne", 35), ("rosy-peach", 55)),
        "softglam": _look("softglam", ("rose-gold-smoke", 80, 60, -2), ("espresso", 60), ("soft-black", 75),
                          ("brown", 35), ("muted-rose", 36, "1color2", 30), ("honey", 20),
                          ("pearl-champagne", 40), ("dusty-rose", 68), ("rose", 40)),
        "evening": _look("evening", ("copper-umber", 85, 70, 0), ("soft-black", 70), ("soft-black", 78),
                         ("brown", 42), ("deep-rose", 40, "1color2", 30), ("honey", 26),
                         ("pearl-champagne", 45), ("ruby", 80), ("red", 55)),
    },
    "medium": {
        "fresh": _look("fresh", ("champagne-taupe", 60, 58, 0), ("chocolate", 52), ("soft-black", 65),
                       ("smoky-taupe", 30), ("warm-peach", 34, "1color2", 30), ("honey", 16),
                       ("warm-champagne", 36), ("coral-rose", 58), ("cool-brown", 42)),
        "softglam": _look("softglam", ("rose-gold-smoke", 80, 62, -2), ("espresso", 64), ("soft-black", 78),
                          ("brown", 36), ("muted-rose", 40, "1color2", 30), ("amber", 21),
                          ("gold", 41), ("rose-brown", 72), ("rose", 46)),
        "evening": _look("evening", ("copper-umber", 86, 72, 0), ("soft-black", 74), ("soft-black", 80),
                         ("soft-black-brown", 42), ("warm-berry", 42, "1color2", 30), ("amber", 26),
                         ("gold", 45), ("ruby", 82), ("red", 56)),
    },
    "olive": {
        "fresh": _look("fresh", ("warm-gold", 62, 58, 0), ("plum-brown", 55), ("soft-black", 66),
                       ("brown", 30), ("peach-terracotta", 38, "1color2", 30), ("amber", 16),
                       ("gold", 38), ("peach-nude", 62), ("rose-brown", 44)),
        "softglam": _look("softglam", ("copper-rose", 80, 62, -2), ("espresso", 66), ("soft-black", 78),
                          ("soft-black-brown", 36), ("burnt-rose", 40, "1color2", 30), ("copper", 21),
                          ("gold", 41), ("rose-brown", 72), ("wine", 46)),
        "evening": _look("evening", ("copper-bronze", 86, 72, 0), ("soft-black", 76), ("soft-black", 80),
                         ("dark-brown", 42), ("warm-berry", 42, "1color2", 30), ("copper", 26),
                         ("gold-bronze", 45), ("warm-red", 84), ("wine", 58)),
    },
    "deep": {
        "fresh": _look("fresh", ("gold-copper", 65, 60, 0), ("espresso", 60), ("soft-black", 70),
                       ("soft-black-brown", 30), ("warm-rose", 46, "1color2", 30), ("deep-bronze", 18),
                       ("gold-bronze", 40), ("caramel-nude", 70), ("chocolate-berry", 45)),
        "softglam": _look("softglam", ("bronze-smoke", 82, 65, -2), ("soft-black", 70), ("soft-black", 80),
                          ("dark-brown", 40), ("mulled-rose", 36, "1color5", 25), ("deep-tan", 22),
                          ("warm-gold", 42), ("berry-rose", 76), ("wine", 55)),
        "evening": _look("evening", ("bronze-night", 88, 75, -3), ("black", 80), ("soft-black", 82),
                         ("espresso", 42), ("dark-cherry", 38, "1color5", 25), ("dark-bronze", 26),
                         ("deep-gold", 45), ("deep-red", 86), ("dark-berry", 60)),
    },
}


def ladder(group: str, zone: str) -> tuple[Shade, ...]:
    return LADDERS[group][zone]


def circles(group: str, zone: str) -> tuple[Shade, ...]:
    """What the sheet offers: the ladder, plus the circle without the product in a thin zone."""
    return LADDERS[group][zone] + ((_NONE,) if zone in THIN_ZONES else ())


def shade(group: str, zone: str, shade_id: str) -> Shade:
    for s in circles(group, zone):
        if s.id == shade_id:
            return s
    raise ValueError(f"no shade {shade_id!r} for {zone} in the {group} palette")


def skin_order(group: str, zone: str, skin_hex: str) -> list[Shade]:
    """The shades of a zone from the closest to her skin to the farthest (CIEDE2000; lids: the lid colour, the crease
    breaks a tie). Softer and Bolder walk this order. The circle without the product is not on it: taking a product away is a choice
    of its own, not a softer step."""

    def distance(s: Shade) -> list[float]:
        return [float(hex_delta_e2000(c, skin_hex)) for c in s.colors]

    return sorted(LADDERS[group][zone], key=distance)


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
