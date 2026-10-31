import json

import numpy as np
import pytest
from conftest import SAMPLE_IDS, SAMPLES, load_rgb

from lookbrief import landmarks, makeup_map
from lookbrief.color import hex_delta_e2000


@pytest.fixture(scope="module", params=SAMPLE_IDS)
def sample(request):
    sd = SAMPLES / request.param
    mf = json.loads((sd / "manifest.json").read_text())
    bare = load_rgb(sd / "bride.jpg")
    look = load_rgb(sd / mf["steps"]["mu_transfer"]["image"], size=(bare.shape[1], bare.shape[0]))
    face = landmarks.detect(bare)
    return sd, mf, bare, look, face


def test_face_found_frontal(sample):
    _, _, _, _, face = sample
    assert face is not None and face.face_count == 1
    assert abs(face.yaw_deg) < 15 and abs(face.pitch_deg) < 20


def test_zone_cells_are_disjoint_and_ordered(sample):
    _, _, _, _, face = sample
    cells = landmarks.zone_cells(face)
    stack = np.stack([c.astype(int) for c in cells.values()])
    assert stack.sum(axis=0).max() <= 1, "a pixel belongs to two zones"
    ys = {z: np.nonzero(cells[z])[0].mean() for z in ("skin", "eyes", "cheeks", "lips")}
    assert ys["skin"] < ys["eyes"] < ys["cheeks"] < ys["lips"]


def test_map_finds_makeup_and_keeps_skin(sample):
    _, _, bare, look, face = sample
    m = makeup_map.compute(bare, look, face)
    for z in ("eyes", "lips"):
        assert m.zones[z].changed_px > 500 and m.zones[z].delta_e2000 > 2
    assert m.skin_control_de < 1.5, "forehead (no makeup) must stay unchanged by the transfer"
    assert m.explained_share > 0.5


def test_recorded_map_reproduces_on_this_machine(sample):
    """Replay serves the map stored at recording time; recomputing here must agree (cross-platform check)."""
    _, mf, bare, look, face = sample
    now = makeup_map.compute(bare, look, face)
    rec = makeup_map.MakeupMap.from_dict(mf["map"])
    for z in ("eyes", "cheeks", "lips"):
        assert hex_delta_e2000(now.zones[z].color_after, rec.zones[z].color_after) < 1.5
        assert abs(now.zones[z].coverage - rec.zones[z].coverage) < 0.05


def test_compare_is_zero_for_identical_and_bounded_for_render(sample):
    sd, mf, bare, look, face = sample
    same = makeup_map.compare(bare, look, look, face)
    assert all(g["color_gap_de2000"] == 0 for g in same["zones"].values())
    render = load_rgb(sd / mf["steps"]["render:base"]["image"], size=(bare.shape[1], bare.shape[0]))
    gaps = makeup_map.compare(bare, look, render, face)
    for g in gaps["zones"].values():
        assert 0 < g["color_gap_de2000"] < 8
        assert 0 <= g["coverage_render"] <= 1
    assert gaps["skin_control_render_de76"] < 1.5, "skin_smooth=0 must leave the forehead untouched"


def test_size_mismatch_is_rejected():
    a = np.zeros((10, 10, 3), np.uint8)
    b = np.zeros((10, 11, 3), np.uint8)
    with pytest.raises(ValueError):
        makeup_map.compute(a, b, None)  # type: ignore[arg-type]


def test_no_face_on_noise():
    rng = np.random.default_rng(0)
    assert landmarks.detect(rng.integers(0, 255, (512, 384, 3), dtype=np.uint8)) is None
