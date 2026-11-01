"""Every button must visibly change the face (Nadya on an iPhone, 31.10: "I tap lips, pick a strength, nothing
changes"). Measured on the recorded renders inside the zone (thresholds in lookbrief.visibility): a circle or a style
against the base render, Softer and Bolder as the pair of shade renders they step between. A step that does not show
goes to `quiet_edits` in the manifest and gets no button (scripts/edit_visibility_report.py --write)."""

import json

import numpy as np
import pytest
from helpers import SAMPLES, make_v2_samples, parse_edit_key, recorded_samples
from PIL import Image

from lookbrief import landmarks, palettes, visibility
from lookbrief import recipe as rcp


@pytest.fixture(scope="module", params=recorded_samples())
def report(request):
    return request.param, visibility.edit_visibility(SAMPLES / request.param)


def test_every_button_is_measured(report):
    sid, rep = report
    assert not rep["missing"], (sid, rep["missing"])


def test_the_quiet_list_is_what_the_recording_measures(report):
    sid, rep = report
    mf = json.loads((SAMPLES / sid / "manifest.json").read_text())
    assert sorted(mf.get("quiet_edits", [])) == sorted(rep["quiet"]), "run edit_visibility_report.py --write"


@pytest.fixture(scope="module")
def s3_face():
    rgb = np.asarray(Image.open(SAMPLES / "s3-mauve-smoky" / "bride.jpg").convert("RGB"), dtype=np.uint8)
    return landmarks.detect(rgb)


def test_every_zone_has_a_mask(s3_face):
    masks = visibility.zone_masks(s3_face)
    assert set(masks) == set(palettes.ZONES)
    assert all(int(m.sum()) > 150 for m in masks.values()), {k: int(v.sum()) for k, v in masks.items()}


def test_thin_masks_sit_where_their_product_lands(s3_face):
    m = visibility.zone_masks(s3_face)
    y = {z: float(np.nonzero(v)[0].mean()) for z, v in m.items()}
    assert y["brows"] < y["eyes"] < y["highlight"] < y["lips"], y
    assert y["brows"] < y["liner"] < y["highlight"], y
    assert not (m["liner"] & m["brows"]).any(), "the lid rim stops below the brow"
    assert int(m["liner"].sum()) < int(m["eyes"].sum()) / 2, "the rim is a thin band, not the lid"
    assert (m["lashes"] & m["liner"]).sum() == m["liner"].sum(), "lashes reach higher than the liner"


def test_the_lip_ring_follows_the_edge_of_the_lips(s3_face):
    m = visibility.zone_masks(s3_face)
    assert 0 < int((m["lip_line"] & m["lips"]).sum()) < int(m["lip_line"].sum()), "half on the lips, half around"
    assert int(m["lip_line"].sum()) < int(m["lips"].sum()), "a ring, not the lips"


def test_bronzer_has_its_mask_away_from_the_highlight(s3_face):
    m = visibility.zone_masks(s3_face)
    assert not (m["bronzer"] & m["highlight"]).any(), "probe r2: Bronzer1 is temples, hollows, chin, not the cheekbone"


@pytest.fixture
def synthetic(tmp_path):
    """Every render of the sample is the same image: nothing shows, unless a test paints one render."""
    sd = make_v2_samples(tmp_path / "samples") / "s3-mauve-smoky"
    steps = json.loads((sd / "manifest.json").read_text())["steps"]
    return sd, steps


def _paint(sd, steps, key, zone, share=1.0):
    """Replace one render by the base render with a share of the zone repainted."""
    img = Image.open(sd / steps["render:base"]["image"]).convert("RGB")
    bare = Image.open(sd / "bride.jpg").convert("RGB")
    masks = visibility.zone_masks(landmarks.detect(np.asarray(bare, dtype=np.uint8)))
    arr = np.asarray(img.resize(bare.size), dtype=np.uint8).copy()
    ys, xs = np.nonzero(masks[zone])
    keep = np.arange(len(ys)) < share * len(ys)
    arr[ys[keep], xs[keep]] = (40, 200, 90)
    Image.fromarray(arr).save(sd / f"{key.replace(':', '-')}.png")
    steps[key] = {**steps[key], "image": f"{key.replace(':', '-')}.png"}
    (sd / "manifest.json").unlink()
    (sd / "manifest.json").write_text(json.dumps({"steps": steps, "order": "transfer_first"}))


def test_a_render_that_changes_nothing_is_quiet(synthetic):
    sd, steps = synthetic
    rep = visibility.edit_visibility(sd)
    assert not rep["missing"] and rep["edits"]
    assert set(rep["quiet"]) == set(rep["edits"]), "must-differ control below: a painted render is not quiet"


def test_a_softer_that_ends_further_from_her_bare_skin_is_not_offered(synthetic):
    """Softer and Bolder are named for what they do to the photo: a step that goes the other way gets no button."""
    sd, steps = synthetic
    base = steps["render:base"]["recipe"]
    start = base["zones"]["lips"]["shade_id"]
    softer = palettes.step_from("deep", "lips", base["skin_hex"], start, "softer")
    _paint(sd, steps, f"render:lips:shade:{softer}", "lips")  # visible, and further from the bare lips than the base
    rep = visibility.edit_visibility(sd)
    step = rep["edits"][f"lips:softer@{start}"]
    assert step["p90"] >= visibility.min_p90("lips"), "must-differ control: the step shows, only its direction is wrong"
    assert step["wrong_way"] and f"lips:softer@{start}" in rep["quiet"]
    assert f"lips:shade:{softer}" not in rep["quiet"], "the circle itself stays: it only has no name of softer"


def test_a_painted_circle_shows_and_its_neighbours_steps_show_with_it(synthetic):
    sd, steps = synthetic
    base = steps["render:base"]["recipe"]
    start = base["zones"]["lips"]["shade_id"]
    next_ = palettes.step_from("deep", "lips", base["skin_hex"], start, "bolder")
    assert palettes.step_from("deep", "lips", base["skin_hex"], next_, "softer") == start
    _paint(sd, steps, f"render:lips:shade:{next_}", "lips")
    rep = visibility.edit_visibility(sd)
    assert f"lips:shade:{next_}" not in rep["quiet"]
    assert f"lips:bolder@{start}" not in rep["quiet"] and f"lips:softer@{next_}" not in rep["quiet"]
    assert f"lips:softer@{start}" in rep["quiet"], "the other way nothing changed"


def test_a_thin_line_counts_a_speck_does_not(synthetic):
    """The gate reads the 90th percentile: a mean over the mask dilutes a thin element (a wing liner: mean 3.7, p90
    10.5), and p90 still ignores a change on a few pixels."""
    sd, steps = synthetic
    thin, speck = "render:cheeks:shade:peach", "render:cheeks:shade:coral"
    keys = [k for k in steps if k.startswith("render:cheeks:shade:")]
    thin, speck = (thin if thin in steps else keys[0]), (speck if speck in steps else keys[1])
    _paint(sd, steps, thin, "cheeks", share=0.2)
    _paint(sd, steps, speck, "cheeks", share=0.05)
    edits = visibility.edit_visibility(sd)["edits"]
    line, dot = edits[thin.removeprefix("render:")], edits[speck.removeprefix("render:")]
    assert line["ok"] and line["p90"] >= visibility.MIN_P90
    assert not dot["ok"] and dot["p90"] == 0


def test_the_gate_is_the_90th_percentile_only():
    assert visibility.MIN_P90 == 2.5
    assert not hasattr(visibility, "MIN_MEAN") and not hasattr(visibility, "MIN_SHARE")


@pytest.mark.parametrize(("zone", "shows"), [("brows", False), ("lips", True), ("cheeks", True), ("lashes", True)])
def test_the_brows_ask_for_more_than_the_other_zones(zone, shows):
    a, b = np.full((50, 3), [50.0, 0.0, 0.0]), np.full((50, 3), [53.0, 0.0, 0.0])  # dE2000 3.0: between the thresholds
    stat = visibility._stat(a, b, zone)
    assert 2.5 < stat["p90"] < 3.5 and stat["ok"] is shows
    assert visibility.min_p90(zone) == (3.5 if zone == "brows" else 2.5)


def test_a_style_is_read_inside_its_own_mask(synthetic):
    sd, steps = synthetic
    _paint(sd, steps, "render:brows:shade:soft", "brows")
    rep = visibility.edit_visibility(sd)
    assert "brows:shade:soft" not in rep["quiet"]
    assert rep["edits"]["brows:shade:soft"]["p90"] > 10
    assert "highlight:shade:none" in rep["quiet"]


def test_softer_and_bolder_are_measured_on_lids_cheeks_and_lips_only(synthetic):
    sd, _ = synthetic
    keys = [k for k in visibility.edit_visibility(sd)["edits"] if "@" in k]
    assert {k.rsplit("+", 1)[-1].split(":")[0] for k in keys} == {"eyes", "cheeks", "lips"}
    assert any(k.startswith("look:evening+lips:") for k in keys), "the steps of another look are measured on that look"


def test_a_missing_render_is_reported(synthetic):
    sd, steps = synthetic
    steps.pop("render:lips:shade:rose-gloss", steps.pop("render:lips:shade:berry-gloss", None))
    (sd / "manifest.json").unlink()
    (sd / "manifest.json").write_text(json.dumps({"steps": steps, "order": "transfer_first"}))
    assert "lips:shade:berry-gloss" in visibility.edit_visibility(sd)["missing"]


def test_the_metric_sees_a_real_change_and_ignores_none():
    """Must-differ control of the metric itself: the base render against itself is 0, against the transfer it is not."""
    from lookbrief import makeup_map
    from lookbrief.color import delta_e2000

    sd = SAMPLES / "s2-classic-red"
    steps = json.loads((sd / "manifest.json").read_text())["steps"]
    bare = Image.open(sd / "bride.jpg").convert("RGB")
    masks = visibility.zone_masks(landmarks.detect(np.asarray(bare, dtype=np.uint8)))

    def lab(k):
        return makeup_map._lab(makeup_map.to_rgb_array(Image.open(sd / steps[k]["image"]), size=bare.size))

    base, transfer = lab("render:base"), lab("mu_transfer")
    assert float(delta_e2000(base[masks["lips"]], base[masks["lips"]]).max()) == 0.0
    assert float(delta_e2000(base[masks["lips"]], transfer[masks["lips"]]).mean()) > 3.0


@pytest.mark.parametrize("sid", recorded_samples())
def test_recorded_edit_recipes_follow_the_edit_rule(sid):
    """Replay serves what was recorded: each recorded render must be exactly what recipe.apply_edits makes today
    (a changed palette with stale recordings would show one thing and claim another)."""
    steps = json.loads((SAMPLES / sid / "manifest.json").read_text())["steps"]
    base = steps["render:base"]["recipe"]
    stale = [key for key, rec in steps.items() if key.startswith("render:")
             and rec["recipe"] != rcp.apply_edits(base, parse_edit_key(key))]
    assert not stale, f"{sid}: recorded under an older palette: {stale}"


def test_report_writes_the_quiet_list_into_the_manifest(tmp_path, monkeypatch):
    import importlib.util
    import sys

    from helpers import ROOT
    path = ROOT / "scripts" / "edit_visibility_report.py"
    spec = importlib.util.spec_from_file_location("edit_visibility_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    make_v2_samples(tmp_path / "samples")
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["edit_visibility_report.py"])
    real = (SAMPLES / "s3-mauve-smoky" / "manifest.json").read_bytes()
    assert mod.main() == 0
    mf = json.loads((tmp_path / "samples" / "s3-mauve-smoky" / "manifest.json").read_text())
    assert "quiet_edits" not in mf, "without --write the report only prints"
    assert (tmp_path / "docs" / "EDITS.md").exists()
    monkeypatch.setattr(sys, "argv", ["edit_visibility_report.py", "--write"])
    assert mod.main() == 0
    mf = json.loads((tmp_path / "samples" / "s3-mauve-smoky" / "manifest.json").read_text())
    assert "lips:shade:plum" in mf["quiet_edits"] and "render:base" in mf["steps"], "the rest of the manifest stays"
    assert (SAMPLES / "s3-mauve-smoky" / "manifest.json").read_bytes() == real, "the real sample is not touched"
