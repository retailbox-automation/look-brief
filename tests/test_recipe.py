import json
import re
from pathlib import Path

import pytest
from helpers import SKIN

from lookbrief import palettes
from lookbrief import recipe as rcp
from lookbrief.color import hex_delta_e2000
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
            for op in rcp.EDIT_OPS:
                if not rcp.blocked(r, z, op):
                    yield rcp.apply_edit(r, z, op)
            for t in rcp.FINISHES.get(z, ()):
                yield rcp.apply_edit(r, z, f"finish:{t}")


def _distance(r, zone):
    return [hex_delta_e2000(c, r["skin_hex"]) for c in r["zones"][zone]["palette"]]


def test_recipe_v2_describes_every_zone():
    r = _look()
    assert r["version"] == 2 and r["group"] == "light" and r["look"] == "softglam" and r["skin_hex"] == SKIN["light"]
    assert list(r["zones"]) == list(palettes.ZONES)
    lips = r["zones"]["lips"]
    assert {"category", "shade_id", "shade_name", "palette", "texture", "pattern", "intensity"} <= set(lips)
    assert lips["shade_id"] == "dusty-rose" and lips["palette"] == ["#B96F78"] and lips["texture"] == "satin"
    assert lips["pattern"] == "original" and lips["intensity"] == 68
    assert r["zones"]["eyes"]["palette"] == ["#C98F7E", "#5C342A"]


def test_the_old_colour_formula_and_strength_steps_are_gone():
    for name in ("product_color", "_more_vivid", "TUNING", "SOFTER_KEEP", "SOFTER_INTENSITY", "BOLDER_STEP",
                 "BOLDER_DARKEN", "SHADE_STEP_L", "zone_intensity"):
        assert not hasattr(rcp, name), name
    assert not hasattr(palettes, "RANGES") and not hasattr(palettes, "INTENSITY_STEP")
    assert rcp.EDIT_OPS == ("softer", "bolder"), "Lighter and Deeper are gone"
    assert not {"lightest", "deepest"} & set(rcp.BLOCK_NOTES)


def test_pinned_recipe_is_the_look_itself():
    assert rcp.base_recipe(None, "deep", SKIN["deep"], "softglam") == _look("deep", "softglam")


def test_pin_overrides_a_shade_and_keeps_the_look():
    r = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    plain = _look()
    assert r["zones"]["lips"]["palette"] == ["#B0102E"] and r["zones"]["lips"]["texture"] == "matte"
    assert r["zones"]["lips"]["intensity"] == plain["zones"]["lips"]["intensity"]
    r["zones"].pop("lips")
    plain["zones"].pop("lips")
    assert r["zones"] == plain["zones"]


def test_a_pin_outside_the_ladder_is_refused():
    with pytest.raises(ValueError):
        rcp.base_recipe(None, "deep", SKIN["deep"], "softglam", {"lips": "ruby"})


def test_the_inspiration_picks_the_colour_family_from_the_ladder():
    assert rcp.base_recipe(_map(lips="#a52b2d"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] == "ruby"
    assert rcp.base_recipe(_map(lips="#d98f9f"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] != "ruby"
    assert rcp.base_recipe(_map(lips="#a03070"), "light", SKIN["light"])["zones"]["lips"]["shade_id"] == "orchid-berry"


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
    for zone in base["zones"]:
        if base["zones"][zone]["shade_id"] == palettes.NONE_ID:
            continue
        d0 = _distance(base, zone)
        if not rcp.blocked(base, zone, "softer"):
            assert _distance(rcp.apply_edit(base, zone, "softer"), zone) < d0, (group, zone)
        if not rcp.blocked(base, zone, "bolder"):
            assert _distance(rcp.apply_edit(base, zone, "bolder"), zone) > d0, (group, zone)


def test_softer_and_bolder_are_the_neighbours_in_the_order_of_her_skin():
    base = _look()
    order = [s.id for s in palettes.skin_order("light", "lips", SKIN["light"])]
    i = order.index(base["zones"]["lips"]["shade_id"])
    assert rcp.resolve_edit(base, "lips", "softer") == ["lips", f"shade:{order[i - 1]}"]
    assert rcp.resolve_edit(base, "lips", "bolder") == ["lips", f"shade:{order[i + 1]}"]


def test_the_order_is_her_skin_not_a_fixed_one():
    pale = palettes.skin_order("light", "cheeks", "#f6e2d6")
    tan = palettes.skin_order("light", "cheeks", "#a56a4a")
    assert [s.id for s in pale] != [s.id for s in tan]


def test_lids_are_ordered_by_the_lid_colour_and_the_crease_breaks_a_tie():
    order = palettes.skin_order("light", "eyes", SKIN["light"])
    d = [hex_delta_e2000(s.colors[0], SKIN["light"]) for s in order]
    assert d == sorted(d)
    deep = [s.id for s in palettes.skin_order("deep", "eyes", SKIN["deep"])]
    assert deep.index("bronze-smoke") < deep.index("bronze-night"), "one lid colour, a deeper crease is further"


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


def test_softer_and_bolder_keep_the_strength_of_a_zone_without_a_strength_of_its_own():
    base = _look()
    assert rcp.apply_edit(base, "lips", "bolder")["zones"]["lips"]["intensity"] == base["zones"]["lips"]["intensity"]


def test_the_ends_of_the_order_block_the_step():
    base = _look()
    order = [s.id for s in palettes.skin_order("light", "lips", SKIN["light"])]
    nearest = rcp.apply_edit(base, "lips", f"shade:{order[0]}")
    farthest = rcp.apply_edit(base, "lips", f"shade:{order[-1]}")
    assert rcp.blocked(nearest, "lips", "softer") == "softest" and rcp.blocked(nearest, "lips", "bolder") is None
    assert rcp.blocked(farthest, "lips", "bolder") == "boldest" and rcp.blocked(farthest, "lips", "softer") is None
    with pytest.raises(ValueError):
        rcp.apply_edit(nearest, "lips", "softer")
    one_before_last = rcp.apply_edit(base, "lips", f"shade:{order[-2]}")
    assert rcp.apply_edit(one_before_last, "lips", "bolder")["zones"]["lips"]["shade_id"] == order[-1]
    second = rcp.apply_edit(base, "lips", f"shade:{order[1]}")
    assert rcp.apply_edit(second, "lips", "softer")["zones"]["lips"]["shade_id"] == order[0]


def test_a_zone_without_makeup_has_nothing_to_soften_and_bolder_starts_at_the_nearest_shade():
    base = rcp.apply_edit(_look(), "bronzer", "shade:none")
    assert rcp.blocked(base, "bronzer", "softer") == "softest"
    nearest = palettes.skin_order("light", "bronzer", SKIN["light"])[0].id
    assert rcp.resolve_edit(base, "bronzer", "bolder") == ["bronzer", f"shade:{nearest}"]


def test_softer_never_removes_a_product():
    base = _look()
    nearest = palettes.skin_order("light", "bronzer", SKIN["light"])[0].id
    r = rcp.apply_edit(base, "bronzer", f"shade:{nearest}")
    assert rcp.blocked(r, "bronzer", "softer") == "softest"


# ---------------- thin zones: shades with a strength of their own, a circle without the product ----------------
@pytest.mark.parametrize("zone", ["bronzer", "highlight", "liner", "lip_line"])
def test_a_thin_zone_can_be_left_out_of_the_request(zone):
    base = _look()
    out = rcp.apply_edit(base, zone, "shade:none")
    assert out["zones"][zone]["shade_id"] == "none" and out["zones"][zone]["palette"] == []
    cats = [e["category"] for e in rcp.to_vto_effects(out)]
    assert palettes.ZONES[zone] not in cats and len(cats) == 9, "skin_smooth + eight zones"
    assert zone not in [x["zone"] for x in rcp.shade_list(out, _map())], "the artist has nothing to bring"


@pytest.mark.parametrize("zone", ["eyes", "lips", "cheeks", "brows", "lashes"])
def test_other_zones_cannot_be_left_out(zone):
    with pytest.raises(ValueError):
        rcp.apply_edit(_look(), zone, "shade:none")


def test_a_thin_zone_step_brings_its_own_strength():
    base = _look()
    step = next(s for s in palettes.ladder("light", "bronzer") if s.id != base["zones"]["bronzer"]["shade_id"])
    out = rcp.apply_edit(base, "bronzer", f"shade:{step.id}")
    assert out["zones"]["bronzer"]["intensity"] == step.intensity != base["zones"]["bronzer"]["intensity"]


def test_back_from_none_the_zone_gets_the_strength_of_the_shade():
    base = rcp.apply_edit(_look(), "bronzer", "shade:none")
    step = palettes.ladder("light", "bronzer")[0]
    assert rcp.apply_edit(base, "bronzer", f"shade:{step.id}")["zones"]["bronzer"]["intensity"] == step.intensity


def test_light_fresh_shows_nine_zones_and_sends_no_lip_liner_as_approved():
    r = _look("light", "fresh")
    assert len(r["zones"]) == 9 and r["zones"]["lip_line"]["shade_id"] == "none"
    assert "lip_liner" not in [e["category"] for e in rcp.to_vto_effects(r)]


# ---------------- finish ----------------
def test_finish_list():
    assert rcp.FINISHES == {"lips": ("matte", "satin", "gloss"), "eyes": ("matte", "shimmer", "metallic")}


def test_gloss_lips_follow_the_schema():
    lips = next(e for e in rcp.to_vto_effects(rcp.apply_edit(_look(), "lips", "finish:gloss"))
                if e["category"] == "lip_color")
    assert lips["palettes"] == [{"color": "#B96F78", "texture": "gloss", "colorIntensity": 68, "gloss": 50,
                                 "transparencyIntensity": 30}]


def test_matte_lips_carry_no_gloss_fields():
    lips = next(e for e in rcp.to_vto_effects(rcp.apply_edit(_look(), "lips", "finish:matte"))
                if e["category"] == "lip_color")
    assert lips["palettes"] == [{"color": "#B96F78", "texture": "matte", "colorIntensity": 68}]


def test_metallic_lids_follow_the_schema():
    eyes = rcp.to_vto_effects(rcp.apply_edit(_look(), "eyes", "finish:metallic"))[1]
    assert eyes["palettes"][0] == {"color": "#C98F7E", "texture": "metallic", "shimmerColor": "#C98F7E",
                                   "shimmerIntensity": 60, "metallicIntensity": 60, "colorIntensity": 80}
    assert eyes["palettes"][1] == {"color": "#5C342A", "texture": "matte", "colorIntensity": 78}


def test_matte_lids_send_no_shimmer():
    eyes = rcp.to_vto_effects(rcp.apply_edit(_look(), "eyes", "finish:matte"))[1]
    assert all(p["texture"] == "matte" and "shimmerIntensity" not in p for p in eyes["palettes"])


def test_finish_keeps_the_shade_and_the_strength():
    base = _look()
    z = rcp.apply_edit(base, "lips", "finish:gloss")["zones"]["lips"]
    assert z == {**base["zones"]["lips"], "texture": "gloss"}


def test_the_current_finish_is_not_a_change():
    base = _look()
    assert rcp.blocked(base, "lips", "finish:satin") == "current"
    assert rcp.blocked(base, "eyes", "finish:shimmer") == "current"
    assert rcp.blocked(base, "lips", "finish:gloss") is None


@pytest.mark.parametrize(("zone", "op"), [
    ("lips", "finish:metallic"), ("eyes", "finish:gloss"), ("cheeks", "finish:matte"), ("lips", "finish:"),
    ("look", "finish:matte")])
def test_a_finish_outside_the_list_is_refused(zone, op):
    with pytest.raises(ValueError):
        rcp.blocked(_look(), zone, op)


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
    ("look", "shade:ruby")])
def test_unknown_edits_are_rejected(zone, op):
    r = _look()
    with pytest.raises(ValueError):
        rcp.apply_edit(r, zone, op)
    with pytest.raises(ValueError):
        rcp.blocked(r, zone, op)


def test_edit_keys_are_stable_for_every_kind_of_edit():
    assert rcp.edit_key([]) == "base"
    two = [["cheeks", "shade:salmon"], ["lips", "finish:gloss"]]
    assert rcp.edit_key(two) == "cheeks:shade:salmon+lips:finish:gloss"
    assert rcp.edit_key([["look", "evening"]]) == "look:evening"
    r = _look()
    assert rcp.recipe_sha256(r) == rcp.recipe_sha256(json.loads(json.dumps(r)))


def test_quiet_keys_name_where_a_step_starts():
    base = _look()
    start = base["zones"]["lips"]["shade_id"]
    assert rcp.quiet_key(base, "lips", "softer") == f"lips:softer@{start}"
    assert rcp.quiet_key(base, "lips", "finish:gloss") == "lips:finish:gloss"
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


def test_add_edit_keeps_one_finish_and_a_new_shade_drops_it():
    base = _look()
    edits = rcp.add_edit(base, [], "lips", "finish:gloss")
    assert edits == [["lips", "finish:gloss"]]
    assert rcp.add_edit(base, edits, "lips", "finish:matte") == [["lips", "finish:matte"]]
    assert rcp.add_edit(base, edits, "lips", "finish:satin") == [], "the shade's own finish is no edit"
    assert rcp.add_edit(base, edits, "lips", "shade:ruby") == [["lips", "shade:ruby"]], "a finish belongs to its shade"


def test_add_edit_of_a_look_clears_the_rest_and_the_base_look_means_no_edit():
    base = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    edits = [["cheeks", "shade:salmon"], ["lips", "shade:peach-pink"]]
    assert rcp.add_edit(base, edits, "look", "evening") == [["look", "evening"]]
    assert rcp.add_edit(base, [["look", "evening"]], "look", "softglam") == []


def test_the_recorded_grid_is_every_circle_every_finish_and_two_looks():
    base = _look()
    keys = [rcp.edit_key(e) for e in rcp.record_grid(base)]
    assert len(keys) == len(set(keys)) == 38 + 4 + 2
    assert {"look:fresh", "look:evening", "lips:finish:gloss", "lips:finish:matte", "eyes:finish:matte",
            "eyes:finish:metallic", "bronzer:shade:none", "liner:shade:none"} <= set(keys)
    assert f"lips:shade:{base['zones']['lips']['shade_id']}" not in keys, "the base shade is the base render"
    assert "lips:finish:satin" not in keys and "eyes:finish:shimmer" not in keys, "the base finish is the base render"
    assert not [k for k in keys if "softer" in k or "bolder" in k], "Softer and Bolder are renders of circles"


def test_the_deep_grid_has_the_fourth_liner_step():
    keys = [rcp.edit_key(e) for e in rcp.record_grid(_look("deep"))]
    assert len(keys) == 39 + 4 + 2 and "liner:shade:bronze" in keys


# ---------------- the body ----------------
def test_body_on_nine_zones_follows_the_schema():
    effects = rcp.to_vto_effects(_look("deep"))
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
    lips = next(e for e in rcp.to_vto_effects(_look("light", "fresh")) if e["category"] == "lip_color")
    assert lips["palettes"] == [{"color": "#D98C86", "texture": "sheer", "colorIntensity": 55, "gloss": 45,
                                 "transparencyIntensity": 30}]


def test_a_matte_lid_shade_sends_no_shimmer():
    r = _look()
    matte = next(s for s in palettes.ladder("light", "eyes") if s.texture == "matte")
    eyes = rcp.to_vto_effects(rcp.apply_edit(r, "eyes", f"shade:{matte.id}"))[1]
    assert eyes["category"] == "eye_shadow"
    assert all(p["texture"] == "matte" and "shimmerIntensity" not in p for p in eyes["palettes"])


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
    r = _look()
    assert "foundation" not in [x["category"] for x in rcp.to_vto_effects(r)], "transfer-first looks have no foundation"
    with_even = rcp.to_vto_effects(r, {"skin_hex": "#dfa588", "coverage": 30})
    assert [x["category"] for x in with_even][:3] == ["skin_smooth", "foundation", "eye_shadow"]
    assert with_even[1] == rcp.even_out_effects("#dfa588", 30)[1], "the same foundation as the even-out step"
    assert with_even[1]["palettes"][0] == {"color": "#dfa588", "colorIntensity": 40, "glowIntensity": 20,
                                           "coverageIntensity": 30}


def test_shade_list_has_a_row_per_zone():
    rows = rcp.shade_list(_look(), _map())
    assert [x["zone"] for x in rows] == list(palettes.ZONES)
    lips = next(x for x in rows if x["zone"] == "lips")
    assert lips["label"] == "Lips" and lips["product_hex"] == "#B96F78" and lips["shade_name"] == "Dusty rose"
    assert lips["on_face_hex"] == "#a52b2d" and lips["coverage"] == 0.3 and lips["intensity"] == 68
    brows = next(x for x in rows if x["zone"] == "brows")
    assert brows["label"] == "Brows" and brows["on_face_hex"] is None and brows["coverage"] is None
    assert next(x for x in rows if x["zone"] == "eyes")["palette"] == ["#C98F7E", "#5C342A"]
