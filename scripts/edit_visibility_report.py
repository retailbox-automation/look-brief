#!/usr/bin/env python3
"""Writes docs/EDITS.md: the edit rule and, per sample, how much each recorded edit changes its zone.

    uv run python scripts/edit_visibility_report.py
Numbers come from lookbrief.visibility (mean dE2000 inside the zone outline against the render without edits).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lookbrief import palettes  # noqa: E402
from lookbrief import recipe as rcp  # noqa: E402
from lookbrief import visibility as vis  # noqa: E402


def main() -> int:
    rows, pairs = [], []
    for sd in sorted((ROOT / "samples").glob("s*")):
        if not (sd / "manifest.json").exists():
            continue
        meta = json.loads((sd / "sample.json").read_text())
        if meta.get("hidden"):  # evidence of the old rule, recipe v1
            continue
        r = vis.edit_visibility(sd)
        for z in rcp.EDIT_ZONES:
            if z not in r["strength"]:
                continue
            cells = []
            for op in rcp.EDIT_OPS:
                e = r["edits"].get(f"{z}:{op}")
                cells.append(f"{e['mean']:.2f} ({e['share']:.0%})" if e else "off — on the edge")
            rows.append(f"| {sd.name} | {z} | {r['strength'][z]:.2f} | " + " | ".join(cells) + " |")
        worst = min(r["pairs"].items(), key=lambda kv: kv[1]["mean"])
        pairs.append(f"| {sd.name} | {len(r['pairs'])} | {worst[1]['mean']:.2f} ({worst[0]}) | "
                     f"{'PASS' if r['ok'] else 'FAIL'} |")
    md = f"""# Edits that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." Two causes:
the "Makeup + hair" preview showed the Hair Transfer photo and ignored edits (fixed in `static/session.js`: an edit
always switches to the view that carries it), and the recorded edits moved the zone by only dE2000 0.5–1.5
(Makeup VTO barely reacts to intensity +-20 or a shade +-8 L*).

## The edit rule (`src/lookbrief/recipe.py`, `src/lookbrief/palettes.py`)
- **Softer / Bolder:** strength only, in steps of {palettes.INTENSITY_STEP['lips']} on lips and eyes and
  {palettes.INTENSITY_STEP['cheeks']} on cheeks, inside the range of the zone for her skin group. A step that would
  leave the range turns the button off, and it says why.
- **Lighter / Deeper:** the neighbour step of the shade ladder, the same render as tapping that circle. The ends of the
  ladder turn the button off. No colour is computed: every colour sent is a step of the palette.

## The gate (`src/lookbrief/visibility.py`, `tests/test_edit_visibility.py`)
Inside the zone outline the app draws (open eye and mouth left out), against the re-render without edits: every
offered edit **mean dE2000 >= {vis.MIN_MEAN}** with **>= {vis.MIN_SHARE:.0%}** of pixels over {vis.JND}
(just noticeable); every pair of edits of one zone **>= {vis.MIN_PAIR_MEAN}** (tapping one button after another must
change the photo too). Thresholds checked by eye on 1:1 zone crops; the recordings of build b05012a failed it.
Each recorded recipe equals what `recipe.apply_edits` makes today (test), so Replay shows what the code does.

## Measured (mean dE2000 in the zone, share of pixels over {vis.JND})
| Sample | Zone | Whole makeup | Softer | Bolder | Lighter | Deeper |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

| Sample | Pairs of one zone | Closest pair | Gate |
|---|---|---|---|
{chr(10).join(pairs)}
"""
    (ROOT / "docs" / "EDITS.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
