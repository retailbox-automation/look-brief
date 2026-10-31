import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SAMPLE_IDS = sorted(p.name for p in SAMPLES.glob("s*") if (p / "manifest.json").exists())
VISIBLE_IDS = [s for s in SAMPLE_IDS if not json.loads((SAMPLES / s / "sample.json").read_text()).get("hidden")]


def load_rgb(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if size and img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)
