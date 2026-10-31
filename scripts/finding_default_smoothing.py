#!/usr/bin/env python3
"""Platform finding evidence (1 unit): the same recipe as sample s1's recorded base render, but WITHOUT the
explicit skin_smooth effect -> Makeup VTO applies its default smoothing to the whole face. Compares the
forehead (no makeup) against the bare selfie for both renders. Writes docs/platform-findings/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from lookbrief import landmarks, makeup_map  # noqa: E402
from lookbrief import recipe as rcp  # noqa: E402
from lookbrief.color import delta_e76, srgb_to_lab  # noqa: E402
from lookbrief.config import youcam_key  # noqa: E402
from lookbrief.engine import image_ext  # noqa: E402
from lookbrief.youcam import YouCamClient, redact  # noqa: E402

SID = "s1-soft-glam"
OUT = ROOT / "docs" / "platform-findings"


def forehead_de(bare: np.ndarray, img_path: Path, face, size) -> float:
    arr = makeup_map.to_rgb_array(Image.open(img_path), size=size)
    skin = landmarks.zone_cells(face)["skin"]
    return round(float(np.median(delta_e76(srgb_to_lab(bare / 255), srgb_to_lab(arr / 255))[skin])), 2)


def main() -> int:
    sd = ROOT / "samples" / SID
    mf = json.loads((sd / "manifest.json").read_text())
    recipe = mf["steps"]["render:base"]["recipe"]
    effects = [e for e in rcp.to_vto_effects(recipe) if e["category"] != "skin_smooth"]
    out_img = next(OUT.glob(f"{SID}-default-smoothing.*"), None)
    if out_img is None:
        client = YouCamClient(youcam_key(), call_log=ROOT / "data" / "youcam-calls.jsonl")
        before = client.credit()
        fid = client.upload((sd / "bride.jpg").read_bytes(), "bride.jpg")
        res = client.run_task("makeup-vto", {"src_file_id": fid, "version": "1.0", "effects": effects})
        img = client.download(res.result_url)
        out_img = OUT / f"{SID}-default-smoothing{image_ext(img)}"
        out_img.write_bytes(img)
        (OUT / f"{SID}-default-smoothing.json").write_text(json.dumps(redact({
            "sample": SID, "task_id": res.task_id, "seconds": res.seconds, "units": res.units,
            "effects_sent": effects, "credit_before": before, "credit_after": client.credit()}), indent=1))
    bare_img = Image.open(sd / "bride.jpg").convert("RGB")
    bare = np.asarray(bare_img, dtype=np.uint8)
    face = landmarks.detect(bare)
    with_zero = forehead_de(bare, sd / mf["steps"]["render:base"]["image"], face, bare_img.size)
    default = forehead_de(bare, out_img, face, bare_img.size)
    print(json.dumps({"forehead_median_de76_vs_bare": {"skin_smooth_0": with_zero, "api_default": default}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
