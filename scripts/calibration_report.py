#!/usr/bin/env python3
"""docs/CALIBRATION.md: transfer-vs-re-render gap for the v1 recipe rule (before) and the v2 rule (now).
Images only — no API calls. v1 renders: docs/calibration/<sample>-v1-base.*; v2: samples/<sample> render:base."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from lookbrief import landmarks, makeup_map  # noqa: E402

ZONES = ("eyes", "cheeks", "lips")
CAL = ROOT / "docs" / "calibration"


def gaps(sd: Path, render_path: Path) -> dict:
    mf = json.loads((sd / "manifest.json").read_text())
    bare_img = Image.open(sd / "bride.jpg").convert("RGB")
    bare = np.asarray(bare_img, dtype=np.uint8)
    face = landmarks.detect(bare)
    look = makeup_map.to_rgb_array(Image.open(sd / mf["steps"]["mu_transfer"]["image"]), size=bare_img.size)
    render = makeup_map.to_rgb_array(Image.open(render_path), size=bare_img.size)
    return makeup_map.compare(bare, look, render, face)["zones"]


def main() -> int:
    v1meta = json.loads((CAL / "v1-recipes.json").read_text())
    rows, v1all, v2all, firstall = [], [], [], []
    for sid in sorted(v1meta["recipes"]):
        sd = ROOT / "samples" / sid
        mf = json.loads((sd / "manifest.json").read_text())
        v1 = gaps(sd, next(CAL.glob(f"{sid}-v1-base.*[gp]")))
        v2 = gaps(sd, sd / mf["steps"]["render:base"]["image"])
        first = v1meta["first_pass_gaps_de2000"][sid]
        for z in ZONES:
            a, b = v1[z], v2[z]
            v1all.append(a["color_gap_de2000"])
            v2all.append(b["color_gap_de2000"])
            firstall.append(first[z])
            rows.append(
                f"| {sid} | {z} | {first[z]:.2f} | {a['color_gap_de2000']:.2f} | {b['color_gap_de2000']:.2f} | "
                f"{a['coverage_transfer'] * 100:.0f}% | {a['coverage_render'] * 100:.0f}% | {b['coverage_render'] * 100:.0f}% |"
            )
    m = lambda xs: round(float(np.mean(xs)), 2)  # noqa: E731
    text = f"""# Calibration of the editable recipe

AI Makeup Transfer returns a picture, not makeup parameters. Look Brief measures the makeup from pixels and
writes an editable AI Makeup VTO recipe (`src/lookbrief/recipe.py`). How close the VTO re-render lands to the
transfer is measured, not assumed (`makeup_map.compare`: CIEDE2000 of median colours on the pixels the transfer
changed, per zone; coverage = share of the zone visibly changed, ΔE76 > 6).

## Before and after, on the three recorded samples

v1 rule (first pass): intensity from colour strength; product shade = skin + gain·(look − skin), gains 1.8 / 2.5 / 1.15.
v2 rule (now): intensity from the transfer's **coverage** (eyes 80 + 130·(cov − 0.325), cheeks 56 + 120·cov),
lips lifted by L* +8 (Makeup VTO lands lip colour darker than the hex it gets — every lip render was darker).

| Sample | Zone | v1 first pass | v1 re-rendered for the record | v2 (replayed now) | Transfer coverage | v1 coverage | v2 coverage |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

Mean shade gap ΔE2000 over 9 zones, both measured on images in this repo: **v1 {m(v1all)} → v2 {m(v2all)}**
(the first pass measured v1 at {m(firstall)}; those renders were replaced, only the numbers survive).
Makeup VTO is not deterministic for every effect: the identical v1 recipe rendered twice differs by up to
{max(abs(a - b) for a, b in zip(firstall, v1all, strict=True)):.2f} ΔE on eyelids and lips, while blush repeats within 0.04 (columns 3 and 4).
So a single-zone difference under ~1 ΔE is noise. Cheeks: v2 gives up 0.2–0.3 ΔE of shade for coverage much
closer to the transfer (v1 painted 2–5× the transfer's blush area).
v1 recipes: `docs/calibration/v1-recipes.json`; v1 re-renders with task IDs: `docs/calibration/*-v1-base.*`.
Reproduce: `uv run python scripts/calibration_report.py` (no API calls).

## How v2 was found (data, not taste)

- Development sample (a Perfect Corp docs sample face with a Look VTO reference; not redistributed here): one base
  render plus three variants, 1 unit each. Blush at gain 2.5 / intensity 100 matched the transfer (ΔE 1.40,
  coverage 33% vs 34%); "Circle" blush patterns barely render (coverage 1%); "1color9"/"1color37" eye patterns
  were worse than "1color1". Same blush recipe rendered twice → identical numbers (1.40 / 33.4%); the same lip
  recipe varied 2.67–3.79 across renders with different eye/cheek settings — that is the noise floor.
- Recorded edit grid (12 single-zone edits × 3 samples = 36 re-renders, already paid for): "lips a shade lighter"
  closed the lip gap from 6.95 / 6.09 / 4.77 to 2.70 / 1.59 / 2.31 → the default became lighter; "eyes softer"
  matched coverage better when the transfer covered less → intensity follows coverage.
- `skin_smooth` explicitly 0: forehead (no makeup) ΔE76 vs bare selfie 0.36 on the development sample, against
  4.66 with the API default — the default beautifies the whole face, which a brief must not do.

## Spend

Development calibration 9 units; samples 90 units (first pass 51, re-recorded grid after calibration 39);
v1 re-renders for this page 3 units (`docs/calibration/v1-recording.json`).
"""
    (ROOT / "docs" / "CALIBRATION.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
