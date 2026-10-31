import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SAMPLE_IDS = sorted(p.name for p in SAMPLES.glob("s*") if (p / "manifest.json").exists())
def _meta(s: str) -> dict:
    return json.loads((SAMPLES / s / "sample.json").read_text())


VISIBLE_IDS = [s for s in SAMPLE_IDS if not _meta(s).get("hidden") and not _meta(s).get("unlisted")]
UNLISTED_IDS = [s for s in SAMPLE_IDS if _meta(s).get("unlisted") and not _meta(s).get("hidden")]
HIDDEN_IDS = [s for s in SAMPLE_IDS if _meta(s).get("hidden")]


def bare_path(sd: Path, manifest: dict) -> Path:
    """The no-makeup reference the map is measured against: the selfie, or her face with the new hair (hair_first)."""
    if manifest.get("order") == "hair_first":
        return sd / manifest["steps"]["hair_transfer"]["image"]
    return sd / "bride.jpg"


def load_rgb(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if size and img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)
