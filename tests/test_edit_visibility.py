"""Every button must visibly change the face (Nadya on an iPhone, 31.10: "I tap lips, pick a strength, nothing
changes"). Measured on the recorded renders inside the zone (thresholds in lookbrief.visibility): a circle or a finish
against the base render, Softer and Bolder as the pair of shade renders they step between. A step that does not show
goes to `quiet_edits` in the manifest and gets no button (scripts/edit_visibility_report.py --write)."""

import json

import numpy as np
import pytest
from helpers import SAMPLES, SKIN, make_v2_samples, parse_edit_key, recorded_samples
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


def test_a_painted_circle_shows_and_its_neighbours_steps_show_with_it(synthetic):
    sd, steps = synthetic
    base = steps["render:base"]["recipe"]
    order = [s.id for s in palettes.skin_order("deep", "lips", base["skin_hex"])]
    start = base["zones"]["lips"]["shade_id"]
    next_ = order[order.index(start) + 1]
    _paint(sd, steps, f"render:lips:shade:{next_}", "lips")
    rep = visibility.edit_visibility(sd)
    assert f"lips:shade:{next_}" not in rep["quiet"]
    assert f"lips:bolder@{start}" not in rep["quiet"] and f"lips:softer@{next_}" not in rep["quiet"]
    assert f"lips:softer@{start}" in rep["quiet"], "the other way nothing changed"
    assert "lips:finish:gloss" in rep["quiet"]


def test_a_strong_change_on_a_small_part_of_the_zone_stays_quiet(synthetic):
    sd, steps = synthetic
    key = "render:cheeks:shade:salmon"
    if key not in steps:
        key = next(k for k in steps if k.startswith("render:cheeks:shade:"))
    _paint(sd, steps, key, "cheeks", share=0.3)
    e = visibility.edit_visibility(sd)["edits"][key.removeprefix("render:")]
    assert e["mean"] >= visibility.MIN_MEAN and e["share"] < visibility.MIN_SHARE and not e["ok"], e


def test_a_finish_is_measured_against_the_base(synthetic):
    sd, steps = synthetic
    _paint(sd, steps, "render:lips:finish:gloss", "lips")
    rep = visibility.edit_visibility(sd)
    assert "lips:finish:gloss" not in rep["quiet"] and "lips:finish:matte" in rep["quiet"]


def test_a_thin_zone_is_read_inside_its_own_mask(synthetic):
    sd, steps = synthetic
    _paint(sd, steps, "render:bronzer:shade:none", "bronzer")
    rep = visibility.edit_visibility(sd)
    assert "bronzer:shade:none" not in rep["quiet"]
    assert rep["edits"]["bronzer:shade:none"]["share"] > 0.9
    assert "highlight:shade:none" in rep["quiet"]


def test_bolder_from_none_is_measured_but_softer_never_lands_on_none(synthetic):
    sd, _ = synthetic
    rep = visibility.edit_visibility(sd)
    assert "bronzer:bolder@none" in rep["edits"]
    nearest = palettes.skin_order("deep", "bronzer", SKIN["deep"])[0].id
    assert f"bronzer:softer@{nearest}" not in rep["edits"]


def test_a_missing_render_is_reported(synthetic):
    sd, steps = synthetic
    steps.pop("render:lips:finish:gloss")
    (sd / "manifest.json").unlink()
    (sd / "manifest.json").write_text(json.dumps({"steps": steps, "order": "transfer_first"}))
    assert "lips:finish:gloss" in visibility.edit_visibility(sd)["missing"]


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
    assert mod.main() == 0
    mf = json.loads((tmp_path / "samples" / "s3-mauve-smoky" / "manifest.json").read_text())
    assert "quiet_edits" not in mf, "without --write the report only prints"
    assert (tmp_path / "docs" / "EDITS.md").exists()
    monkeypatch.setattr(sys, "argv", ["edit_visibility_report.py", "--write"])
    assert mod.main() == 0
    mf = json.loads((tmp_path / "samples" / "s3-mauve-smoky" / "manifest.json").read_text())
    assert "lips:finish:gloss" in mf["quiet_edits"] and "render:base" in mf["steps"], "the rest of the manifest stays"
    assert "quiet_edits" not in json.loads((SAMPLES / "s3-mauve-smoky" / "manifest.json").read_text())
