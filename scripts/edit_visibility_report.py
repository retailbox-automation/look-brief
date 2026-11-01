#!/usr/bin/env python3
"""Writes docs/EDITS.md: the edit rule and, per sample, how much each recorded button changes its zone.

    uv run python scripts/edit_visibility_report.py [--write]
Numbers come from lookbrief.visibility. --write also puts the steps that do not show into `quiet_edits` of each
sample's manifest.json: those buttons are not offered.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lookbrief import palettes  # noqa: E402
from lookbrief import visibility as vis  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write quiet_edits into each manifest.json")
    args = ap.parse_args()
    rows, totals = [], []
    for sd in sorted((ROOT / "samples").glob("s*")):
        mf_path = sd / "manifest.json"
        if not mf_path.exists():
            continue
        meta = json.loads((sd / "sample.json").read_text())
        mf = json.loads(mf_path.read_text())
        recipe = mf["steps"]["render:base"]["recipe"]
        if meta.get("hidden") or recipe["version"] != 2 or recipe["zones"]["eyes"]["pattern"] != palettes.EYE_PATTERN:
            print(f"{sd.name}: skipped (hidden or waits for re-recording)")
            continue
        r = vis.edit_visibility(sd)
        for key, e in r["edits"].items():
            zone = key.split(":", 1)[0]
            kind = "thin" if zone in palettes.STYLE_ZONES else "wide"
            rows.append(f"| {sd.name} | {kind} | `{key}` | {e['p90']:.2f} | {e['mean']:.2f} | "
                        f"{'shows' if e['ok'] else 'quiet'} |")
        totals.append(f"| {sd.name} | {len(r['edits'])} | {len(r['quiet'])} | {len(r['missing'])} |")
        if r["missing"]:
            print(f"{sd.name}: no render for {r['missing']}", file=sys.stderr)
        if args.write:
            mf["quiet_edits"] = r["quiet"]
            mf_path.write_text(json.dumps(mf, indent=1, ensure_ascii=False))
    md = f"""# Buttons that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." A probe of 14
units then showed why strength cannot be the button: intensity +-8-10 moves a zone by dE2000 0.6-1.3, and even 14 against
64 on the cheeks by 1.3-2.9.

## The edit rule (`src/lookbrief/recipe.py`, `src/lookbrief/palettes.py`)
- **Softer / Bolder** (lids, cheeks, lips): the next shade of the same colour family in the order of distance to her
  skin (CIEDE2000; lids: the lid colour). The same render as tapping that circle. The end of the way turns the button off.
- **Circles:** every shade of lids, cheeks and lips, metallic and gloss looks among them.
- **Styles:** liner, lashes, brows, highlighter and lip liner offer named steps with their own pattern and strength;
  the highlighter can be left out. Bronzer has no choice: a light warm layer that is part of the look.
No colour is computed: every colour sent is a shade of the palette.

## The gate (`src/lookbrief/visibility.py`, `tests/test_edit_visibility.py`)
Inside the mask of the zone (open eye and mouth left out), against the render without edits, or between the two shades
of a step: **the 90th percentile of dE2000 >= {vis.MIN_P90}**. A step below that is quiet: `quiet_edits` in the manifest,
no button, the server refuses it.

Why p90 and not a mean: a mean over the mask dilutes thin elements (a wing liner: mean 3.7, p90 10.5). Why it is the
right measure here: the look screen brings a chosen zone close up (2.3x on eyes and lips, 1.5x on cheeks), so the
strongest part of the zone is what she looks at. The threshold was checked by eye by the critic on close-up crops of
the recording.

| Sample | Measured | Quiet | No render |
|---|---|---|---|
{chr(10).join(totals)}

## Measured (dE2000 in the zone)
| Sample | Zone | Edit | p90 | Mean | Verdict |
|---|---|---|---|---|---|
{chr(10).join(rows)}
"""
    (ROOT / "docs" / "EDITS.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
