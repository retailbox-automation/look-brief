"""The palette is what guarantees the makeup looks good: every colour and strength the app can send comes from here."""

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from helpers import SAMPLES, load_rgb

from lookbrief import landmarks, makeup_map, palettes
from lookbrief import recipe as rcp
from lookbrief.color import hex_to_lab

APPROVED = json.loads((Path(__file__).parent / "fixtures" / "approved_looks.json").read_text())
DOCS = json.loads((Path(__file__).parent / "fixtures" / "youcam_docs_snapshot.json").read_text())
SIZES = {"lips": 9, "cheeks": 8, "eyes": 8}
ALL = [(g, z) for g in palettes.GROUPS for z in palettes.ZONES]


def _hue(hex_: str) -> float:
    _, a, b = hex_to_lab(hex_)
    return math.degrees(math.atan2(b, a)) % 360


def _chroma(hex_: str) -> float:
    return float(np.hypot(*hex_to_lab(hex_)[1:]))


def test_nine_zones_map_to_the_api_categories_in_request_order():
    assert palettes.ZONES == {
        "eyes": "eye_shadow", "liner": "eye_liner", "lashes": "eyelashes", "brows": "eyebrows", "cheeks": "blush",
        "bronzer": "bronzer", "highlight": "highlighter", "lips": "lip_color", "lip_line": "lip_liner"}
    assert palettes.GROUPS == ("light", "medium", "olive", "deep")
    assert set(palettes.ZONE_LABELS) == set(palettes.ZONES)


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_each_group_has_43_shades(group):
    sizes = {z: len(palettes.ladder(group, z)) for z in palettes.ZONES}
    assert sizes == {z: SIZES.get(z, 3) for z in palettes.ZONES}
    assert sum(sizes.values()) == 43


@pytest.mark.parametrize(("group", "zone"), ALL)
def test_ladders_run_from_light_to_deep(group, zone):
    ls = [palettes.shade_lightness(s) for s in palettes.ladder(group, zone)]
    assert ls == sorted(ls, reverse=True), (group, zone, ls)


@pytest.mark.parametrize(("group", "zone"), ALL)
def test_shades_are_named_and_safe_for_file_names(group, zone):
    ladder = palettes.ladder(group, zone)
    assert len({s.id for s in ladder}) == len(ladder)
    for s in ladder:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s.id), s.id  # shade ids end up in render file names
        assert s.name and s.name.isascii()
        assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in s.colors)
    assert len({tuple(c.lower() for c in s.colors) for s in ladder}) == len(ladder), "two steps of one colour"


@pytest.mark.parametrize(("group", "zone"), [(g, "eyes") for g in palettes.GROUPS])
def test_eye_shades_carry_the_two_colours_of_their_pattern(group, zone):
    assert {len(s.colors) for s in palettes.ladder(group, zone)} == {2}
    assert {z.pattern[:7] for lk in palettes.LOOKS[group].values() for k, z in lk.items() if k == zone} == {"2colors"}


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g, z in ALL if z != "eyes"])
def test_other_zones_carry_one_colour(group, zone):
    assert {len(s.colors) for s in palettes.ladder(group, zone)} == {1}


@pytest.mark.parametrize("group", palettes.GROUPS)
@pytest.mark.parametrize("look", palettes.LOOK_IDS)
def test_looks_use_steps_of_the_ladders_and_stay_in_range(group, look):
    for zone, z in palettes.LOOKS[group][look].items():
        assert palettes.shade(group, zone, z.shade), (group, look, zone)
        lo, hi = palettes.RANGES[group][zone]
        assert lo <= z.intensity <= hi, (group, look, zone)


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_softglam_covers_nine_zones_and_every_strength_button_moves(group):
    look = palettes.LOOKS[group][palettes.DEFAULT_LOOK]
    assert set(look) == set(palettes.ZONES)
    for zone, z in look.items():
        lo, hi = palettes.RANGES[group][zone]
        step = palettes.INTENSITY_STEP[zone]
        assert lo <= z.intensity - step and z.intensity + step <= hi, (group, zone)


def test_ruby_is_a_step_of_the_light_lips_for_the_classic_red_sample():
    assert palettes.shade("light", "lips", "ruby").colors == ("#B0102E",)


def test_deep_blush_stays_warm():
    """Probes r1/v3: pinks and berries turn to mud on deep skin, warm deep shades are beautiful (#8E3A3C, #7E2A38)."""
    for s in palettes.ladder("deep", "cheeks"):
        assert 15 <= _hue(s.colors[0]) <= 60, (s.id, _hue(s.colors[0]))
        assert _chroma(s.colors[0]) >= 30, s.id


def test_no_pastel_or_white_on_deep_skin():
    for zone, ceiling in (("lips", 60), ("cheeks", 65), ("eyes", 72)):
        for s in palettes.ladder("deep", zone):
            assert hex_to_lab(s.colors[0])[0] <= ceiling, (zone, s.id)


def test_patterns_are_in_the_youcam_catalogs():
    labels = DOCS["pattern_labels"]
    catalog = {"eyes": "eyeshadow", "liner": "eyeliner", "lashes": "eyelashes", "cheeks": "blush",
               "bronzer": "bronzer", "highlight": "highlighter", "lips": "lipshape", "lip_line": "lipliner"}
    for group in palettes.GROUPS:
        for look in palettes.LOOKS[group].values():
            for zone, z in look.items():
                if zone == "brows":
                    assert z.pattern == "color"  # her own brow shape, pigment only
                else:
                    assert z.pattern in labels[catalog[zone]], (zone, z.pattern)


@pytest.mark.parametrize(("group", "look"), [(g, k) for g in ("light", "deep") for k in palettes.LOOK_IDS])
def test_approved_looks_are_sent_byte_for_byte(group, look):
    want = json.loads(json.dumps(APPROVED[group][look]))
    even = None
    for e in want:
        if e["category"] == "foundation":  # the only agreed change: 50 -> 40, forehead L* within 1.5
            assert e["palettes"][0]["colorIntensity"] == 50
            e["palettes"][0]["colorIntensity"] = 40
            even = {"skin_hex": e["palettes"][0]["color"], "coverage": e["palettes"][0]["coverageIntensity"]}
    got = rcp.to_vto_effects(rcp.look_recipe(group, look), even)
    assert rcp.canonical(got) == rcp.canonical(want)


@pytest.mark.parametrize(("lab", "group"), [
    ((72.5, 17.7, 23.4), "light"),  # s0 forehead, ITA 43.9
    ((76.5, 15.1, 18.2), "light"),  # s2, ITA 55.5
    ((60.5, 18.3, 24.9), "deep"),  # s3, ITA 22.9
    ((35.0, 12.0, 15.0), "deep"),  # negative ITA
    ((66.0, 18.0, 26.0), "medium"),  # ITA 31.6, rosy
    ((66.0, 10.0, 26.0), "olive"),  # ITA 31.6, yellow-green
])
def test_skin_group_by_ita(lab, group):
    assert palettes.skin_group(np.array(lab)) == group


@pytest.mark.parametrize(("sample", "group"), [
    ("s0-champagne-rose", "light"), ("s1-soft-glam", "light"), ("s2-classic-red", "light"), ("s3-mauve-smoky", "deep")])
def test_skin_group_of_the_four_faces(sample, group):
    """On the real forehead cells. s0 is measured on the base photo, as the app does (hair first)."""
    sd = SAMPLES / sample
    name = "results/hair_transfer.jpg" if sample.startswith("s0") else "bride.jpg"
    rgb = load_rgb(sd / name)
    face = landmarks.detect(rgb)
    forehead = np.median(makeup_map._lab(rgb)[landmarks.zone_cells(face)["skin"]], axis=0)
    assert palettes.skin_group(forehead) == group
