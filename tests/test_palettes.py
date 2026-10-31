"""The palette is what guarantees the makeup looks good: every colour and strength the app can send comes from here."""

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from helpers import SAMPLES, SKIN, load_rgb

from lookbrief import landmarks, makeup_map, palettes
from lookbrief import recipe as rcp
from lookbrief.color import hex_delta_e2000, hex_to_lab

APPROVED = json.loads((Path(__file__).parent / "fixtures" / "approved_looks.json").read_text())
DOCS = json.loads((Path(__file__).parent / "fixtures" / "youcam_docs_snapshot.json").read_text())
LIGHT_SIZES = {"eyes": 6, "liner": 3, "lashes": 3, "brows": 3, "cheeks": 5, "bronzer": 1, "highlight": 2, "lips": 10,
               "lip_line": 2}
DEEP_SIZES = {**LIGHT_SIZES, "cheeks": 4, "lips": 9}
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


@pytest.mark.parametrize(("group", "sizes"), [("light", LIGHT_SIZES), ("deep", DEEP_SIZES)])
def test_ladders_have_the_steps_of_palette_v3(group, sizes):
    assert {z: len(palettes.ladder(group, z)) for z in palettes.ZONES} == sizes


@pytest.mark.parametrize("group", ["medium", "olive"])
def test_medium_and_olive_are_built_the_same_way(group):
    sizes = {z: len(palettes.ladder(group, z)) for z in palettes.ZONES}
    assert {z: sizes[z] for z in palettes.STYLE_ZONES} == {z: LIGHT_SIZES[z] for z in palettes.STYLE_ZONES}
    assert sizes["eyes"] == 6 and sizes["cheeks"] == 5 and sizes["lips"] >= 9 and sizes["bronzer"] == 1


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_none_is_offered_on_highlighter_and_lip_liner_only(group):
    for zone in palettes.ZONES:
        ids = [s.id for s in palettes.circles(group, zone)]
        assert (palettes.NONE_ID in ids) is (zone in ("highlight", "lip_line")), zone


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_bronzer_is_no_choice(group):
    assert palettes.circles(group, "bronzer") == ()
    assert palettes.FIXED_ZONES == {"bronzer": "A light warm layer is part of this look."}


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g in palettes.GROUPS for z in palettes.STYLE_ZONES])
def test_a_style_brings_its_own_strength(group, zone):
    ladder = palettes.ladder(group, zone)
    assert all(isinstance(s.intensity, int) and 0 < s.intensity <= 100 for s in ladder), zone
    assert len({(s.colors, s.intensity, s.pattern) for s in ladder}) == len(ladder)


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_each_blush_shade_has_its_own_strength(group):
    assert all(isinstance(s.intensity, int) for s in palettes.ladder(group, "cheeks"))


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g in palettes.GROUPS for z in ("eyes", "lips")])
def test_lids_and_lips_keep_the_strength_of_the_look(group, zone):
    assert {s.intensity for s in palettes.ladder(group, zone)} == {None}


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g in palettes.GROUPS for z in palettes.STEP_ZONES])
def test_ladders_run_from_light_to_deep(group, zone):
    ls = [palettes.shade_lightness(s) for s in palettes.ladder(group, zone)]
    assert ls == sorted(ls, reverse=True), (group, zone, ls)


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g in palettes.GROUPS for z in palettes.STEP_ZONES])
def test_skin_order_runs_from_her_skin_outwards(group, zone):
    order = palettes.skin_order(group, zone, SKIN[group])
    d = [hex_delta_e2000(s.main, SKIN[group]) for s in order]
    assert d == sorted(d) and {s.id for s in order} == {s.id for s in palettes.ladder(group, zone)}


def test_gloss_is_a_sheer_circle_and_metallic_an_ordinary_shade():
    assert palettes.shade("light", "lips", "rose-gloss").texture == "sheer"
    assert palettes.shade("deep", "lips", "berry-gloss").texture == "sheer"
    assert {s.id for s in palettes.ladder("light", "eyes") if s.texture == "metallic"} == {"champagne", "bronze"}


def test_shades_left_out_of_the_palette_are_gone():
    lips = {s.id for s in palettes.circles("light", "lips")} | {s.id for s in palettes.circles("deep", "lips")}
    assert not lips & {"candy-pink", "orchid-berry", "smoky-rose", "fuchsia", "rosewood"}
    for group in ("light", "deep"):
        assert {s.id for s in palettes.circles(group, "liner")} == {"classic", "flick", "wing"}
        assert {s.id for s in palettes.circles(group, "lashes")} == {"natural", "fluttery", "volume"}


def test_a_look_only_shade_is_no_circle():
    assert palettes.shade("light", "eyes", "copper-umber").colors == ("#A8613A", "#2F1C16")
    assert "copper-umber" not in {s.id for s in palettes.circles("light", "eyes")}


def test_the_concealer_is_her_skin_a_touch_lighter():
    assert palettes.concealer_hex("#dfa588") == "#E8B79C" and palettes.concealer_hex("#be8567") == "#C88F6E"
    assert hex_to_lab(palettes.concealer_hex("#e4b29c"))[0] == pytest.approx(hex_to_lab("#e4b29c")[0] + 4, abs=0.5)


@pytest.mark.parametrize(("group", "zone"), ALL)
def test_shades_are_named_and_safe_for_file_names(group, zone):
    ladder = palettes.ladder(group, zone)
    assert len({s.id for s in ladder}) == len(ladder)
    for s in ladder:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s.id), s.id  # shade ids end up in render file names
        assert s.name and s.name.isascii()
        assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in s.colors)
    assert len({(s.colors, s.texture, s.intensity, s.pattern) for s in ladder}) == len(ladder), "two equal steps"


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_eye_shades_carry_lid_and_outer_corner(group):
    assert {len(s.colors) for s in palettes.ladder(group, "eyes")} == {2}


@pytest.mark.parametrize(("group", "zone"), [(g, z) for g, z in ALL if z != "eyes"])
def test_other_zones_carry_one_colour(group, zone):
    assert {len(s.colors) for s in palettes.ladder(group, zone)} == {1}


@pytest.mark.parametrize("group", palettes.GROUPS)
@pytest.mark.parametrize("look", palettes.LOOK_IDS)
def test_looks_use_shades_of_the_palette(group, look):
    for zone, z in palettes.LOOKS[group][look].items():
        assert palettes.shade(group, zone, z.shade), (group, look, zone)
        assert 0 <= z.intensity <= 100, (group, look, zone)
    assert rcp.look_recipe(group, look, SKIN[group])["zones"]["eyes"]["pattern"] == "2colors279"


@pytest.mark.parametrize("group", palettes.GROUPS)
@pytest.mark.parametrize("look", palettes.LOOK_IDS)
def test_looks_cover_nine_zones(group, look):
    assert list(palettes.LOOKS[group][look]) == list(palettes.ZONES)


def test_ruby_is_a_step_of_the_light_lips_for_the_classic_red_sample():
    assert palettes.shade("light", "lips", "ruby").colors == ("#B0102E",)


def test_deep_blush_stays_warm():
    """Probes r1/v3: pinks and berries turn to mud on deep skin, warm deep shades are beautiful (#8E3A3C, #7E2A38)."""
    for s in palettes.ladder("deep", "cheeks"):
        assert 9 <= _hue(s.main) <= 60, (s.id, _hue(s.main))
        assert _chroma(s.main) >= 30, s.id


def test_deep_blush_has_no_orange_and_nothing_loud():
    """Nadya's complaint about orange cheeks; the matte red shouted. Warm deep shades took their place."""
    colors = {s.colors[0] for s in palettes.ladder("deep", "cheeks")}
    assert not colors & {"#D9785E", "#C86A5A", "#C0262C"}
    assert {"#A8553F", "#8C3A4A"} <= colors
    assert palettes.LOOKS["deep"]["softglam"]["cheeks"].shade == "mulled-rose"


def test_no_pastel_or_white_on_deep_skin():
    for zone, ceiling in (("lips", 60), ("cheeks", 65), ("eyes", 72)):
        for s in palettes.ladder("deep", zone):
            assert hex_to_lab(s.main)[0] <= ceiling, (zone, s.id)


def test_patterns_are_in_the_youcam_catalogs():
    labels = DOCS["pattern_labels"]
    catalog = {"eyes": "eyeshadow", "liner": "eyeliner", "lashes": "eyelashes", "cheeks": "blush",
               "bronzer": "bronzer", "highlight": "highlighter", "lips": "lipshape", "lip_line": "lipliner"}
    for group in palettes.GROUPS:
        for look in palettes.LOOK_IDS:
            r = rcp.look_recipe(group, look, SKIN[group])
            for zone in palettes.ZONES:
                walked = [rcp.apply_edit(r, zone, f"shade:{s.id}")["zones"][zone]["pattern"]
                          for s in palettes.circles(group, zone)]
                for pattern in {r["zones"][zone]["pattern"], *walked}:
                    if zone == "brows":
                        assert pattern == "color"  # her own brow shape, pigment only
                    else:
                        assert pattern in labels[catalog[zone]], (zone, pattern)


@pytest.mark.parametrize(("group", "look"), [(g, k) for g in ("light", "deep") for k in palettes.LOOK_IDS])
def test_approved_looks_are_sent_byte_for_byte(group, look):
    want = APPROVED[group][look]
    even = None
    for e in want:
        if e["category"] == "foundation":
            even = {"skin_hex": e["palettes"][0]["color"], "coverage": e["palettes"][0]["coverageIntensity"]}
    got = rcp.to_vto_effects(rcp.look_recipe(group, look, SKIN[group]), even)
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
