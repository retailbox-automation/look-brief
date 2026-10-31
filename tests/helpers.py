import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lookbrief import recipe as rcp

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SAMPLE_IDS = sorted(p.name for p in SAMPLES.glob("s*") if (p / "manifest.json").exists())
def _meta(s: str) -> dict:
    return json.loads((SAMPLES / s / "sample.json").read_text())


VISIBLE_IDS = [s for s in SAMPLE_IDS if not _meta(s).get("hidden") and not _meta(s).get("unlisted")]
UNLISTED_IDS = [s for s in SAMPLE_IDS if _meta(s).get("unlisted") and not _meta(s).get("hidden")]
HIDDEN_IDS = [s for s in SAMPLE_IDS if _meta(s).get("hidden")]
SKIN = {"light": "#dfa588", "medium": "#c8956d", "olive": "#c4a070", "deep": "#be8567"}  # foreheads; s0 and s3 are real


def _recipe_version(s: str) -> int:
    return json.loads((SAMPLES / s / "manifest.json").read_text())["steps"]["render:base"]["recipe"]["version"]


def recorded_samples(ids: list[str] | None = None) -> list:
    """Offered samples for tests on the recorded renders. A sample still holding recipe v1 waits for its re-recording
    (skipped by name, runs by itself once the manifest is v2). Hidden s1 stays as evidence of the old rule."""
    return [s if _recipe_version(s) == 2 else pytest.param(s, marks=pytest.mark.skip(f"{s}: waits for re-recording"))
            for s in (VISIBLE_IDS if ids is None else ids)]


def parse_edit_key(key: str) -> list[list[str]]:
    """render:lips:shade:ruby -> [["lips", "shade:ruby"]]; render:base -> []."""
    body = key.removeprefix("render:")
    return [] if body == "base" else [p.split(":", 1) for p in body.split("+")]


def make_v2_samples(dest: Path) -> Path:
    """A samples folder with the recipe v2 contract on the recorded images: every planned render is the old base
    render, so the app and pipeline tests can run before (and independently of) the real re-recording. It proves the
    contract, not the look. Hidden samples stay as they are, recipe v1 included."""
    dest.mkdir(parents=True, exist_ok=True)
    for sd in sorted(p for p in SAMPLES.glob("s*") if (p / "manifest.json").exists()):
        out = dest / sd.name
        meta = _meta(sd.name)
        if meta.get("hidden"):
            out.symlink_to(sd, target_is_directory=True)
            continue
        out.mkdir()
        for child in sd.iterdir():
            if child.name != "manifest.json":
                (out / child.name).symlink_to(child)
        mf = json.loads((sd / "manifest.json").read_text())
        steps = {k: v for k, v in mf["steps"].items() if not k.startswith("render:")}
        pins = meta["recipe_pins"]
        skin = mf["map"]["zones"]["skin"]["color_before"]
        base = rcp.base_recipe(None, pins["group"], skin, pins["look"], pins["shades"])
        old = mf["steps"]["render:base"]
        for edits in [[], *rcp.record_grid(base)]:
            steps[f"render:{rcp.edit_key(edits)}"] = {**old, "recipe": rcp.apply_edits(base, edits)}
        (out / "manifest.json").write_text(json.dumps({**mf, "steps": steps}))
    return dest


def bare_path(sd: Path, manifest: dict) -> Path:
    """The no-makeup reference the map is measured against: the selfie, or her face with the new hair (hair_first)."""
    if manifest.get("order") == "hair_first":
        return sd / manifest["steps"]["hair_transfer"]["image"]
    return sd / "bride.jpg"


def reference_path(sd: Path, manifest: dict) -> Path:
    """The look the map and the accuracy are read from: the evened look for hair-first samples with the
    even-out step (src/lookbrief/pipeline.map_reference), else the Makeup Transfer result."""
    if manifest.get("order") == "hair_first" and "even_out" in manifest["steps"]:
        return sd / manifest["steps"]["even_out"]["image"]
    return sd / manifest["steps"]["mu_transfer"]["image"]


def load_rgb(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if size and img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)
