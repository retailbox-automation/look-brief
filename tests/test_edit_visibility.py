"""Every edit button must visibly change the face (Nadya on an iPhone, 31.10: "I tap lips, pick a strength,
nothing changes"). Measured on the recorded renders: each offered edit against the render without edits, inside
the zone outline, and every pair of edits of one zone against each other (thresholds in lookbrief.visibility).
These tests failed on the recordings of b05012a (edits moved the zone by dE2000 0.5-1.5)."""

import pytest
from helpers import SAMPLE_IDS, SAMPLES

from lookbrief import visibility


@pytest.fixture(scope="module", params=SAMPLE_IDS)
def report(request):
    return request.param, visibility.edit_visibility(SAMPLES / request.param)


def test_every_offered_edit_is_recorded(report):
    """12 edits minus "softer" on zones too light to soften visibly (decision B, 31.10)."""
    sid, rep = report
    assert not rep["missing"], (sid, rep["missing"])
    light = [z for z, v in rep["strength"].items() if v < visibility.LIGHT_ZONE]
    assert len(rep["edits"]) == 12 - len(light), (sid, sorted(rep["edits"]), light)


def test_each_edit_visibly_changes_its_zone(report):
    sid, rep = report
    weak = {k: v for k, v in rep["edits"].items() if not v["ok"]}
    assert not weak, f"{sid}: edits that barely change the photo (need mean dE2000 >= {visibility.MIN_MEAN} and " \
                     f">= {visibility.MIN_SHARE:.0%} of pixels over {visibility.JND}): {weak}"


def test_switching_between_edits_of_a_zone_changes_the_photo(report):
    sid, rep = report
    weak = {k: v for k, v in rep["pairs"].items() if not v["ok"]}
    assert not weak, f"{sid}: two buttons of one zone give nearly the same photo (need mean dE2000 >= " \
                     f"{visibility.MIN_PAIR_MEAN}): {weak}"


def test_the_metric_sees_a_real_change_and_ignores_none():
    """Must-differ control of the metric itself: the base render against itself is 0, against the transfer it is not."""
    import json

    import numpy as np
    from PIL import Image

    from lookbrief import landmarks, makeup_map
    from lookbrief.color import delta_e2000

    sd = SAMPLES / "s2-classic-red"
    steps = json.loads((sd / "manifest.json").read_text())["steps"]
    bare = Image.open(sd / "bride.jpg").convert("RGB")
    masks = visibility.zone_masks(landmarks.detect(np.asarray(bare, dtype=np.uint8)))

    def lab(k):
        return makeup_map._lab(makeup_map.to_rgb_array(Image.open(sd / steps[k]["image"]), size=bare.size))

    base, transfer = lab("render:base"), lab("mu_transfer")
    assert float(delta_e2000(base[masks["lips"]], base[masks["lips"]]).max()) == 0.0
    assert float(delta_e2000(base[masks["lips"]], transfer[masks["lips"]]).mean()) > visibility.MIN_PAIR_MEAN


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_recorded_edit_recipes_follow_the_edit_rule(sid):
    """Replay serves what was recorded: each recorded edit must be exactly what recipe.apply_edit makes today
    (a changed step with stale recordings would show one thing and claim another)."""
    import json

    from lookbrief import recipe as rcp

    steps = json.loads((SAMPLES / sid / "manifest.json").read_text())["steps"]
    base = steps["render:base"]["recipe"]
    stale = []
    for key, rec in steps.items():
        if not key.startswith("render:") or key == "render:base":
            continue
        zone, op = key.split(":")[1:]
        want = rcp.apply_edit(base, zone, op)["zones"][zone]
        got = rec["recipe"]["zones"][zone]
        if (want["color"], want["intensity"]) != (got["color"], got["intensity"]):
            stale.append((key, got["color"], got["intensity"], want["color"], want["intensity"]))
    assert not stale, f"{sid}: recorded edits made under an older rule: {stale}"
