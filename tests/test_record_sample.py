"""The recording script on a fake client: nothing here reaches the API or spends a unit."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys

import pytest
from helpers import ROOT, SAMPLES
from PIL import Image

from lookbrief import recipe as rcp
from lookbrief.engine import ReplayEngine, hair_label
from lookbrief.youcam import UNITS, TaskResult


def dry(*args):
    env = {**os.environ, "YOUCAM_API_KEY": "", "LOOKBRIEF_KEYCHAIN": ""}
    return subprocess.run([sys.executable, "scripts/record_sample.py", *args, "--dry"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize(("sample", "renders", "units", "hair"), [
    ("s0-champagne-rose", 55, 55, False), ("s2-classic-red", 55, 57, True), ("s3-mauve-smoky", 55, 57, True)])
def test_dry_lists_the_grid_without_a_key(sample, renders, units, hair):
    r = dry(f"samples/{sample}", "--max-units", "230")
    assert r.returncode == 0, r.stderr
    assert f"renders {renders}" in r.stdout and f"units {units}" in r.stdout
    assert ("  hair_transfer" in r.stdout) is hair
    for must in ("render:base", "render:look:fresh", "render:look:evening", "render:lips:softer"):
        assert must in r.stdout
    assert "mu_transfer" not in r.stdout, "the transfer is paid for"
    assert "even_out" not in r.stdout


def test_dry_keeps_the_base_shade_out_of_the_grid():
    assert "render:lips:shade:ruby" not in dry("samples/s2-classic-red").stdout, "ruby is the base lip of s2"
    assert "render:lips:shade:ruby" in dry("samples/s0-champagne-rose").stdout


def test_dry_says_where_the_ceiling_stops_it():
    r = dry("samples/s3-mauve-smoky", "--max-units", "25")
    assert r.returncode == 0 and "--max-units 25 stops it at 25 of 57 units" in r.stdout


def test_dry_without_pins_says_it_cannot_plan(tmp_path):
    sd = tmp_path / "x"
    sd.mkdir()
    (sd / "sample.json").write_text("{}")
    r = dry(str(sd))
    assert r.returncode == 2 and "recipe_pins" in r.stderr


PNG = io.BytesIO()
Image.new("RGB", (64, 64), (200, 120, 100)).save(PNG, format="PNG")


class FakeClient:
    tasks: list = []
    bodies: list = []

    def __init__(self, *a, **kw):
        pass

    def credit(self):
        return 500

    def upload(self, content, name, content_type="image/jpeg"):
        return f"file-{name}"

    def run_task(self, name, body, version=None):
        type(self).tasks.append(name)
        type(self).bodies.append(body)
        return TaskResult(name, f"task-{len(type(self).tasks)}", "fake://x", 1.0, UNITS[name], {})

    def download(self, url):
        return PNG.getvalue()


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("record_sample", ROOT / "scripts" / "record_sample.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)  # ledgers and work files stay out of the repo
    monkeypatch.setattr(mod, "YouCamClient", FakeClient)
    monkeypatch.setattr(mod, "youcam_key", lambda: "sk-fake")
    monkeypatch.setattr(FakeClient, "tasks", [])
    monkeypatch.setattr(FakeClient, "bodies", [])
    return mod


def _record(mod, monkeypatch, sd, units):
    monkeypatch.setattr(sys, "argv", ["record_sample.py", str(sd), "--max-units", str(units)])
    return mod.main()


def _spent():
    return sum(UNITS[t] for t in FakeClient.tasks)


@pytest.mark.parametrize(("sample", "group", "src"), [
    ("s0-champagne-rose", "light", "base.jpg"), ("s3-mauve-smoky", "deep", "bride.jpg")])
def test_the_base_render_of_a_sample_is_the_approved_request(script, monkeypatch, tmp_path, sample, group, src):
    """From the pins through the whole chain to the bytes that would go out, foundation 40 instead of 50 included."""
    sd = tmp_path / sample
    shutil.copytree(SAMPLES / sample, sd)
    assert _record(script, monkeypatch, sd, 1) == 4
    want = json.loads((ROOT / "tests" / "fixtures" / "approved_looks.json").read_text())[group]["softglam"]
    for e in want:
        if e["category"] == "foundation":
            e["palettes"][0]["colorIntensity"] = 40
    assert rcp.canonical(FakeClient.bodies[0]["effects"]) == rcp.canonical(want)
    assert FakeClient.bodies[0]["src_file_id"] == f"file-{src}"


def test_the_classic_red_sample_is_the_soft_glam_with_a_ruby_lip(script, monkeypatch, tmp_path):
    sd = tmp_path / "s2-classic-red"
    shutil.copytree(SAMPLES / sd.name, sd)
    assert _record(script, monkeypatch, sd, 1) == 4
    want = rcp.to_vto_effects(rcp.look_recipe("light", "softglam"))
    got = FakeClient.bodies[0]["effects"]
    lips = next(e for e in got if e["category"] == "lip_color")
    assert lips["palettes"][0]["color"] == "#B0102E"
    assert [e for e in got if e["category"] != "lip_color"] == [e for e in want if e["category"] != "lip_color"]


def test_a_grid_stops_at_the_ceiling_resumes_and_then_spends_nothing(script, monkeypatch, tmp_path):
    sd = tmp_path / "s3-mauve-smoky"
    shutil.copytree(SAMPLES / sd.name, sd)
    old_transfer = (sd / "results" / "mu_transfer.jpg").read_bytes()
    base = rcp.look_recipe("deep", "softglam")

    assert _record(script, monkeypatch, sd, 5) == 4, "stopped by the ceiling, not finished"
    assert _spent() == 5
    assert FakeClient.tasks[:2] == ["makeup-vto", "hair-transfer"], "the new base first, hair on it"
    steps = json.loads((sd / "manifest.json").read_text())["steps"]
    assert steps["render:base"]["recipe"] == base
    assert steps["hair_transfer"]["label"] == hair_label(base)
    assert all((s.get("recipe") or {"version": 2})["version"] == 2 for s in steps.values()), "no old render is left"
    assert not (sd / "results" / "render__cheeks__lighter.png").exists(), "old files go with their steps"
    assert not (sd / "fixtures" / "render__cheeks__lighter.json").exists()

    assert _record(script, monkeypatch, sd, 100) == 0
    assert _spent() == 57, "the second run only pays for what the first one did not record"
    assert FakeClient.tasks.count("mu-transfer") == 0 and FakeClient.tasks.count("hair-transfer") == 1
    assert (sd / "results" / "mu_transfer.jpg").read_bytes() == old_transfer
    keys = set(ReplayEngine(sd).recorded_render_keys())
    assert keys == {"base", *(rcp.edit_key(e) for e in rcp.record_grid(base))}

    assert _record(script, monkeypatch, sd, 100) == 0
    assert _spent() == 57, "a finished grid spends nothing"


def test_a_changed_shade_is_recorded_again_alone(script, monkeypatch, tmp_path):
    sd = tmp_path / "s3-mauve-smoky"
    shutil.copytree(SAMPLES / sd.name, sd)
    assert _record(script, monkeypatch, sd, 100) == 0
    mf = json.loads((sd / "manifest.json").read_text())
    key = next(k for k in mf["steps"] if k.startswith("render:lips:shade:"))
    mf["steps"][key]["recipe"]["zones"]["lips"]["palette"] = ["#000000"]  # as if the palette changed under this render
    (sd / "manifest.json").write_text(json.dumps(mf))
    FakeClient.tasks.clear()
    assert _record(script, monkeypatch, sd, 100) == 0
    assert FakeClient.tasks == ["makeup-vto"]


def test_a_hair_first_sample_keeps_its_transfer_hair_and_even_out(script, monkeypatch, tmp_path):
    sd = tmp_path / "s0-champagne-rose"
    shutil.copytree(SAMPLES / sd.name, sd)
    kept = {n: (sd / "results" / n).read_bytes() for n in ("hair_transfer.jpg", "mu_transfer.jpg")}
    assert _record(script, monkeypatch, sd, 100) == 0
    assert set(FakeClient.tasks) == {"makeup-vto"} and _spent() == 55
    assert {n: (sd / "results" / n).read_bytes() for n in kept} == kept
