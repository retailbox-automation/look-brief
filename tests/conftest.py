from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
SAMPLE_IDS = sorted(p.name for p in SAMPLES.glob("s*") if (p / "manifest.json").exists())


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLES / SAMPLE_IDS[0]


def load_rgb(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if size and img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)
