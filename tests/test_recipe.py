import json
import re
from pathlib import Path

import pytest

from lookbrief import palettes
from lookbrief import recipe as rcp
from lookbrief.makeup_map import MakeupMap, ZoneStat

DOCS = json.loads((Path(__file__).parent / "fixtures" / "youcam_docs_snapshot.json").read_text())
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
# required fields per category, from makeup_vto.yaml (components/schemas/*Effect)
REQUIRED = {
    "eye_shadow": ("color", "texture", "colorIntensity"),
    "eye_liner": ("color", "texture", "colorIntensity"),
    "eyelashes": ("color", "colorIntensity"),
    "eyebrows": ("color", "colorIntensity", "texture"),
    "blush": ("color", "texture", "colorIntensity"),
    "bronzer": ("color", "colorIntensity"),
    "highlighter": ("color", "glowIntensity", "shimmerIntensity", "shimmerDensity", "shimmerSize", "colorIntensity"),
    "lip_color": ("color", "texture", "colorIntensity"),
    "lip_liner": ("color", "texture", "colorIntensity", "thickness", "smoothness"),
}
TEXTURES = {"eye_shadow": {"matte", "shimmer", "metallic"}, "eye_liner": {"matte", "shimmer", "metallic"},
            "eyebrows": {"matte", "shimmer"}, "blush": {"matte", "satin", "shimmer"},
            "lip_color": {"matte", "gloss", "holographic", "metallic", "satin", "sheer", "shimmer"},
            "lip_liner": {"matte", "satin"}}


def _map(lips="#a52b2d", cheeks="#e79d8f", eyes="#906551", changed=3000) -> MakeupMap:
    def z(name, before, after):
        return ZoneStat(name, name.title(), 10000, changed, changed / 10000, 8.0, after, before, 8.0)

    return MakeupMap(768, 1024, 0.1, 0.8, 0.3, {"eyes": z("eyes", "#aa806b", eyes),
                                                "cheeks": z("cheeks", "#dea38f", cheeks),
                                                "lips": z("lips", "#b16d67", lips)})


def _recipes(group):
    """Every recipe a bride can reach with one change from any look of her group."""
    for look in palettes.LOOK_IDS:
        r = rcp.look_recipe(group, look)
        yield r
        for z in r["zones"]:
            for s in palettes.ladder(group, z):
                yield rcp.apply_edit(r, z, f"shade:{s.id}")
            for op in rcp.EDIT_OPS:
                if not rcp.blocked(r, z, op):
                    yield rcp.apply_edit(r, z, op)


def test_recipe_v2_describes_every_zone():
    r = rcp.look_recipe("light", "softglam")
    assert r["version"] == 2 and r["group"] == "light" and r["look"] == "softglam"
    assert list(r["zones"]) == list(palettes.ZONES)
    lips = r["zones"]["lips"]
    assert {"category", "shade_id", "shade_name", "palette", "texture", "pattern", "intensity"} <= set(lips)
    assert lips["shade_id"] == "dusty-rose" and lips["palette"] == ["#B96F78"] and lips["texture"] == "satin"
    assert lips["pattern"] == "original" and lips["intensity"] == 68
    assert r["zones"]["eyes"]["palette"] == ["#C98F7E", "#5C342A"]


def test_the_old_colour_formula_is_gone():
    for name in ("product_color", "_more_vivid", "TUNING", "SOFTER_KEEP", "SOFTER_INTENSITY", "BOLDER_STEP",
                 "BOLDER_DARKEN", "SHADE_STEP_L", "zone_intensity"):
        assert not hasattr(rcp, name), name


def test_pinned_recipe_is_the_look_itself():
    assert rcp.base_recipe(None, "deep", "softglam") == rcp.look_recipe("deep", "softglam")


def test_pin_overrides_a_shade_and_keeps_the_look():
    r = rcp.base_recipe(None, "light", "softglam", {"lips": "ruby"})
    plain = rcp.look_recipe("light", "softglam")
    assert r["zones"]["lips"]["palette"] == ["#B0102E"] and r["zones"]["lips"]["texture"] == "matte"
    assert r["zones"]["lips"]["intensity"] == plain["zones"]["lips"]["intensity"]
    r["zones"].pop("lips")
    plain["zones"].pop("lips")
    assert r["zones"] == plain["zones"]


def test_a_pin_outside_the_ladder_is_refused():
    with pytest.raises(ValueError):
        rcp.base_recipe(None, "deep", "softglam", {"lips": "ruby"})


def test_the_inspiration_picks_the_colour_family_from_the_ladder():
    assert rcp.base_recipe(_map(lips="#a52b2d"), "light")["zones"]["lips"]["shade_id"] == "ruby"
    assert rcp.base_recipe(_map(lips="#d98f9f"), "light")["zones"]["lips"]["shade_id"] != "ruby"
    assert rcp.base_recipe(_map(lips="#a03070"), "light")["zones"]["lips"]["shade_id"] == "orchid-berry"


def test_cheeks_and_lids_follow_the_inspiration_too():
    r = rcp.base_recipe(_map(cheeks="#f08878", eyes="#4a3a50"), "light")
    plain = rcp.look_recipe("light", "softglam")
    assert r["zones"]["cheeks"]["shade_id"] != plain["zones"]["cheeks"]["shade_id"]
    assert r["zones"]["eyes"]["shade_id"] != plain["zones"]["eyes"]["shade_id"]


def test_the_look_keeps_everything_but_the_tone():
    r = rcp.base_recipe(_map(), "light")
    plain = rcp.look_recipe("light", "softglam")
    for zone in ("lips", "cheeks", "eyes"):
        assert r["zones"][zone]["intensity"] == plain["zones"][zone]["intensity"]
        assert r["zones"][zone]["pattern"] == plain["zones"][zone]["pattern"]
    assert r["zones"]["brows"] == plain["zones"]["brows"]


def test_a_zone_the_transfer_barely_touched_keeps_the_shade_of_the_look():
    r = rcp.base_recipe(_map(lips="#a52b2d", changed=100), "light")
    assert r["zones"]["lips"] == rcp.look_recipe("light", "softglam")["zones"]["lips"]


def test_unknown_group_or_look_is_refused():
    with pytest.raises(ValueError):
        rcp.look_recipe("tan", "softglam")
    with pytest.raises(ValueError):
        rcp.look_recipe("light", "party")


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_softer_and_bolder_change_only_the_strength_of_one_zone(group):
    base = rcp.look_recipe(group, "softglam")
    for zone, z0 in base["zones"].items():
        step = palettes.INTENSITY_STEP[zone]
        for op, sign in (("softer", -1), ("bolder", 1)):
            out = rcp.apply_edit(base, zone, op)
            assert out["zones"][zone] == {**z0, "intensity": z0["intensity"] + sign * step}, (group, zone, op)
            assert {k: v for k, v in out["zones"].items() if k != zone} == \
                   {k: v for k, v in base["zones"].items() if k != zone}
    assert base == rcp.look_recipe(group, "softglam"), "no mutation"


def test_lighter_and_deeper_are_the_neighbour_steps_of_the_ladder():
    base = rcp.look_recipe("light", "softglam")
    ladder = [s.id for s in palettes.ladder("light", "lips")]
    i = ladder.index(base["zones"]["lips"]["shade_id"])
    assert rcp.apply_edit(base, "lips", "lighter")["zones"]["lips"]["shade_id"] == ladder[i - 1]
    assert rcp.apply_edit(base, "lips", "deeper")["zones"]["lips"]["shade_id"] == ladder[i + 1]
    out = rcp.apply_edit(base, "lips", "deeper")["zones"]["lips"]
    assert out["intensity"] == base["zones"]["lips"]["intensity"] and out["pattern"] == "original"


def test_lighter_is_the_same_render_as_tapping_that_circle():
    base = rcp.look_recipe("light", "softglam")
    ladder = [s.id for s in palettes.ladder("light", "lips")]
    neighbour = ladder[ladder.index(base["zones"]["lips"]["shade_id"]) - 1]
    assert rcp.resolve_edit(base, "lips", "lighter") == ["lips", f"shade:{neighbour}"]
    assert rcp.apply_edit(base, "lips", "lighter") == rcp.apply_edit(base, "lips", f"shade:{neighbour}")


def test_the_top_and_bottom_of_the_ladder_block_the_step():
    base = rcp.look_recipe("light", "softglam")
    ladder = palettes.ladder("light", "lips")
    top = rcp.apply_edit(base, "lips", f"shade:{ladder[0].id}")
    bottom = rcp.apply_edit(base, "lips", f"shade:{ladder[-1].id}")
    assert rcp.blocked(top, "lips", "lighter") == "lightest" and rcp.blocked(top, "lips", "deeper") is None
    assert rcp.blocked(bottom, "lips", "deeper") == "deepest" and rcp.blocked(bottom, "lips", "lighter") is None
    with pytest.raises(ValueError):
        rcp.apply_edit(top, "lips", "lighter")


def test_the_edge_of_the_range_blocks_the_strength_button():
    r = rcp.look_recipe("light", "softglam")
    lo, hi = palettes.RANGES["light"]["cheeks"]
    r["zones"]["cheeks"]["intensity"] = lo
    assert rcp.blocked(r, "cheeks", "softer") == "softest" and rcp.blocked(r, "cheeks", "bolder") is None
    r["zones"]["cheeks"]["intensity"] = hi
    assert rcp.blocked(r, "cheeks", "bolder") == "boldest" and rcp.blocked(r, "cheeks", "softer") is None
    with pytest.raises(ValueError):
        rcp.apply_edit(r, "cheeks", "bolder")


def test_a_step_that_would_leave_the_range_is_blocked_not_cut_short():
    r = rcp.look_recipe("light", "softglam")
    lo, _ = palettes.RANGES["light"]["cheeks"]
    r["zones"]["cheeks"]["intensity"] = lo + palettes.INTENSITY_STEP["cheeks"] - 1
    assert rcp.blocked(r, "cheeks", "softer") == "softest"


def test_the_selected_shade_and_look_are_not_a_change():
    base = rcp.look_recipe("light", "softglam")
    assert rcp.blocked(base, "lips", f"shade:{base['zones']['lips']['shade_id']}") == "current"
    assert rcp.blocked(base, "look", "softglam") == "current"
    assert rcp.blocked(base, "look", "evening") is None


def test_a_look_replaces_the_whole_recipe():
    base = rcp.look_recipe("deep", "softglam")
    assert rcp.apply_edit(base, "look", "evening") == rcp.look_recipe("deep", "evening")


def test_light_fresh_has_no_lip_liner_as_approved():
    r = rcp.look_recipe("light", "fresh")
    assert "lip_line" not in r["zones"] and len(r["zones"]) == 8
    with pytest.raises(ValueError):
        rcp.apply_edit(r, "lip_line", "softer")


@pytest.mark.parametrize(("zone", "op"), [
    ("nose", "softer"), ("lips", "glossier"), ("lips", "shade:no-such-shade"), ("lips", "shade:"), ("look", "party"),
    (None, "softer"), ("lips", None), ("lips", "shade:../../etc/passwd"), ("look", "shade:ruby")])
def test_unknown_edits_are_rejected(zone, op):
    r = rcp.look_recipe("light", "softglam")
    with pytest.raises(ValueError):
        rcp.apply_edit(r, zone, op)
    with pytest.raises(ValueError):
        rcp.blocked(r, zone, op)


def test_edit_keys_are_stable_for_every_kind_of_edit():
    assert rcp.edit_key([]) == "base"
    assert rcp.edit_key([["cheeks", "softer"], ["lips", "shade:ruby"]]) == "cheeks:softer+lips:shade:ruby"
    assert rcp.edit_key([["look", "evening"]]) == "look:evening"
    r = rcp.look_recipe("light", "softglam")
    assert rcp.recipe_sha256(r) == rcp.recipe_sha256(json.loads(json.dumps(r)))


def test_add_edit_keeps_one_shade_per_zone():
    base = rcp.look_recipe("light", "softglam")
    edits = rcp.add_edit(base, [], "lips", "shade:ruby")
    assert edits == [["lips", "shade:ruby"]]
    assert rcp.add_edit(base, edits, "lips", "shade:peach-pink") == [["lips", "shade:peach-pink"]]
    assert rcp.add_edit(base, edits, "lips", "softer") == [["lips", "shade:ruby"], ["lips", "softer"]]


def test_add_edit_back_to_the_starting_shade_drops_the_edit():
    base = rcp.look_recipe("light", "softglam")
    edits = rcp.add_edit(base, [], "lips", "shade:ruby")
    assert rcp.add_edit(base, edits, "lips", f"shade:{base['zones']['lips']['shade_id']}") == []


def test_add_edit_of_a_look_clears_the_rest_and_the_base_look_means_no_edit():
    base = rcp.base_recipe(None, "light", "softglam", {"lips": "ruby"})
    edits = [["cheeks", "softer"], ["lips", "shade:peach-pink"]]
    assert rcp.add_edit(base, edits, "look", "evening") == [["look", "evening"]]
    assert rcp.add_edit(base, [["look", "evening"]], "look", "softglam") == []


def test_the_recorded_grid_is_every_shade_every_strength_and_two_looks():
    base = rcp.look_recipe("light", "softglam")
    grid = rcp.record_grid(base)
    keys = [rcp.edit_key(e) for e in grid]
    assert len(keys) == len(set(keys)) == 34 + 18 + 2
    assert "look:fresh" in keys and "look:evening" in keys and "lips:softer" in keys
    assert f"lips:shade:{base['zones']['lips']['shade_id']}" not in keys, "the base shade is the base render"
    assert "lips:lighter" not in keys, "lighter is the render of the neighbour circle"


def test_the_recorded_grid_skips_a_strength_button_on_the_edge():
    base = rcp.look_recipe("light", "softglam")
    base["zones"]["cheeks"]["intensity"] = palettes.RANGES["light"]["cheeks"][0]
    keys = [rcp.edit_key(e) for e in rcp.record_grid(base)]
    assert "cheeks:softer" not in keys and "cheeks:bolder" in keys and len(keys) == 34 + 17 + 2


def test_body_on_nine_zones_follows_the_schema():
    effects = rcp.to_vto_effects(rcp.look_recipe("deep", "softglam"))
    assert [e["category"] for e in effects] == ["skin_smooth", *palettes.ZONES.values()]
    assert effects[0] == {"category": "skin_smooth", "skinSmoothStrength": 0, "skinSmoothColorIntensity": 0}
    for e in effects[1:]:
        cat = e["category"]
        assert e["palettes"], cat
        for p in e["palettes"]:
            for field in REQUIRED[cat]:
                assert field in p, (cat, field)
            assert HEX.match(p["color"]), cat
            if cat in TEXTURES:
                assert p["texture"] in TEXTURES[cat], cat
            for k, v in p.items():
                if k not in ("color", "texture", "shimmerColor"):
                    assert isinstance(v, int) and 0 <= v <= 100, (cat, k, v)
    by = {e["category"]: e for e in effects}
    assert by["lip_color"]["style"] == {"type": "full"}, "lip_color without style -> HTTP 400"
    assert by["lip_color"]["shape"] == {"name": "original"}
    assert by["eyebrows"]["pattern"] == {"type": "color"}
    assert by["eye_shadow"]["pattern"]["name"] in DOCS["pattern_labels"]["eyeshadow"]
    assert by["blush"]["pattern"]["name"] in DOCS["pattern_labels"]["blush"]


def test_sheer_lips_carry_gloss_and_transparency():
    lips = rcp.to_vto_effects(rcp.look_recipe("light", "fresh"))[-1]
    assert lips["category"] == "lip_color"
    assert lips["palettes"] == [{"color": "#D98C86", "texture": "sheer", "colorIntensity": 55, "gloss": 45,
                                 "transparencyIntensity": 30}]


def test_a_matte_lid_shade_sends_no_shimmer():
    r = rcp.look_recipe("light", "softglam")
    matte = next(s for s in palettes.ladder("light", "eyes") if s.texture == "matte")
    eyes = rcp.to_vto_effects(rcp.apply_edit(r, "eyes", f"shade:{matte.id}"))[1]
    assert eyes["category"] == "eye_shadow"
    assert all(p["texture"] == "matte" and "shimmerIntensity" not in p for p in eyes["palettes"])


def test_strength_moves_both_colours_of_the_lids():
    r = rcp.look_recipe("light", "softglam")
    before = rcp.to_vto_effects(r)[1]["palettes"]
    after = rcp.to_vto_effects(rcp.apply_edit(r, "eyes", "softer"))[1]["palettes"]
    step = palettes.INTENSITY_STEP["eyes"]
    assert [p["colorIntensity"] for p in after] == [p["colorIntensity"] - step for p in before]


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_no_colour_outside_the_palette_on_any_step(group):
    """The palette guarantees the beauty only if no path can send a colour of its own."""
    allowed = {z: {c for s in palettes.ladder(group, z) for c in s.colors} for z in palettes.ZONES}
    by_cat = {cat: z for z, cat in palettes.ZONES.items()}
    n = 0
    for r in _recipes(group):
        for e in rcp.to_vto_effects(r)[1:]:
            for p in e["palettes"]:
                assert p["color"] in allowed[by_cat[e["category"]]], (group, e["category"], p["color"])
                n += 1
    assert n > 1000, "the walk must really cover the steps"


def test_even_out_foundation_rides_under_the_recipe():
    r = rcp.look_recipe("light", "softglam")
    assert "foundation" not in [x["category"] for x in rcp.to_vto_effects(r)], "transfer-first looks have no foundation"
    with_even = rcp.to_vto_effects(r, {"skin_hex": "#dfa588", "coverage": 30})
    assert [x["category"] for x in with_even][:3] == ["skin_smooth", "foundation", "eye_shadow"]
    assert with_even[1] == rcp.even_out_effects("#dfa588", 30)[1], "the same foundation as the even-out step"
    assert with_even[1]["palettes"][0] == {"color": "#dfa588", "colorIntensity": 40, "glowIntensity": 20,
                                           "coverageIntensity": 30}


def test_shade_list_has_a_row_per_zone():
    r = rcp.look_recipe("light", "softglam")
    rows = rcp.shade_list(r, _map())
    assert [x["zone"] for x in rows] == list(palettes.ZONES)
    lips = next(x for x in rows if x["zone"] == "lips")
    assert lips["label"] == "Lips" and lips["product_hex"] == "#B96F78" and lips["shade_name"] == "Dusty rose"
    assert lips["on_face_hex"] == "#a52b2d" and lips["coverage"] == 0.3 and lips["intensity"] == 68
    brows = next(x for x in rows if x["zone"] == "brows")
    assert brows["label"] == "Brows" and brows["on_face_hex"] is None and brows["coverage"] is None
    assert next(x for x in rows if x["zone"] == "eyes")["palette"] == ["#C98F7E", "#5C342A"]
