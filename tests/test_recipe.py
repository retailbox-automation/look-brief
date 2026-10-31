import json
from pathlib import Path

import pytest

from lookbrief import recipe as rcp
from lookbrief.color import hex_delta_e2000, hex_to_lab
from lookbrief.makeup_map import MakeupMap, ZoneStat

DOCS = json.loads((Path(__file__).parent / "fixtures" / "youcam_docs_snapshot.json").read_text())


def _map() -> MakeupMap:
    def z(name, cov, de, before, after):
        return ZoneStat(name, name.title(), 10000, int(cov * 10000), cov, de, after, before, 8.0)
    return MakeupMap(768, 1024, 0.1, 0.8, 0.3, {
        "eyes": z("eyes", 0.33, 11.0, "#aa806b", "#906551"),
        "cheeks": z("cheeks", 0.09, 6.5, "#dea38f", "#e79d8f"),
        "lips": z("lips", 0.21, 13.0, "#b16d67", "#b86a58"),
    })


def test_base_recipe_has_three_zones_with_valid_ranges():
    r = rcp.base_recipe(_map())
    assert set(r["zones"]) == {"eyes", "cheeks", "lips"}
    for z in r["zones"].values():
        assert 10 <= z["intensity"] <= 100 and z["color"].startswith("#") and len(z["color"]) == 7


def test_intensity_follows_coverage_not_strength():
    m = _map()
    lo = rcp.base_recipe(m)["zones"]["eyes"]["intensity"]
    m.zones["eyes"].coverage = 0.5
    hi = rcp.base_recipe(m)["zones"]["eyes"]["intensity"]
    assert hi > lo


def test_lip_shade_is_lifted_because_vto_lands_darker():
    m = _map()
    lips = rcp.base_recipe(m)["zones"]["lips"]
    assert hex_to_lab(lips["color"])[0] > hex_to_lab(m.zones["lips"].color_after)[0]


def test_vto_effects_match_documented_schema():
    eff = rcp.to_vto_effects(rcp.base_recipe(_map()))
    by = {e["category"]: e for e in eff}
    assert by["skin_smooth"] == {"category": "skin_smooth", "skinSmoothStrength": 0, "skinSmoothColorIntensity": 0}
    assert by["lip_color"]["style"] == {"type": "full"}, "lip_color without style -> HTTP 400"
    assert by["eye_shadow"]["pattern"]["name"] in DOCS["pattern_labels"]["eyeshadow"]
    assert by["blush"]["pattern"]["name"] in DOCS["pattern_labels"]["blush"]
    for e in eff:
        for p in e.get("palettes", []):
            assert p["texture"] == "matte" and 0 <= p["colorIntensity"] <= 100


def test_edits_move_in_the_right_direction():
    base = rcp.base_recipe(_map())
    soft = rcp.apply_edit(base, "cheeks", "softer")["zones"]["cheeks"]
    assert soft["intensity"] == base["zones"]["cheeks"]["intensity"] - rcp.INTENSITY_STEP
    light = rcp.apply_edit(base, "lips", "lighter")["zones"]["lips"]
    assert hex_to_lab(light["color"])[0] > hex_to_lab(base["zones"]["lips"]["color"])[0]
    deep = rcp.apply_edit(base, "lips", "deeper")["zones"]["lips"]
    assert hex_to_lab(deep["color"])[0] < hex_to_lab(base["zones"]["lips"]["color"])[0]
    assert base["zones"]["cheeks"]["intensity"] == rcp.base_recipe(_map())["zones"]["cheeks"]["intensity"], "no mutation"


def test_bolder_at_full_intensity_pushes_shade_from_skin():
    r = rcp.base_recipe(_map())
    r["zones"]["eyes"]["intensity"] = 100
    z0 = r["zones"]["eyes"]
    z1 = rcp.apply_edit(r, "eyes", "bolder")["zones"]["eyes"]
    assert z1["intensity"] == 100
    assert hex_delta_e2000(z1["color"], z0["skin"]) > hex_delta_e2000(z0["color"], z0["skin"])


def test_unknown_edit_rejected_and_keys_stable():
    r = rcp.base_recipe(_map())
    with pytest.raises(ValueError):
        rcp.apply_edit(r, "nose", "softer")
    with pytest.raises(ValueError):
        rcp.apply_edit(r, "lips", "glossier")
    assert rcp.edit_key([]) == "base"
    assert rcp.edit_key([["cheeks", "softer"], ["lips", "lighter"]]) == "cheeks:softer+lips:lighter"
    assert rcp.recipe_sha256(r) == rcp.recipe_sha256(json.loads(json.dumps(r)))
