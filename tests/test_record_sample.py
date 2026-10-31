"""The recording script on a fake client: nothing here reaches the API or spends a unit."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import ROOT, SAMPLES, SKIN
from PIL import Image

from lookbrief import recipe as rcp
from lookbrief.engine import ReplayEngine, hair_label
from lookbrief.youcam import UNITS, TaskResult


def before_the_grid(sample: str, dest: Path) -> Path:
    """A copy of the sample as it stood before its grid: transfers and hair kept, no render on the current recipe.
    The real sample may be half recorded or done by the time this runs."""
    shutil.copytree(SAMPLES / sample, dest)
    mf = json.loads((dest / "manifest.json").read_text())
    mf["steps"] = {k: v for k, v in mf["steps"].items() if not k.startswith("render:")}
    if mf.get("order") != "hair_first":
        mf["steps"]["hair_transfer"]["label"] = ""
    (dest / "manifest.json").write_text(json.dumps(mf))
    return dest


def dry(*args):
    env = {**os.environ, "YOUCAM_API_KEY": "", "LOOKBRIEF_KEYCHAIN": ""}
    return subprocess.run([sys.executable, "scripts/record_sample.py", *args, "--dry"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize(("sample", "renders", "units", "hair"), [
    ("s0-champagne-rose", 31, 31, False), ("s2-classic-red", 31, 33, True), ("s3-mauve-smoky", 29, 31, True)])
def test_dry_lists_the_grid_without_a_key(sample, renders, units, hair, tmp_path):
    r = dry(str(before_the_grid(sample, tmp_path / sample)), "--max-units", "230")
    assert r.returncode == 0, r.stderr
    assert f"renders {renders}" in r.stdout and f"units {units}" in r.stdout
    assert ("  hair_transfer" in r.stdout) is hair
    for must in ("render:base", "render:look:fresh", "render:look:evening", "render:highlight:shade:none",
                 "render:lashes:shade:fluttery", "render:liner:shade:wing"):
        assert must in r.stdout
    assert ":softer" not in r.stdout and ":bolder" not in r.stdout, "Softer and Bolder are renders of circles"
    assert "finish" not in r.stdout and "render:bronzer" not in r.stdout
    assert "mu_transfer" not in r.stdout, "the transfer is paid for"
    assert "even_out" not in r.stdout


def test_dry_keeps_the_base_shade_out_of_the_grid(tmp_path):
    s2, s0 = (before_the_grid(n, tmp_path / n) for n in ("s2-classic-red", "s0-champagne-rose"))
    assert "render:lips:shade:ruby" not in dry(str(s2)).stdout, "ruby is the base lip of s2"
    assert "render:lips:shade:ruby" in dry(str(s0)).stdout


def test_skin_of_the_samples_for_a_run_without_a_measured_map():
    expected = (("s0-champagne-rose", "#dfa588"), ("s2-classic-red", "#e4b29c"), ("s3-mauve-smoky", "#be8567"))
    for sample, skin in expected:
        r = dry(f"samples/{sample}")
        assert f"skin {skin}" in r.stdout, r.stdout[:200]


def test_dry_says_where_the_ceiling_stops_it(tmp_path):
    r = dry(str(before_the_grid("s3-mauve-smoky", tmp_path / "s3")), "--max-units", "25")
    assert r.returncode == 0 and "--max-units 25 stops it at 25 of 31 units" in r.stdout


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
    ("s0-champagne-rose", "light", "base.jpg"), ("s2-classic-red", "medium", "bride.jpg"),
    ("s3-mauve-smoky", "deep", "bride.jpg")])
def test_the_base_render_of_a_sample_is_the_approved_request(script, monkeypatch, tmp_path, sample, group, src):
    """From the pins through the whole chain to the bytes that would go out, foundation 40 instead of 50 included."""
    sd = before_the_grid(sample, tmp_path / sample)
    assert _record(script, monkeypatch, sd, 1) == 4
    want = json.loads((ROOT / "tests" / "fixtures" / "approved_looks.json").read_text())[group]["softglam"]
    assert rcp.canonical(FakeClient.bodies[0]["effects"]) == rcp.canonical(want)
    assert FakeClient.bodies[0]["src_file_id"] == f"file-{src}"


def test_a_grid_stops_at_the_ceiling_resumes_and_then_spends_nothing(script, monkeypatch, tmp_path):
    sd = before_the_grid("s3-mauve-smoky", tmp_path / "s3-mauve-smoky")
    old_transfer = (sd / "results" / "mu_transfer.jpg").read_bytes()
    base = rcp.look_recipe("deep", "softglam", SKIN["deep"])

    mf = json.loads((sd / "manifest.json").read_text())  # a render of an older rule must go, file and fixture too
    old = sd / "results" / "render__old.png"
    old.write_bytes(PNG.getvalue())
    (sd / "fixtures" / "render__old.json").write_text("{}")
    stale = {**mf["steps"]["mu_transfer"], "image": "results/render__old.png", "recipe": {"version": 1, "zones": {}}}
    mf["steps"]["render:cheeks:lighter"] = stale
    (sd / "manifest.json").write_text(json.dumps(mf))

    assert _record(script, monkeypatch, sd, 5) == 4, "stopped by the ceiling, not finished"
    assert _spent() == 5
    assert FakeClient.tasks[:2] == ["makeup-vto", "hair-transfer"], "the new base first, hair on it"
    steps = json.loads((sd / "manifest.json").read_text())["steps"]
    assert steps["render:base"]["recipe"] == base
    assert steps["hair_transfer"]["label"] == hair_label(base)
    assert all((s.get("recipe") or {"version": 2})["version"] == 2 for s in steps.values()), "no old render is left"
    assert not old.exists() and not (sd / "fixtures" / "render__old.json").exists(), "old files go with their steps"

    assert _record(script, monkeypatch, sd, 100) == 0
    assert _spent() == 31, "the second run only pays for what the first one did not record"
    assert FakeClient.tasks.count("mu-transfer") == 0 and FakeClient.tasks.count("hair-transfer") == 1
    assert (sd / "results" / "mu_transfer.jpg").read_bytes() == old_transfer
    keys = set(ReplayEngine(sd).recorded_render_keys())
    assert keys == {"base", *(rcp.edit_key(e) for e in rcp.record_grid(base))}

    assert _record(script, monkeypatch, sd, 100) == 0
    assert _spent() == 31, "a finished grid spends nothing"


def test_a_changed_shade_is_recorded_again_alone(script, monkeypatch, tmp_path):
    sd = before_the_grid("s3-mauve-smoky", tmp_path / "s3-mauve-smoky")
    assert _record(script, monkeypatch, sd, 100) == 0
    mf = json.loads((sd / "manifest.json").read_text())
    key = next(k for k in mf["steps"] if k.startswith("render:lips:shade:"))
    mf["steps"][key]["recipe"]["zones"]["lips"]["palette"] = ["#000000"]  # as if the palette changed under this render
    (sd / "manifest.json").write_text(json.dumps(mf))
    FakeClient.tasks.clear()
    assert _record(script, monkeypatch, sd, 100) == 0
    assert FakeClient.tasks == ["makeup-vto"]


def test_a_hair_first_sample_keeps_its_transfer_hair_and_even_out(script, monkeypatch, tmp_path):
    sd = before_the_grid("s0-champagne-rose", tmp_path / "s0-champagne-rose")
    kept = {n: (sd / "results" / n).read_bytes() for n in ("hair_transfer.jpg", "mu_transfer.jpg")}
    assert _record(script, monkeypatch, sd, 100) == 0
    assert set(FakeClient.tasks) == {"makeup-vto"} and _spent() == 31
    assert {n: (sd / "results" / n).read_bytes() for n in kept} == kept
