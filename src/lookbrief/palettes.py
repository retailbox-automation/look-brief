"""The palette: skin groups, nine zones, ladders of shades, three looks per group.

Every colour the app can send to Makeup VTO is a shade here: an edit picks another shade, it never computes a colour.
All hex values are ours (from wording in beauty sources), except the looks of the light and deep groups: those are the
request bodies the API accepted on 2026-10-31, and the critic and the client approved by eye
(tests/fixtures/approved_looks.json; ladders: PALETTE-V2 of the project docs). The medium and olive groups are built the
same way and have not been rendered on a real face yet.

A zone is either a ladder of colours (eyes, cheeks, lips: circles, Softer and Bolder) or a few styles with a name
(liner, lashes, brows, bronzer, highlighter, lip liner: a style brings its own pattern and strength). `LOOK_SHADES` hold
what only an approved look wears: never a circle, never a target of Softer or Bolder.
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
STYLE_ZONES = ("liner", "lashes", "brows", "bronzer", "highlight", "lip_line")
NONE_ZONES = ("liner", "highlight", "lip_line")  # the product can be left out (no bronzer: it would not show, dE 0.95)
NONE_ID = "none"
# Softer / Bolder stay in the colour family: the raw order of distance to her skin jumped from berry rose to fuchsia.
FAMILY_HUE = 30.0  # the next shade differs by at most this much of hue h* ...
FAMILY_CHROMA_RISE = 15.0  # ... and gains at most this much chroma C*
NEUTRAL_CHROMA = 6.0  # below this a colour has no hue to keep

# Concealer: a layer under every look, not a zone. Its colour is her skin 4 L* lighter; the two faces of the approved
# looks keep the colours measured on them.
CONCEALER_LIFT_L = 4.0
CONCEALER_FINISH = {"colorIntensity": 45, "colorUnderEyeIntensity": 55, "coverageLevel": 45}
CONCEALER_MEASURED = {"#dfa588": "#E8B79C", "#be8567": "#C88F6E"}
# A red lip takes the lip liner under it: shade of the lips -> (lip liner, strength).
LIP_LINE_UNDER = {"ruby": ("red", 45)}
# Strength and shimmer of the three lid colours (inner, lid, outer) on the ladder shades.
EYE_SLOTS = {"light": ((70, 85, 85), (60, 60, 0)), "medium": ((72, 85, 85), (60, 60, 0)),
             "olive": ((74, 86, 85), (64, 64, 0)), "deep": ((85, 92, 85), (80, 80, 0))}
EYE_PATTERN = "3colors1"
LASH_COLOR = "#17110f"
ZONE_PATTERNS = {"brows": "color", "bronzer": "Bronzer1", "highlight": "OvalFace28", "lips": "original",
                 "lip_line": "Natural1"}


@dataclass(frozen=True)
class Shade:
    id: str  # ends up in render file names: lowercase letters, digits, hyphens
    name: str
    colors: tuple[str, ...]  # eyes: inner, lid, outer (two colours on the fresh look: lid, crease); "none": no colour
    texture: str = "matte"  # "" where the API has no texture field (lashes, bronzer, highlighter)
    intensity: int | None = None  # the strength this shade brings; None: the look keeps its own
    pattern: str = ""  # the pattern this shade brings; "": the look keeps its own

    @property
    def main(self) -> str:
        """The colour that reads on the face: the lid colour of an eye shade, else the only colour."""
        return self.colors[1] if len(self.colors) == 3 else self.colors[0]


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


def _eye(id_: str, name: str, inner: str, lid: str, outer: str, texture: str = "shimmer") -> Shade:
    return Shade(id_, name, (inner, lid, outer), texture, None, EYE_PATTERN)


def _eye_look(id_: str, name: str, *colors: str, pattern: str) -> Shade:
    return Shade(id_, name, colors, "shimmer", None, pattern)


def _blush(id_: str, name: str, color: str, intensity: int | None = None) -> Shade:
    return Shade(id_, name, (color,), "satin", intensity)


def _lip(id_: str, name: str, color: str, texture: str = "satin") -> Shade:
    return Shade(id_, name, (color,), texture)


def _style(id_: str, name: str, color: str, intensity: int | None = None, pattern: str = "",
           texture: str = "matte") -> Shade:
    return Shade(id_, name, (color,), texture, intensity, pattern)


def _bare(id_: str, name: str, color: str, intensity: int | None = None, pattern: str = "") -> Shade:
    return _style(id_, name, color, intensity, pattern, texture="")


def _lashes(natural: int, wispy: int, volume: int) -> tuple[Shade, ...]:
    return (_bare("natural", "Natural", LASH_COLOR, natural, "Natural17"),
            _bare("wispy", "Wispy", LASH_COLOR, wispy, "Wispies37"),
            _bare("volume", "Volume", LASH_COLOR, volume, "Upper&Lower4"))


LADDERS: dict[str, dict[str, tuple[Shade, ...]]] = {
    "light": {
        "eyes": _ladder(
            _eye("rose-gold-smoke", "Rose gold smoke", "#EAD0BC", "#C98F7E", "#5C342A"),
            _eye("champagne-glow", "Champagne glow", "#F0DCC4", "#D9B08C", "#7A5240"),
            _eye("peach-bronze", "Peach bronze", "#F0D0B0", "#D4946C", "#6E4030"),
            _eye("warm-taupe", "Warm taupe", "#E6D2C0", "#A88670", "#4F3A30", "matte"),
            _eye("copper", "Copper", "#EAC8A8", "#B56E42", "#4A2A1E", "metallic"),
            _eye("plum-brown", "Plum brown", "#E6CFC4", "#8E5F66", "#43262C"),
            _eye("rose-brown", "Rose brown", "#E8CDBE", "#A87068", "#4A2A26", "matte"),
            _eye("chocolate-gold", "Chocolate gold", "#E6C89C", "#8A5A3A", "#2F1C16", "metallic")),
        "liner": (_style("classic", "Classic", "#2B1B17", 60, "Upper1"),
                  _style("smudge", "Smudge", "#3A2A24", 72, "Upper283"),
                  _style("wing", "Wing", "#17110f", 75, "Upper4")),
        "lashes": _lashes(75, 82, 78),
        "brows": (_style("natural", "Natural", "#5A4034", 35), _style("soft", "Soft", "#8A6A5C", 18),
                  _style("defined", "Defined", "#3B2A22", 72)),
        "cheeks": _ladder(
            _blush("muted-rose", "Muted rose", "#D58C95", 36),
            _blush("peach", "Peach", "#EE8F6A", 50),
            _blush("coral", "Coral", "#E8836B", 48),
            _blush("terracotta", "Terracotta", "#D9744F", 44),
            _blush("rose", "Rose", "#DE6A72", 46),
            _blush("berry", "Berry", "#C2506A", 44),
            _blush("mauve", "Mauve", "#B56A80", 46)),
        "bronzer": (_bare("natural", "Natural", "#C08A55", 20), _bare("sculpted", "Sculpted", "#8A5230", 85)),
        "highlight": (_bare("natural", "Natural", "#F3E3D0", 40), _bare("radiant", "Radiant", "#F3D3B5", 78)),
        "lips": _ladder(
            _lip("dusty-rose", "Dusty rose", "#B96F78"),
            _lip("light-pink", "Light pink", "#E8A0A8", "sheer"),
            _lip("peach-pink", "Peach pink", "#E9A08C", "sheer"),
            _lip("rosy-peach", "Rosy peach", "#D98C86", "sheer"),
            _lip("nude-rose", "Nude rose", "#B9766F"),
            _lip("warm-coral", "Warm coral", "#D9705F"),
            _lip("rosewood", "Rosewood", "#9E5A55"),
            _lip("raspberry", "Raspberry", "#B03050"),
            _lip("ruby", "Ruby", "#B0102E", "matte"),
            _lip("rose-gloss", "Rose gloss", "#B96F78", "gloss")),
        "lip_line": (_style("natural", "Natural", "#A63A50", 40), _style("defined", "Defined", "#8E4A58", 62)),
    },
    "medium": {
        "eyes": _ladder(
            _eye("rose-gold-smoke", "Rose gold smoke", "#EAD0BC", "#C98B7A", "#5C342A"),
            _eye("champagne-glow", "Champagne glow", "#F0DCC4", "#D9B08C", "#7A5240"),
            _eye("gold-bronze", "Gold bronze", "#EDD9A8", "#D4A94E", "#6E4A28"),
            _eye("warm-taupe", "Warm taupe", "#E6D2C0", "#9C7B6B", "#4A2F27", "matte"),
            _eye("copper", "Copper", "#EAC8A8", "#A8613A", "#3F2620", "metallic"),
            _eye("bronze-smoke", "Bronze smoke", "#E0C08C", "#8C5A2E", "#3F2620"),
            _eye("plum-smoke", "Plum smoke", "#E0C8BE", "#5E3F48", "#2F1710"),
            _eye("chocolate-gold", "Chocolate gold", "#E6C89C", "#7A4E34", "#2B1B17", "metallic")),
        "liner": (_style("classic", "Classic", "#2B1B17", 64, "Upper1"),
                  _style("smudge", "Smudge", "#3A2A24", 74, "Upper283"),
                  _style("wing", "Wing", "#17110f", 78, "Upper4")),
        "lashes": _lashes(78, 84, 80),
        "brows": (_style("natural", "Natural", "#5A4034", 36), _style("soft", "Soft", "#7A5C52", 20),
                  _style("defined", "Defined", "#3B2F2F", 72)),
        "cheeks": _ladder(
            _blush("muted-rose", "Muted rose", "#C97C84", 40),
            _blush("apricot", "Apricot", "#F0A58A", 50),
            _blush("warm-peach", "Warm peach", "#F2A27E", 48),
            _blush("peach", "Peach", "#EE9A82", 48),
            _blush("radiant-coral", "Radiant coral", "#F08A6E", 46),
            _blush("warm-pink", "Warm pink", "#E27A8A", 46),
            _blush("warm-berry", "Warm berry", "#B04A5E", 44)),
        "bronzer": (_bare("natural", "Natural", "#B97A4C", 21), _bare("sculpted", "Sculpted", "#8A5230", 85)),
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
            _lip("rose-gloss", "Rose gloss", "#A5685E", "gloss")),
        "lip_line": (_style("natural", "Natural", "#A63A50", 46), _style("defined", "Defined", "#8E4A58", 62)),
    },
    "olive": {
        "eyes": _ladder(
            _eye("copper-rose", "Copper rose", "#EACBB0", "#B8705A", "#5C342A"),
            _eye("warm-gold", "Warm gold", "#EDD9A8", "#C9A24A", "#6E4A28"),
            _eye("copper-bronze", "Copper bronze", "#E8C098", "#A8683F", "#3F2620", "metallic"),
            _eye("bronze-sepia", "Bronze sepia", "#E0C08C", "#8A5A3A", "#4A2F27"),
            _eye("sepia-smoke", "Sepia smoke", "#DDBF98", "#6B4730", "#2F1710", "matte"),
            _eye("plum-smoke", "Plum smoke", "#E0C8BE", "#5E3F48", "#2F1710"),
            _eye("burgundy-night", "Burgundy night", "#D8B090", "#6E1A2E", "#2F1710"),
            _eye("chocolate", "Chocolate", "#D8B890", "#4A2F27", "#2B1B17", "matte")),
        "liner": (_style("classic", "Classic", "#2B1B17", 66, "Upper1"),
                  _style("smudge", "Smudge", "#3A2A24", 76, "Upper283"),
                  _style("wing", "Wing", "#17110f", 78, "Upper4")),
        "lashes": _lashes(78, 84, 80),
        "brows": (_style("natural", "Natural", "#3B2F2F", 36), _style("soft", "Soft", "#5A4034", 20),
                  _style("defined", "Defined", "#33241E", 72)),
        "cheeks": _ladder(
            _blush("burnt-rose", "Burnt rose", "#B06A68", 40),
            _blush("amber-peach", "Amber peach", "#F0A060", 50),
            _blush("peach-terracotta", "Peach terracotta", "#D9805E", 48),
            _blush("coral", "Coral", "#F08060", 46),
            _blush("terracotta", "Terracotta", "#C9704F", 46),
            _blush("bronzed-terracotta", "Bronzed terracotta", "#B8663E", 44),
            _blush("warm-berry", "Warm berry", "#B04A5E", 44)),
        "bronzer": (_bare("natural", "Natural", "#A8683F", 21), _bare("sculpted", "Sculpted", "#6B3F28", 85)),
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
            _lip("rose-gloss", "Rose gloss", "#A5685E", "gloss")),
        "lip_line": (_style("natural", "Natural", "#6A1B2C", 46), _style("defined", "Defined", "#5A2A2E", 66)),
    },
    "deep": {
        "eyes": _ladder(
            _eye("gold-bronze", "Gold bronze", "#E8C070", "#C99A50", "#3F1F14"),
            _eye("copper-flame", "Copper flame", "#E0A868", "#B5653D", "#3A1C12", "metallic"),
            _eye("bronze-smoke", "Bronze smoke", "#C9A06A", "#8A5A36", "#2F1710"),
            _eye("rose-copper", "Rose copper", "#E0B090", "#B5705A", "#4A241A"),
            _eye("plum-gold", "Plum gold", "#D4A94E", "#6E2A4A", "#2A1220"),
            _eye("burgundy", "Burgundy", "#C98F6A", "#6E1A2E", "#2A0E14", "matte"),
            _eye("emerald", "Emerald", "#D4A94E", "#0F6B4A", "#0E2A20"),
            _eye("chocolate", "Chocolate", "#C09060", "#4A2F27", "#1F120E", "matte")),
        "liner": (_style("classic", "Classic", "#120c0a", 70, "Upper1"),
                  _style("smudge", "Smudge", "#2B1B17", 80, "Upper283"),
                  _style("wing", "Wing", "#0d0908", 80, "Upper4")),
        "lashes": _lashes(80, 86, 82),
        "brows": (_style("natural", "Natural", "#33241E", 40), _style("soft", "Soft", "#3B2F2F", 22),
                  _style("defined", "Defined", "#2B1B17", 72)),
        # warm deep shades only: pinks and berries turn to mud (probes r1, v3), orange and loud reds are out
        "cheeks": _ladder(
            _blush("mulled-rose", "Mulled rose", "#8E3A3C", 36),
            _blush("terracotta-rose", "Terracotta rose", "#A8553F", 54),
            _blush("soft-sienna", "Soft sienna", "#94503F", 52),
            _blush("warm-berry", "Warm berry", "#8C3A4A", 50),
            _blush("dark-cherry", "Dark cherry", "#7E2A38", 38),
            _blush("plum-wine", "Plum wine", "#6E2A3A", 50)),
        "bronzer": (_bare("natural", "Natural", "#8A5230", 22), _bare("sculpted", "Sculpted", "#4A2818", 85)),
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
            _lip("berry-gloss", "Berry gloss", "#8A2F45", "gloss")),
        "lip_line": (_style("natural", "Natural", "#6A1B2C", 55), _style("defined", "Defined", "#5A2A2E", 70)),
    },
}

LOOK_SHADES: dict[str, dict[str, tuple[Shade, ...]]] = {
    "light": {
        "eyes": (_eye_look("champagne-taupe", "Champagne taupe", "#E6CFA8", "#9C7B6B", pattern="2colors1"),
                 _eye_look("copper-umber", "Copper umber", "#EAD0BC", "#A8613A", "#3F2620", pattern="3colors8")),
        "liner": (_style("taupe-brown", "Taupe brown", "#7A5C52", pattern="Upper283"),),
        "cheeks": (_blush("soft-peach", "Soft peach", "#F0A090"), _blush("deep-rose", "Deep rose", "#D0707E")),
        "bronzer": (_bare("golden-peach", "Golden peach", "#D9A57A"),),
        "lip_line": (_style("red", "Red", "#8E0F1A"),),
    },
    "medium": {
        "eyes": (_eye_look("champagne-taupe", "Champagne taupe", "#E6CBA8", "#9C7B6B", pattern="2colors1"),
                 _eye_look("copper-umber", "Copper umber", "#EAD0BC", "#A8613A", "#3F2620", pattern="3colors8")),
        "liner": (_style("chocolate", "Chocolate", "#4A2F27", pattern="Upper283"),),
        "bronzer": (_bare("honey", "Honey", "#C08A55"),),
        "lip_line": (_style("cool-brown", "Cool brown", "#8D5F58"), _style("red", "Red", "#8E0F1A")),
    },
    "olive": {
        "eyes": (_eye_look("warm-gold-taupe", "Warm gold taupe", "#C9A24A", "#8A5A3A", pattern="2colors1"),
                 _eye_look("copper-night", "Copper night", "#E8C098", "#A8683F", "#3F2620", pattern="3colors8")),
        "liner": (_style("plum-brown", "Plum brown", "#5E3F48", pattern="Upper283"),),
        "bronzer": (_bare("amber", "Amber", "#B97A4C"),),
        "lip_line": (_style("rose-brown", "Rose brown", "#A5685E"), _style("wine", "Wine", "#6A1B2C")),
    },
    "deep": {
        "eyes": (_eye_look("gold-copper", "Gold copper", "#C9A24A", "#A8683F", pattern="2colors1"),
                 _eye_look("copper-night", "Copper night", "#D4A94E", "#A8683F", "#2F1710", pattern="3colors8")),
        "cheeks": (_blush("warm-rose", "Warm rose", "#B5535A"),),
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
    main = eyes[1][1] if len(eyes[1]) == 3 else eyes[1][0]
    plain = {"liner": liner, "lashes": lashes, "brows": brows, "bronzer": bronzer, "highlight": highlight, "lips": lips,
             "lip_line": lip_line}
    zones = {z: ZoneLook(v[0], v[1]) for z, v in plain.items()}
    zones["eyes"] = ZoneLook(eyes[0], main, slots=eyes[1], shimmer=eyes[2])
    zones["cheeks"] = ZoneLook(cheeks[0], cheeks[1], pattern=cheeks[2], glow=cheeks[3])
    return {z: zones[z] for z in ZONES}


LOOKS: dict[str, dict[str, dict[str, ZoneLook]]] = {
    "light": {
        "fresh": _look(("champagne-taupe", (55, 55), (55, 0)), ("taupe-brown", 50), ("natural", 60), ("soft", 28),
                       ("soft-peach", 30, "1color2", 30), ("golden-peach", 14), ("natural", 35), ("rosy-peach", 55)),
        "softglam": _look(("rose-gold-smoke", (70, 85, 85), (60, 60, 0)), ("classic", 60), ("natural", 75),
                          ("natural", 35), ("muted-rose", 36, "1color2", 30), ("natural", 20), ("natural", 40),
                          ("dusty-rose", 68), ("natural", 40)),
        "evening": _look(("copper-umber", (72, 85, 88), (60, 60, 0)), ("wing", 70), ("volume", 78), ("natural", 42),
                         ("deep-rose", 40, "1color2", 30), ("natural", 26), ("natural", 45), ("ruby", 80), ("red", 55)),
    },
    "medium": {
        "fresh": _look(("champagne-taupe", (60, 60), (58, 0)), ("chocolate", 52), ("natural", 65), ("soft", 30),
                       ("warm-peach", 34, "1color2", 30), ("honey", 16), ("radiant", 36), ("coral-rose", 58),
                       ("cool-brown", 42)),
        "softglam": _look(("rose-gold-smoke", (72, 85, 85), (60, 60, 0)), ("classic", 64), ("natural", 78),
                          ("natural", 36), ("muted-rose", 40, "1color2", 30), ("natural", 21), ("natural", 41),
                          ("rose-brown", 72), ("natural", 46)),
        "evening": _look(("copper-umber", (72, 85, 88), (60, 60, 0)), ("wing", 74), ("volume", 80), ("defined", 42),
                         ("warm-berry", 42, "1color2", 30), ("natural", 26), ("natural", 45), ("ruby", 82),
                         ("red", 56)),
    },
    "olive": {
        "fresh": _look(("warm-gold-taupe", (62, 62), (58, 0)), ("plum-brown", 55), ("natural", 66), ("soft", 30),
                       ("peach-terracotta", 38, "1color2", 30), ("amber", 16), ("natural", 38), ("peach-nude", 62),
                       ("rose-brown", 44)),
        "softglam": _look(("copper-rose", (74, 86, 85), (64, 64, 0)), ("classic", 66), ("natural", 78), ("natural", 36),
                          ("burnt-rose", 40, "1color2", 30), ("natural", 21), ("natural", 41), ("rose-brown", 72),
                          ("natural", 46)),
        "evening": _look(("copper-night", (76, 86, 88), (66, 62, 0)), ("wing", 76), ("volume", 80), ("defined", 42),
                         ("warm-berry", 42, "1color2", 30), ("natural", 26), ("radiant", 45), ("warm-red", 84),
                         ("wine", 58)),
    },
    "deep": {
        "fresh": _look(("gold-copper", (65, 65), (60, 0)), ("smudge", 60), ("natural", 70), ("soft", 30),
                       ("warm-rose", 46, "1color2", 30), ("deep-bronze", 18), ("radiant", 40), ("caramel-nude", 70),
                       ("defined", 45)),
        "softglam": _look(("gold-bronze", (85, 92, 85), (80, 80, 0)), ("classic", 70), ("natural", 80), ("natural", 40),
                          ("mulled-rose", 36, "1color5", 25), ("natural", 22), ("natural", 42), ("berry-rose", 76),
                          ("natural", 55)),
        "evening": _look(("copper-night", (80, 88, 88), (72, 65, 0)), ("wing", 80), ("volume", 82), ("defined", 42),
                         ("dark-cherry", 38, "1color5", 25), ("dark-bronze", 26), ("deep-gold", 45), ("deep-red", 86),
                         ("dark-berry", 60)),
    },
}


def ladder(group: str, zone: str) -> tuple[Shade, ...]:
    return LADDERS[group][zone]


def circles(group: str, zone: str) -> tuple[Shade, ...]:
    """What the sheet offers in a zone: the ladder, plus "none" where the product can be left out."""
    if zone not in NONE_ZONES:
        return LADDERS[group][zone]
    return (*LADDERS[group][zone], Shade(NONE_ID, "None", (), ""))


def shade(group: str, zone: str, shade_id: str) -> Shade:
    for s in (*circles(group, zone), *LOOK_SHADES[group].get(zone, ())):
        if s.id == shade_id:
            return s
    raise ValueError(f"no shade {shade_id!r} for {zone} in the {group} palette")


def _distance(s: Shade, skin_hex: str) -> list[float]:
    return [float(hex_delta_e2000(s.main, skin_hex)), *(float(hex_delta_e2000(c, skin_hex)) for c in s.colors)]


def skin_order(group: str, zone: str, skin_hex: str) -> list[Shade]:
    """The shades of a zone from the closest to her skin to the farthest (CIEDE2000; lids: the lid colour, the others
    break a tie). Softer and Bolder walk this order. The circle without the product is not on it: taking a product away
    is a choice of its own, not a softer step."""
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
    candidates = (s for s in way if s.id in ladder_ids and s.texture != "gloss" and s.main != here.main
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
