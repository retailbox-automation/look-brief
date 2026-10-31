import json
import re
from pathlib import Path

import numpy as np
import pytest
from helpers import SKIN

from lookbrief import palettes
from lookbrief import recipe as rcp
from lookbrief.color import hex_delta_e2000, lab_to_hex
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
    "concealer": ("color", "colorIntensity", "colorUnderEyeIntensity", "coverageLevel"),
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


def _look(group="light", look="softglam", shades=None):
    return rcp.look_recipe(group, look, SKIN[group], shades)


def _recipes(group):
    """Every recipe a bride can reach with one change from any look of her group."""
    for look in palettes.LOOK_IDS:
        r = _look(group, look)
        yield r
        for z in r["zones"]:
            for s in palettes.circles(group, z):
                yield rcp.apply_edit(r, z, f"shade:{s.id}")
        for z in palettes.STEP_ZONES:
            for op in rcp.EDIT_OPS:
                if not rcp.blocked(r, z, op):
                    yield rcp.apply_edit(r, z, op)


def _distance(r, zone):
    z = r["zones"][zone]
    main = palettes.shade(r["group"], zone, z["shade_id"]).main
    return hex_delta_e2000(main, r["skin_hex"])


def test_recipe_v2_describes_every_zone():
    r = _look()
    assert r["version"] == 2 and r["group"] == "light" and r["look"] == "softglam" and r["skin_hex"] == SKIN["light"]
    assert list(r["zones"]) == list(palettes.ZONES)
    lips = r["zones"]["lips"]
    assert {"category", "shade_id", "shade_name", "palette", "texture", "pattern", "intensity"} <= set(lips)
    assert lips["shade_id"] == "dusty-rose" and lips["palette"] == ["#B96F78"] and lips["texture"] == "satin"
    assert lips["pattern"] == "original" and lips["intensity"] == 68
    assert r["zones"]["eyes"]["palette"] == ["#B9745F", "#5C342A"]
    assert r["zones"]["eyes"]["pattern"] == "2colors279" and r["zones"]["eyes"]["intensity"] == 92


def test_the_old_colour_formula_and_strength_steps_are_gone():
    for name in ("product_color", "_more_vivid", "TUNING", "SOFTER_KEEP", "SOFTER_INTENSITY", "BOLDER_STEP",
                 "BOLDER_DARKEN", "SHADE_STEP_L", "zone_intensity"):
        assert not hasattr(rcp, name), name
    assert not hasattr(palettes, "RANGES") and not hasattr(palettes, "INTENSITY_STEP")
    assert rcp.EDIT_OPS == ("softer", "bolder"), "Lighter and Deeper are gone"
    assert not {"lightest", "deepest"} & set(rcp.BLOCK_NOTES)
    assert not hasattr(rcp, "FINISHES") and not hasattr(rcp, "FINISH_PREFIX"), "Finish is gone: gloss is a circle"


def test_pinned_recipe_is_the_look_itself():
    assert rcp.base_recipe(None, "deep", SKIN["deep"], "softglam") == _look("deep", "softglam")


def test_pin_overrides_a_shade_and_keeps_the_look():
    r = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    plain = _look()
    assert r["zones"]["lips"]["palette"] == ["#B0102E"] and r["zones"]["lips"]["texture"] == "matte"
    assert r["zones"]["lips"]["intensity"] == plain["zones"]["lips"]["intensity"]
    for recipe in (r, plain):
        recipe["zones"].pop("lips")
        recipe["zones"].pop("lip_line")
    assert r["zones"] == plain["zones"]


def test_a_ruby_lip_takes_the_red_liner_under_it():
    r = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    assert r["zones"]["lip_line"]["palette"] == ["#8E0F1A"] and r["zones"]["lip_line"]["intensity"] == 45
    effects = {e["category"]: e for e in rcp.to_vto_effects(r)}
    assert effects["lip_liner"]["palettes"][0]["color"] == "#8E0F1A"


def test_an_explicit_lip_liner_wins_over_the_one_under_ruby():
    r = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby", "lip_line": "defined"})
    assert r["zones"]["lip_line"]["shade_id"] == "defined"


def test_a_pin_outside_the_ladder_is_refused():
    with pytest.raises(ValueError):
        rcp.base_recipe(None, "deep", SKIN["deep"], "softglam", {"lips": "ruby"})


def test_the_inspiration_picks_the_colour_family_from_the_ladder():
    assert rcp.base_recipe(_map(lips="#a52b2d"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] == "ruby"
    assert rcp.base_recipe(_map(lips="#d98f9f"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] != "ruby"
    assert rcp.base_recipe(_map(lips="#a83050"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] == "raspberry"


def test_cheeks_and_lids_follow_the_inspiration_too():
    r = rcp.base_recipe(_map(cheeks="#f08878", eyes="#4a3a50"), "light", SKIN["light"])
    plain = _look()
    assert r["zones"]["cheeks"]["shade_id"] != plain["zones"]["cheeks"]["shade_id"]
    assert r["zones"]["eyes"]["shade_id"] != plain["zones"]["eyes"]["shade_id"]


def test_the_look_keeps_everything_but_the_tone():
    r = rcp.base_recipe(_map(), "light", SKIN["light"])
    plain = _look()
    for zone in ("lips", "cheeks", "eyes"):
        assert r["zones"][zone]["intensity"] == plain["zones"][zone]["intensity"]
        assert r["zones"][zone]["pattern"] == plain["zones"][zone]["pattern"]
    assert r["zones"]["brows"] == plain["zones"]["brows"]


def test_a_zone_the_transfer_barely_touched_keeps_the_shade_of_the_look():
    r = rcp.base_recipe(_map(lips="#a52b2d", changed=100), "light", SKIN["light"])
    assert r["zones"]["lips"] == _look()["zones"]["lips"]


def test_unknown_group_or_look_is_refused():
    with pytest.raises(ValueError):
        rcp.look_recipe("tan", "softglam", SKIN["light"])
    with pytest.raises(ValueError):
        rcp.look_recipe("light", "party", SKIN["light"])


# ---------------- Softer and Bolder: a step of the palette, closer to her skin or further from it ----------------
@pytest.mark.parametrize("group", palettes.GROUPS)
def test_softer_goes_closer_to_her_skin_and_bolder_further(group):
    base = _look(group)
    for zone in palettes.STEP_ZONES:
        d0 = _distance(base, zone)
        if not rcp.blocked(base, zone, "softer"):
            assert _distance(rcp.apply_edit(base, zone, "softer"), zone) < d0, (group, zone)
        if not rcp.blocked(base, zone, "bolder"):
            assert _distance(rcp.apply_edit(base, zone, "bolder"), zone) > d0, (group, zone)


def test_softer_and_bolder_are_the_next_shades_of_her_order_within_the_family():
    base = _look()
    start = palettes.shade("light", "lips", base["zones"]["lips"]["shade_id"])
    order = palettes.skin_order("light", "lips", SKIN["light"])
    i = order.index(start)
    fits = [s.step and s.main != start.main and palettes.same_family(start.main, s.main) for s in order]
    softer = next(order[j].id for j in range(i - 1, -1, -1) if fits[j])
    bolder = next(order[j].id for j in range(i + 1, len(order)) if fits[j])
    assert rcp.resolve_edit(base, "lips", "softer") == ["lips", f"shade:{softer}"]
    assert rcp.resolve_edit(base, "lips", "bolder") == ["lips", f"shade:{bolder}"]


@pytest.mark.parametrize("group", ["light", "deep"])
def test_gloss_is_a_circle_of_its_own_never_a_step(group):
    for s in palettes.ladder(group, "lips"):
        for op in rcp.EDIT_OPS:
            target = palettes.step_from(group, "lips", SKIN[group], s.id, op)
            assert target is None or palettes.shade(group, "lips", target).step, (s.id, op)


def test_a_step_never_lands_on_the_same_colour_with_another_finish():
    base = _look()
    assert rcp.apply_edit(base, "lips", "bolder")["zones"]["lips"]["shade_id"] != "rose-gloss"
    assert rcp.apply_edit(base, "lips", "softer")["zones"]["lips"]["shade_id"] != "rose-gloss"


@pytest.mark.parametrize(("a", "b", "same"), [
    ("#B96F78", "#B9766F", True),  # dusty rose, nude rose: hue 14 and 30, chroma close
    ("#B96F78", "#E4719A", False),  # candy pink: chroma +17.6
    ("#8A2F45", "#D6247F", False),  # fuchsia: chroma +30
    ("#E9A08C", "#A32A6B", False),  # peach pink and orchid berry: 50 degrees of hue apart
    ("#D6247F", "#8A2F45", True),  # a less vivid shade is always within the chroma limit
    ("#17110f", "#000000", True),  # blacks have no hue to keep
    ("#D58C95", "#D9A066", False),  # muted rose and a gold: chroma is fine, 56 degrees of hue apart
])
def test_same_family_limits_hue_and_the_rise_in_chroma(a, b, same):
    assert palettes.same_family(a, b) is same


def test_a_hue_across_the_wrap_is_measured_the_short_way():
    assert palettes.same_family(lab_to_hex(np.array([50.0, -30.0, 4.0])), lab_to_hex(np.array([50.0, -30.0, -4.0])))


def test_a_hue_across_zero_is_measured_the_short_way():
    assert palettes.same_family("#C45078", "#B5535A"), "hue 1 and 21: 20 degrees"
    assert palettes.same_family("#A2175F", "#A8204E"), "hue 355 and 8: 13 degrees, not 347"


def test_no_family_shade_on_the_way_turns_the_button_off():
    r = _look()
    order = palettes.skin_order("light", "lips", SKIN["light"])
    cut = next(s for s in order[:-1] if palettes.step_from("light", "lips", SKIN["light"], s.id, "bolder") is None)
    assert order.index(cut) < len(order) - 1, "precondition: farther shades exist, of other families"
    edge = rcp.apply_edit(r, "lips", f"shade:{cut.id}")
    assert rcp.blocked(edge, "lips", "bolder") == "boldest"
    with pytest.raises(ValueError):
        rcp.apply_edit(edge, "lips", "bolder")


def test_the_order_is_her_skin_not_a_fixed_one():
    pale = palettes.skin_order("light", "cheeks", "#f6e2d6")
    tan = palettes.skin_order("light", "cheeks", "#a56a4a")
    assert [s.id for s in pale] != [s.id for s in tan]


def test_lids_are_ordered_by_the_lid_colour_and_the_crease_breaks_a_tie():
    order = palettes.skin_order("light", "eyes", SKIN["light"])
    d = [hex_delta_e2000(s.main, SKIN["light"]) for s in order]
    assert d == sorted(d)


def test_softer_is_the_same_render_as_tapping_that_circle():
    base = _look()
    _, op = rcp.resolve_edit(base, "lips", "softer")
    assert rcp.apply_edit(base, "lips", "softer") == rcp.apply_edit(base, "lips", op)


def test_softer_and_bolder_leave_the_other_zones_alone():
    base = _look()
    out = rcp.apply_edit(base, "cheeks", "bolder")
    out["zones"].pop("cheeks")
    expected = _look()
    expected["zones"].pop("cheeks")
    assert out["zones"] == expected["zones"]
    assert base == _look(), "no mutation"


def test_a_lip_step_keeps_the_strength_of_the_look_and_a_blush_step_brings_its_own():
    base = _look()
    assert rcp.apply_edit(base, "lips", "bolder")["zones"]["lips"]["intensity"] == base["zones"]["lips"]["intensity"]
    target = rcp.apply_edit(base, "cheeks", "bolder")["zones"]["cheeks"]
    assert target["intensity"] == palettes.shade("light", "cheeks", target["shade_id"]).intensity


def test_the_ends_of_the_order_block_the_step():
    base = _look()
    order = [s.id for s in palettes.skin_order("light", "lips", SKIN["light"])]
    nearest = rcp.apply_edit(base, "lips", f"shade:{order[0]}")
    farthest = rcp.apply_edit(base, "lips", f"shade:{order[-1]}")
    assert rcp.blocked(nearest, "lips", "softer") == "softest"
    assert rcp.blocked(farthest, "lips", "bolder") == "boldest"
    with pytest.raises(ValueError):
        rcp.apply_edit(nearest, "lips", "softer")


def test_the_steps_next_to_the_ends_still_work():
    base = _look()
    order = [s.id for s in palettes.skin_order("light", "lips", SKIN["light"])]
    second = rcp.apply_edit(base, "lips", f"shade:{order[1]}")
    assert rcp.apply_edit(second, "lips", "softer")["zones"]["lips"]["shade_id"] == order[0]


@pytest.mark.parametrize("zone", ["liner", "lashes", "brows", "bronzer", "highlight", "lip_line"])
def test_thin_zones_have_no_softer_or_bolder(zone):
    with pytest.raises(ValueError):
        rcp.apply_edit(_look(), zone, "softer")


def test_softer_and_bolder_start_from_a_look_of_its_own_shade():
    r = _look("light", "evening")
    assert r["zones"]["eyes"]["shade_id"] == "copper-umber", "a shade only the look wears"
    assert "copper-umber" not in {s.id for s in palettes.ladder("light", "eyes")}
    target = rcp.apply_edit(r, "eyes", "softer")["zones"]["eyes"]["shade_id"]
    assert target in {s.id for s in palettes.ladder("light", "eyes")}


def test_a_shade_only_a_look_wears_cannot_be_picked():
    with pytest.raises(ValueError):
        rcp.apply_edit(_look(), "eyes", "shade:copper-umber")


# ---------------- thin zones: styles with their own pattern and strength, "none" where it shows ----------------
@pytest.mark.parametrize("zone", ["highlight", "lip_line"])
def test_a_product_can_be_left_out_of_the_request(zone):
    out = rcp.apply_edit(_look("deep"), zone, "shade:none")
    assert out["zones"][zone]["shade_id"] == "none" and out["zones"][zone]["palette"] == []
    cats = [e["category"] for e in rcp.to_vto_effects(out)]
    assert palettes.ZONES[zone] not in cats and len(cats) == 10, "skin_smooth, concealer, eight zones"
    assert zone not in [x["zone"] for x in rcp.shade_list(out, _map())], "the artist has nothing to bring"


@pytest.mark.parametrize("zone", ["eyes", "lips", "cheeks", "brows", "lashes", "bronzer", "liner"])
def test_other_zones_cannot_be_left_out(zone):
    with pytest.raises(ValueError):
        rcp.apply_edit(_look(), zone, "shade:none")


def test_a_style_brings_its_own_pattern_and_strength():
    z = rcp.apply_edit(_look(), "liner", "shade:flick")["zones"]["liner"]
    assert z["pattern"] == "Upper246" and z["intensity"] == 68 and z["palette"] == ["#2B1B17"]
    lashes = rcp.apply_edit(_look(), "lashes", "shade:fluttery")["zones"]["lashes"]
    assert lashes["pattern"] == "Natural145" and lashes["intensity"] == 80 and lashes["palette"] == ["#17110f"]


def test_a_look_keeps_its_own_strength_on_a_shared_style():
    assert _look("light", "evening")["zones"]["brows"]["intensity"] == 42, "natural brows at 35 as a choice, 42 here"


def test_bronzer_has_nothing_to_pick():
    with pytest.raises(ValueError):
        rcp.apply_edit(_look(), "bronzer", "shade:natural")
    assert "bronzer" not in {e[0][0] for e in rcp.record_grid(_look())}


def test_light_fresh_shows_nine_zones_and_sends_no_lip_liner_as_approved():
    r = _look("light", "fresh")
    assert len(r["zones"]) == 9 and r["zones"]["lip_line"]["shade_id"] == "none"
    assert "lip_liner" not in [e["category"] for e in rcp.to_vto_effects(r)]


# ---------------- edits as a list ----------------
def test_the_selected_shade_and_look_are_not_a_change():
    base = _look()
    assert rcp.blocked(base, "lips", f"shade:{base['zones']['lips']['shade_id']}") == "current"
    assert rcp.blocked(base, "look", "softglam") == "current"
    assert rcp.blocked(base, "look", "evening") is None


def test_a_look_replaces_the_whole_recipe():
    assert rcp.apply_edit(_look("deep"), "look", "evening") == _look("deep", "evening")


@pytest.mark.parametrize(("zone", "op"), [
    ("nose", "softer"), ("lips", "glossier"), ("lips", "lighter"), ("lips", "deeper"), ("lips", "shade:no-such-shade"),
    ("lips", "shade:"), ("look", "party"), (None, "softer"), ("lips", None), ("lips", "shade:../../etc/passwd"),
    ("look", "shade:ruby"), ("lips", "finish:gloss")])
def test_unknown_edits_are_rejected(zone, op):
    r = _look()
    with pytest.raises(ValueError):
        rcp.apply_edit(r, zone, op)
    with pytest.raises(ValueError):
        rcp.blocked(r, zone, op)


def test_edit_keys_are_stable_for_every_kind_of_edit():
    assert rcp.edit_key([]) == "base"
    two = [["cheeks", "shade:peach"], ["lips", "shade:ruby"]]
    assert rcp.edit_key(two) == "cheeks:shade:peach+lips:shade:ruby"
    assert rcp.edit_key([["look", "evening"]]) == "look:evening"
    r = _look()
    assert rcp.recipe_sha256(r) == rcp.recipe_sha256(json.loads(json.dumps(r)))


def test_quiet_keys_name_where_a_step_starts():
    base = _look()
    start = base["zones"]["lips"]["shade_id"]
    assert rcp.quiet_key(base, "lips", "softer") == f"lips:softer@{start}"
    assert rcp.quiet_key(base, "lips", "shade:ruby") == "lips:shade:ruby"


def test_add_edit_keeps_one_shade_per_zone():
    base = _look()
    edits = rcp.add_edit(base, [], "lips", "shade:ruby")
    assert edits == [["lips", "shade:ruby"]]
    assert rcp.add_edit(base, edits, "lips", "shade:peach-pink") == [["lips", "shade:peach-pink"]]


def test_add_edit_back_to_the_starting_shade_drops_the_edit():
    base = _look()
    edits = rcp.add_edit(base, [], "lips", "shade:ruby")
    assert rcp.add_edit(base, edits, "lips", f"shade:{base['zones']['lips']['shade_id']}") == []


def test_add_edit_of_a_look_clears_the_rest_and_the_base_look_means_no_edit():
    base = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    edits = [["cheeks", "shade:peach"], ["lips", "shade:peach-pink"]]
    assert rcp.add_edit(base, edits, "look", "evening") == [["look", "evening"]]
    assert rcp.add_edit(base, [["look", "evening"]], "look", "softglam") == []


def test_the_recorded_grid_is_every_circle_and_style_and_two_looks():
    base = _look()
    keys = [rcp.edit_key(e) for e in rcp.record_grid(base)]
    assert len(keys) == len(set(keys)) == 27 + 2
    assert {"look:fresh", "look:evening", "lips:shade:rose-gloss", "eyes:shade:bronze", "liner:shade:wing",
            "lashes:shade:fluttery", "highlight:shade:radiant", "lip_line:shade:none"} <= set(keys)
    assert f"lips:shade:{base['zones']['lips']['shade_id']}" not in keys, "the base shade is the base render"
    assert not [k for k in keys if "softer" in k or "bolder" in k or "finish" in k or k.startswith("bronzer")]


def test_the_deep_grid_has_fewer_blushes_and_lips():
    assert len(rcp.record_grid(_look("deep"))) == 26 + 2


def test_a_sample_with_a_liner_outside_the_ladder_records_the_natural_one_too():
    keys = [rcp.edit_key(e) for e in rcp.record_grid(_look("medium"))]
    assert len(keys) == 29 + 2 and "lip_line:shade:natural" in keys and "highlight:shade:radiant" in keys
    assert "highlight:shade:none" not in keys, "no highlighter is the base of medium"


# ---------------- the body ----------------
def test_body_on_nine_zones_follows_the_schema():
    effects = rcp.to_vto_effects(_look("deep"))
    assert [e["category"] for e in effects] == ["skin_smooth", "concealer", *palettes.ZONES.values()]
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
    assert "pattern" not in by["concealer"], "the schema has no pattern for concealer"


def test_every_look_sends_the_concealer_under_the_tones():
    for group in palettes.GROUPS:
        for look in palettes.LOOK_IDS:
            cats = [e["category"] for e in rcp.to_vto_effects(_look(group, look))]
            assert cats[:2] == ["skin_smooth", "concealer"] and "foundation" not in cats, (group, look)


def test_sheer_lips_carry_gloss_and_transparency():
    lips = next(e for e in rcp.to_vto_effects(_look("light", "fresh")) if e["category"] == "lip_color")
    assert lips["palettes"] == [{"color": "#D98C86", "texture": "sheer", "colorIntensity": 55, "gloss": 45,
                                 "transparencyIntensity": 30}]


def test_the_gloss_circle_is_sheer_for_a_soft_shine():
    r = rcp.apply_edit(_look(), "lips", "shade:rose-gloss")
    lips = next(e for e in rcp.to_vto_effects(r) if e["category"] == "lip_color")
    assert lips["palettes"] == [{"color": "#B96F78", "texture": "sheer", "colorIntensity": 68, "gloss": 45,
                                 "transparencyIntensity": 30}]


def test_a_metallic_lid_shade_follows_the_schema():
    eyes = next(e for e in rcp.to_vto_effects(rcp.apply_edit(_look(), "eyes", "shade:bronze"))
                if e["category"] == "eye_shadow")
    assert eyes["palettes"][0] == {"color": "#A8683F", "texture": "metallic", "shimmerColor": "#A8683F",
                                   "shimmerIntensity": 70, "metallicIntensity": 70, "colorIntensity": 92}
    assert eyes["palettes"][1] == {"color": "#4A2A1E", "texture": "matte", "colorIntensity": 88}


def test_a_matte_lid_shade_sends_no_shimmer():
    eyes = next(e for e in rcp.to_vto_effects(rcp.apply_edit(_look(), "eyes", "shade:warm-taupe"))
                if e["category"] == "eye_shadow")
    assert all(p["texture"] == "matte" and "shimmerIntensity" not in p for p in eyes["palettes"])


def test_a_lid_circle_from_the_fresh_look_takes_the_strengths_of_the_base():
    r = rcp.apply_edit(_look("light", "fresh"), "eyes", "shade:bronze")
    eyes = next(e for e in rcp.to_vto_effects(r) if e["category"] == "eye_shadow")
    assert eyes["pattern"] == {"name": "2colors279"} and [p["colorIntensity"] for p in eyes["palettes"]] == [92, 88]


@pytest.mark.parametrize(("group", "finish"), [("light", (8, 70, 35)), ("medium", (8, 70, 35)), ("olive", (20, 85, 50)),
                                               ("deep", (20, 85, 50))])
def test_the_concealer_is_her_own_colour_and_stays_under_the_eyes(group, finish):
    p = next(e for e in rcp.to_vto_effects(_look(group)) if e["category"] == "concealer")["palettes"][0]
    assert p == {"color": SKIN[group], "colorIntensity": finish[0], "colorUnderEyeIntensity": finish[1],
                 "coverageLevel": finish[2]}


@pytest.mark.parametrize(("group", "color"), [("medium", "#EBC8A0"), ("light", "#F0D0B0")])
def test_light_and_medium_skin_take_the_quieter_shine_as_a_choice(group, color):
    assert "highlighter" not in [e["category"] for e in rcp.to_vto_effects(_look(group))], "no highlighter in the base"
    r = rcp.apply_edit(_look(group), "highlight", "shade:radiant")
    hi = next(e for e in rcp.to_vto_effects(r) if e["category"] == "highlighter")["palettes"][0]
    assert (hi["color"], hi["colorIntensity"], hi["glowIntensity"], hi["shimmerIntensity"]) == (color, 22, 35, 15)


def test_deep_skin_keeps_the_stronger_shine():
    hi = next(e for e in rcp.to_vto_effects(_look("deep")) if e["category"] == "highlighter")["palettes"][0]
    assert (hi["glowIntensity"], hi["shimmerIntensity"]) == (45, 25)


def test_a_lip_liner_style_brings_its_own_stroke():
    base = next(e for e in rcp.to_vto_effects(_look()) if e["category"] == "lip_liner")["palettes"][0]
    assert (base["thickness"], base["smoothness"]) == (12, 90)
    r = rcp.apply_edit(_look(), "lip_line", "shade:defined")
    out = next(e for e in rcp.to_vto_effects(r) if e["category"] == "lip_liner")["palettes"][0]
    assert (out["thickness"], out["smoothness"]) == (30, 70)


@pytest.mark.parametrize("group", palettes.GROUPS)
def test_no_colour_outside_the_palette_on_any_step(group):
    """The palette guarantees the beauty only if no path can send a colour of its own."""
    allowed = {z: {c for s in (*palettes.ladder(group, z), *palettes.LOOK_SHADES[group].get(z, ())) for c in s.colors}
               for z in palettes.ZONES}
    by_cat = {cat: z for z, cat in palettes.ZONES.items()}
    n = 0
    for r in _recipes(group):
        for e in rcp.to_vto_effects(r)[2:]:  # after smoothing and the concealer, which comes from her skin
            for p in e["palettes"]:
                assert p["color"] in allowed[by_cat[e["category"]]], (group, e["category"], p["color"])
                n += 1
    assert n > 1000, "the walk must really cover the steps"


def test_no_render_carries_a_foundation():
    for group in palettes.GROUPS:
        assert "foundation" not in [x["category"] for x in rcp.to_vto_effects(_look(group))]
    assert [x["category"] for x in rcp.to_vto_effects(_look())][:3] == ["skin_smooth", "concealer", "eye_shadow"]
    assert rcp.even_out_effects("#dfa588", 30)[1]["category"] == "foundation", "the step of the transfer stays"


def test_shade_list_has_a_row_per_zone():
    rows = rcp.shade_list(_look(), _map())
    assert [x["zone"] for x in rows] == [z for z in palettes.ZONES if z != "highlight"], "no highlighter in the base"
    lips = next(x for x in rows if x["zone"] == "lips")
    assert lips["label"] == "Lips" and lips["product_hex"] == "#B96F78" and lips["shade_name"] == "Dusty rose"
    assert lips["on_face_hex"] == "#a52b2d" and lips["coverage"] == 0.3 and lips["intensity"] == 68
    brows = next(x for x in rows if x["zone"] == "brows")
    assert brows["label"] == "Brows" and brows["on_face_hex"] is None and brows["coverage"] is None
    eyes = next(x for x in rows if x["zone"] == "eyes")
    assert eyes["palette"] == ["#B9745F", "#5C342A"] and eyes["product_hex"] == "#B9745F", "the lid colour"
