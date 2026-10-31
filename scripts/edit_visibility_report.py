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

from lookbrief import recipe as rcp  # noqa: E402
from lookbrief import visibility as vis  # noqa: E402


def main() -> int:
    rows, pairs = [], []
    for sd in sorted((ROOT / "samples").glob("s*")):
        if not (sd / "manifest.json").exists():
            continue
        meta = json.loads((sd / "sample.json").read_text())
        r = vis.edit_visibility(sd)
        for z in rcp.EDIT_ZONES:
            if z not in r["strength"]:
                continue
            cells = []
            for op in rcp.EDIT_OPS:
                e = r["edits"].get(f"{z}:{op}")
                cells.append(f"{e['mean']:.2f} ({e['share']:.0%})" if e else "off — already light")
            rows.append(f"| {sd.name}{' (hidden)' if meta.get('hidden') else ''} | {z} | {r['strength'][z]:.2f} | "
                        + " | ".join(cells) + " |")
        worst = min(r["pairs"].items(), key=lambda kv: kv[1]["mean"])
        pairs.append(f"| {sd.name} | {len(r['pairs'])} | {worst[1]['mean']:.2f} ({worst[0]}) | "
                     f"{'PASS' if r['ok'] else 'FAIL'} |")
    md = f"""# Edits that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." Two causes:
the "Makeup + hair" preview showed the Hair Transfer photo and ignored edits (fixed in `static/session.js`: an edit
always switches to the view that carries it), and the recorded edits moved the zone by only dE2000 0.5–1.5
(Makeup VTO barely reacts to intensity +-20 or a shade +-8 L*).

## The edit rule (`src/lookbrief/recipe.py`)
- **Softer:** product shade most of the way to her skin (eyes {rcp.SOFTER_KEEP['eyes']}, cheeks
  {rcp.SOFTER_KEEP['cheeks']}, lips {rcp.SOFTER_KEEP['lips']} of the distance kept), intensity x
  {rcp.SOFTER_INTENSITY['eyes']} / {rcp.SOFTER_INTENSITY['cheeks']} / {rcp.SOFTER_INTENSITY['lips']}.
  **Not offered** where the zone's whole makeup (bare face -> base render) is below {vis.LIGHT_ZONE}: softer cannot go
  past bare skin, so the button is off with "Softer: already close to your bare skin." (the server refuses it too).
- **Bolder:** a more vivid shade — chroma +{rcp.BOLDER_STEP['eyes']:.0f} / +{rcp.BOLDER_STEP['cheeks']:.0f} /
  +{rcp.BOLDER_STEP['lips']:.0f} (eyes / cheeks / lips), L* -{rcp.BOLDER_DARKEN['eyes']:.0f} /
  -{rcp.BOLDER_DARKEN['cheeks']:.0f} / -{rcp.BOLDER_DARKEN['lips']:.0f}, intensity +{rcp.INTENSITY_STEP}. Mostly chroma,
  so it never looks like lighter/deeper.
- **Lighter / Deeper:** L* +- {rcp.SHADE_STEP_L['eyes']:.0f} / {rcp.SHADE_STEP_L['cheeks']:.0f} /
  {rcp.SHADE_STEP_L['lips']:.0f}. Lighter lids end at least {rcp.LIGHTER_ABOVE_SKIN['eyes']:.0f} L* above her skin
  (or they read as softer); a deeper shade that hits L* {rcp.L_FLOOR:.0f} takes the rest of the step as chroma.

## The gate (`src/lookbrief/visibility.py`, `tests/test_edit_visibility.py`)
Inside the zone outline the app draws (open eye and mouth left out), against the re-render without edits: every
offered edit **mean dE2000 >= {vis.MIN_MEAN}** with **>= {vis.MIN_SHARE:.0%}** of pixels over {vis.JND}
(just noticeable); every pair of edits of one zone **>= {vis.MIN_PAIR_MEAN}** (tapping one button after another must
change the photo too). Thresholds checked by eye on 1:1 zone crops; the recordings of build b05012a failed it.
Each recorded recipe equals what `recipe.apply_edit` makes today (test), so Replay shows what the code does.

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
