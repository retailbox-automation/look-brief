"""Replay: zone choices stack. The maths on synthetic arrays, the choice of sources on literal keys, and a guard against
the real multi-zone renders the samples hold (Evening wears Wing and Volume on every lid shade)."""

import io
import json

import cv2
import numpy as np
import pytest
from helpers import SAMPLES, eye_area, geometry, load_rgb, recorded_samples, zone_gap
from PIL import Image

from lookbrief import layers, makeup_map, palettes
from lookbrief import recipe as rcp
from lookbrief.color import delta_e2000
from lookbrief.engine import ReplayEngine

SKIN = "#dfa588"
SOFT = rcp.base_recipe(None, "light", SKIN, "softglam")
EVENING = [["look", "evening"]]
FRESH = [["look", "fresh"]]


def pixel(*rgb: float) -> np.ndarray:
    return np.array([[rgb]], dtype=np.float32)


ONE = np.ones((1, 1), dtype=np.float32)


# ---------------- the blends, by hand ----------------
def test_ratio_scales_the_frame_by_what_the_zone_render_changed():
    assert layers.ratio(pixel(.5, .5, .5), pixel(.4, .4, .4), pixel(.2, .2, .2), ONE) == pytest.approx(.25)


def test_ratio_follows_the_mask():
    half = layers.ratio(pixel(.5, .5, .5), pixel(.4, .4, .4), pixel(.2, .2, .2), ONE * .5)
    assert half == pytest.approx(.375)
    assert layers.ratio(pixel(.5, .5, .5), pixel(.4, .4, .4), pixel(.2, .2, .2), ONE * 0) == pytest.approx(.5)


def test_ratio_can_lighten_a_removal():
    """Wing to Flick: the wing goes away, so the zone gets lighter than the frame."""
    assert layers.ratio(pixel(.1, .1, .1), pixel(.1, .1, .1), pixel(.3, .3, .3), ONE) == pytest.approx(.3)


def test_ratio_is_clipped_both_ways_and_floors_dark_pixels():
    assert layers.ratio(pixel(.01, .01, .01), pixel(0, 0, 0), pixel(1, 1, 1), ONE) == pytest.approx(.12)
    assert layers.ratio(pixel(.5, .5, .5), pixel(1, 1, 1), pixel(0, 0, 0), ONE) == pytest.approx(.015)


def test_alpha_paints_the_colour_as_far_as_the_render_moved_towards_it():
    out = layers.alpha(pixel(.8, .8, .8), pixel(.5, .5, .5), pixel(.25, .25, .25), ONE, pixel(0, 0, 0)[0, 0])
    assert out == pytest.approx(.4)


def test_alpha_never_lightens():
    c = pixel(.8, .8, .8)
    assert layers.alpha(c, pixel(.3, .3, .3), pixel(.6, .6, .6), ONE, pixel(0, 0, 0)[0, 0]) == pytest.approx(.8)


def test_core_keeps_the_depth_of_the_render_in_the_opaque_core():
    """The API paints darker than the recipe colour on dark lids: there the single render wins over the colour."""
    out = layers.core(pixel(.6, .6, .6), pixel(.6, .6, .6), pixel(.1, .1, .1), ONE, pixel(.2, .2, .2)[0, 0])
    assert out == pytest.approx(.1)


def test_core_is_alpha_below_the_core():
    args = (pixel(.8, .8, .8), pixel(.5, .5, .5), pixel(.4, .4, .4), ONE, pixel(.1, .1, .1)[0, 0])  # a = 0.25
    assert layers.core(*args) == pytest.approx(layers.alpha(*args))
    assert layers.core(*args) == pytest.approx(.625)


def test_liner_and_lashes_blend_differently():
    args = (pixel(.6, .6, .6), pixel(.6, .6, .6), pixel(.1, .1, .1), ONE, pixel(.2, .2, .2)[0, 0])
    assert layers.paint("liner", *args) == pytest.approx(.1)
    assert layers.paint("lashes", *args) == pytest.approx(.2)


# ---------------- compose ----------------
def _frame(h=40, w=60) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(30, 220, (h, w, 3), dtype=np.uint8)


def _plate(frame, target, mask, blend="ratio", zone="eyes", box=None, color=None) -> layers.Plate:
    y0, y1, x0, x1 = box or (0, frame.shape[0], 0, frame.shape[1])
    return layers.Plate(zone, blend, (y0, y1, x0, x1), mask[y0:y1, x0:x1], target[y0:y1, x0:x1], frame[y0:y1, x0:x1],
                        color)


def test_no_change_in_the_render_is_no_change_in_the_image():
    f = _frame()
    out = layers.compose(f, [_plate(f, f, np.ones(f.shape[:2], dtype=np.float32))])
    assert np.array_equal(out, f)


def test_every_level_survives_the_trip_through_linear_light():
    levels = np.arange(256, dtype=np.uint8).reshape(1, 256, 1).repeat(3, axis=2)
    assert np.array_equal(layers.to_pixels(layers.to_linear(levels)), levels)


def test_compose_is_deterministic():
    f, t = _frame(), np.clip(_frame().astype(int) - 40, 0, 255).astype(np.uint8)
    m = np.ones(f.shape[:2], dtype=np.float32) * .6
    assert layers.compose(f, [_plate(f, t, m)]).tobytes() == layers.compose(f, [_plate(f, t, m)]).tobytes()


def test_compose_leaves_every_pixel_outside_the_mask_alone():
    f, t = _frame(), np.zeros_like(_frame())
    m = np.zeros(f.shape[:2], dtype=np.float32)
    m[10:20, 10:20] = 1
    out = layers.compose(f, [_plate(f, t, m, box=(5, 25, 5, 25))])
    outside = m == 0
    assert np.array_equal(out[outside], f[outside])
    assert (out[10:20, 10:20] < f[10:20, 10:20]).all()


def test_compose_stacks_on_what_is_already_there():
    """A second layer lands on the first one, not on the frame."""
    f = np.full((4, 4, 3), 128, dtype=np.uint8)
    dark = np.full((4, 4, 3), 64, dtype=np.uint8)
    m = np.ones((4, 4), dtype=np.float32)
    once = layers.compose(f, [_plate(f, dark, m)])
    twice = layers.compose(f, [_plate(f, dark, m), _plate(f, dark, m)])
    assert (twice < once).all()


def test_the_soft_mask_on_a_crop_equals_the_one_on_the_whole_frame():
    """Work on crops must not change the mask: the pad has to hold the dilation and the tail of the blur."""
    zones = {"brows": np.zeros((200, 300), dtype=bool)}
    zones["brows"][60:90, 100:180] = True
    (y0, y1, x0, x1), soft = layers.soft_mask(zones, "brows")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    full = cv2.GaussianBlur(cv2.dilate(zones["brows"].astype(np.uint8), kernel).astype(np.float32), (0, 0), 4)
    assert soft == pytest.approx(full[y0:y1, x0:x1], abs=1e-4)
    assert soft.size < full.size / 2, "a crop, not the frame"
    cut = full.copy()
    cut[y0:y1, x0:x1] = 0
    assert cut.max() < 1e-3, "nothing of the mask is left outside the crop"


def test_the_soft_mask_of_liner_covers_lids_and_lashes_together():
    zones = {z: np.zeros((200, 300), dtype=bool) for z in ("eyes", "liner", "lashes")}
    zones["lashes"][50, 50] = True
    zones["eyes"][120, 240] = True
    box, soft = layers.soft_mask(zones, "liner")
    assert soft[50 - box[0], 50 - box[2]] > .5 and soft[120 - box[0], 240 - box[2]] > .5


# ---------------- which recorded render a zone comes from ----------------
GRID = {"base", "look:evening", "look:fresh", "eyes:shade:chocolate", "lips:shade:ruby", "liner:shade:wing",
        "liner:shade:flick", "lashes:shade:volume", "brows:shade:soft", "highlight:shade:radiant",
        "look:evening+eyes:shade:chocolate", "look:fresh+eyes:shade:chocolate", "look:fresh+lips:shade:ruby"}


def _stack(edits, keys=GRID):
    return layers.stack_of(SOFT, edits, keys)


def test_on_soft_glam_a_wide_zone_reads_against_the_base_render():
    s = _stack([["eyes", "shade:chocolate"], ["liner", "shade:wing"]])
    assert s.frame == "base"
    assert s.layers[0] == layers.Layer("eyes", "eyes:shade:chocolate", "base", "ratio")


def test_on_another_look_a_wide_zone_comes_from_that_look():
    s = _stack([*EVENING, ["eyes", "shade:chocolate"], ["liner", "shade:flick"]])
    assert s.frame == "look:evening"
    assert s.layers[0] == layers.Layer("eyes", "look:evening+eyes:shade:chocolate", "look:evening", "ratio")


def test_a_wide_zone_the_look_has_not_recorded_has_no_source():
    assert _stack([*EVENING, ["lips", "shade:ruby"], ["liner", "shade:flick"]]) is None


def test_a_liner_that_adds_to_the_frame_darkens():
    assert _stack([["eyes", "shade:chocolate"], ["liner", "shade:wing"]]).layers[1] == layers.Layer(
        "liner", "liner:shade:wing", "base", "core")


def test_lashes_that_add_to_the_frame_darken_with_alpha():
    assert _stack([["liner", "shade:wing"], ["lashes", "shade:volume"]]).layers[1] == layers.Layer(
        "lashes", "lashes:shade:volume", "base", "alpha")


def test_wing_to_flick_on_evening_is_a_removal_read_against_the_wing_single():
    s = _stack([*EVENING, ["liner", "shade:flick"]])
    assert s.layers == [layers.Layer("liner", "liner:shade:flick", "liner:shade:wing", "ratio")]


def test_soft_glams_own_style_on_evening_comes_from_the_base_render():
    s = _stack([*EVENING, ["liner", "shade:classic"]])
    assert s.layers == [layers.Layer("liner", "base", "liner:shade:wing", "ratio")]


def test_a_shade_the_look_wears_without_a_single_reads_against_the_base_render():
    """Classic wears a soft brown liner, recorded on no Soft glam single."""
    assert _stack([*FRESH, ["liner", "shade:wing"]]).layers == [
        layers.Layer("liner", "liner:shade:wing", "base", "core")]


def test_a_choice_that_could_not_change_the_photo_has_no_source():
    """Soft glam's own liner on Classic: render:base against render:base. The photo would stay, the tab would lie."""
    assert _stack([*FRESH, ["liner", "shade:classic"]]) is None


def test_a_look_with_no_frame_of_its_own_has_no_source():
    assert layers.stack_of(SOFT, EVENING, {"base"}) is None
    assert layers.stack_of(SOFT, [*EVENING, ["liner", "shade:flick"]], {"base", "liner:shade:flick"}) is None


def test_a_thin_zone_nobody_recorded_has_no_source():
    assert _stack([["liner", "shade:wing"], ["brows", "shade:defined"]]) is None


def test_brows_highlight_and_lip_line_use_the_ratio():
    keys = GRID | {"lip_line:shade:defined"}
    s = _stack([["brows", "shade:soft"], ["highlight", "shade:radiant"], ["lip_line", "shade:defined"]], keys)
    assert [(x.zone, x.blend) for x in s.layers] == [("brows", "ratio"), ("highlight", "ratio"), ("lip_line", "ratio")]


def test_a_changed_lip_decides_which_lip_liner_the_frame_wears():
    """On Evening the light group wears a ruby lip liner; a raspberry lip brings the plain one, and the render holds
    that one: a chosen lip liner reads against what is on the face, not what the look started with."""
    keys = {"base", "look:evening", "look:evening+lips:shade:raspberry", "lip_line:shade:defined",
            "lip_line:shade:ruby-line"}
    s = layers.stack_of(SOFT, [*EVENING, ["lips", "shade:raspberry"], ["lip_line", "shade:defined"]], keys)
    assert s.layers[1].reference == "base"
    without_lip = layers.stack_of(SOFT, [*EVENING, ["lip_line", "shade:defined"]], keys)
    assert without_lip.layers[0].reference == "lip_line:shade:ruby-line"


def test_zones_land_in_one_fixed_order_whatever_the_click_order():
    keys = GRID | {"cheeks:shade:berry", "lip_line:shade:defined", "brows:shade:defined"}
    clicks = [["lashes", "shade:volume"], ["lips", "shade:ruby"], ["liner", "shade:wing"], ["cheeks", "shade:berry"],
              ["brows", "shade:soft"], ["eyes", "shade:chocolate"], ["highlight", "shade:radiant"],
              ["lip_line", "shade:defined"]]
    assert [x.zone for x in _stack(clicks, keys).layers] == ["eyes", "brows", "cheeks", "highlight", "lips", "lip_line",
                                                            "liner", "lashes"]


def test_the_look_stays_first_in_the_canonical_order():
    edits = [["lashes", "shade:volume"], *EVENING, ["eyes", "shade:plum"]]
    assert layers.canonical(edits) == [*EVENING, ["eyes", "shade:plum"], ["lashes", "shade:volume"]]


def test_a_lip_liner_she_chose_survives_a_later_lip_in_either_click_order():
    """recipe.apply_edit makes the liner follow the lips, so the recipe of a stack must not depend on the clicks."""
    a = rcp.apply_edits(SOFT, layers.canonical([["lip_line", "shade:natural"], ["lips", "shade:ruby"]]))
    b = rcp.apply_edits(SOFT, layers.canonical([["lips", "shade:ruby"], ["lip_line", "shade:natural"]]))
    assert a == b and a["zones"]["lip_line"]["shade_id"] == "natural"


def test_the_file_name_ignores_the_click_order_and_stays_short():
    a = layers.file_name([["eyes", "shade:chocolate"], ["liner", "shade:wing"]])
    b = layers.file_name([["liner", "shade:wing"], ["eyes", "shade:chocolate"]])
    c = layers.file_name([["liner", "shade:wing"], ["eyes", "shade:plum"]])
    assert a == b and a != c
    assert a.endswith(".jpg") and len(a) <= 32


@pytest.mark.parametrize(("n", "text"), [
    (2, "Assembled from 2 recorded YouCam Makeup VTO results, one per zone"),
    (6, "Assembled from 6 recorded YouCam Makeup VTO results, one per zone"),
    (1, "Assembled from 1 recorded YouCam Makeup VTO result, one per zone"),
])
def test_the_caption_counts_the_zone_renders(n, text):
    assert layers.caption(n) == text


# ---------------- the real samples ----------------
LIDS = {"s0-champagne-rose": 6, "s2-classic-red": 6, "s3-mauve-smoky": 6}


def lid_shades(sample: str) -> list[str]:
    steps = geometry(sample)[0]["steps"]
    return [k.rsplit(":", 1)[1] for k in steps if k.startswith("render:look:evening+eyes:shade:")]


def stacked(sample: str, edits: list[list[str]]) -> np.ndarray:
    """The composed pixels, before the JPEG."""
    mf, face, _, _ = geometry(sample)
    base = mf["steps"]["render:base"]["recipe"]
    engine = ReplayEngine(SAMPLES / sample)
    stack = engine.stack_of(base, edits)
    assert stack is not None, edits
    return engine.compose(stack, rcp.apply_edits(base, layers.canonical(edits)), face)


def as_shipped(pixels: np.ndarray) -> np.ndarray:
    """What she gets: the same pixels through the JPEG."""
    return np.asarray(Image.open(io.BytesIO(layers.to_jpeg(pixels))).convert("RGB"), dtype=np.uint8)


def real(sample: str, key: str) -> np.ndarray:
    mf, _, _, size = geometry(sample)
    return load_rgb(SAMPLES / sample / mf["steps"][key]["image"], size)


def lid_wing_volume(sample: str, shade: str) -> list[list[str]]:
    base = geometry(sample)[0]["steps"]["render:base"]["recipe"]
    lid = [] if base["zones"]["eyes"]["shade_id"] == shade else [["eyes", f"shade:{shade}"]]
    return [*lid, ["liner", "shade:wing"], ["lashes", "shade:volume"]]


@pytest.mark.parametrize("sample", recorded_samples())
def test_every_sample_holds_six_lids_on_evening(sample):
    assert len(lid_shades(sample)) == LIDS[sample], "the guard below measures 18 real multi-zone renders"


def wing_pixels(sample: str) -> np.ndarray:
    """Where the Wing single moves the eye area a lot: 216-225 pixels, too thin for a statistic over the whole area."""
    base, wing = real(sample, "render:base"), real(sample, "render:liner:shade:wing")
    return eye_area(geometry(sample)[2]) & (delta_e2000(makeup_map._lab(base), makeup_map._lab(wing)) > 12)


AREA_MEAN, AREA_P95, WING_MEAN = 1.1, 4.5, 3.0  # the worst of the 18: 1.05, 4.25, 2.54


@pytest.mark.parametrize("sample", recorded_samples())
def test_the_stack_stays_close_to_the_real_render_of_the_same_zones(sample):
    """Lid + Wing + Volume on Soft glam against the real Evening render with that lid, on the composed pixels: the
    thresholds were set there. The JPEG has its own guard below."""
    area, wing = eye_area(geometry(sample)[2]), wing_pixels(sample)
    for shade in lid_shades(sample):
        truth = real(sample, f"render:look:evening+eyes:shade:{shade}")
        mine = stacked(sample, lid_wing_volume(sample, shade))
        mean, p95 = zone_gap(mine, truth, area)
        assert mean < AREA_MEAN and p95 < AREA_P95, (sample, shade, round(mean, 2), round(p95, 2))
        assert zone_gap(mine, truth, wing)[0] < WING_MEAN, (sample, shade, "wing")


@pytest.mark.parametrize("sample", recorded_samples())
def test_the_jpeg_she_gets_stays_close_too(sample):
    """JPEG 92 adds about 0.4: a real render through the same JPEG sits 0.84 from itself on average, 1.01 at worst."""
    area = eye_area(geometry(sample)[2])
    for shade in lid_shades(sample):
        mean, p95 = zone_gap(as_shipped(stacked(sample, lid_wing_volume(sample, shade))),
                             real(sample, f"render:look:evening+eyes:shade:{shade}"), area)
        assert mean < 1.5 and p95 < 4.6, (sample, shade, round(mean, 2), round(p95, 2))


@pytest.mark.parametrize("sample", recorded_samples())
def test_the_guard_fails_for_the_last_click_alone(sample):
    """The old answer to the same clicks is only the last render. The guard above must catch it, or it measures
    nothing: the wing pixels catch all six lids, the area five (the lid the look already wears differs by a thin wing,
    which is why the wing pixels are measured at all)."""
    area, wing = eye_area(geometry(sample)[2]), wing_pixels(sample)
    last_click = real(sample, "render:lashes:shade:volume")
    by_area = by_wing = 0
    for shade in lid_shades(sample):
        truth = real(sample, f"render:look:evening+eyes:shade:{shade}")
        mean, p95 = zone_gap(last_click, truth, area)
        by_area += mean >= AREA_MEAN or p95 >= AREA_P95
        by_wing += zone_gap(last_click, truth, wing)[0] >= WING_MEAN
    assert (by_area, by_wing) == (5, 6), (sample, by_area, by_wing)


@pytest.mark.parametrize("sample", recorded_samples())
def test_a_recipe_of_applied_edits_is_the_manifest_recipe_for_every_recorded_render(sample):
    steps = json.loads((SAMPLES / sample / "manifest.json").read_text())["steps"]
    base = steps["render:base"]["recipe"]
    for key, rec in steps.items():
        if key.startswith("render:") and key != "render:base":
            edits = [p.split(":", 1) for p in key.removeprefix("render:").split("+")]
            assert rcp.apply_edits(base, edits) == rec["recipe"], key


def test_no_style_zone_is_stepped_or_fixed():
    """layers treats the step zones as recorded per look and the other zones as recorded on Soft glam only."""
    assert set(layers.ORDER) == set(palettes.ZONES) - set(palettes.FIXED_ZONES)
    assert set(layers.ORDER) - set(palettes.STEP_ZONES) == set(palettes.STYLE_ZONES)
