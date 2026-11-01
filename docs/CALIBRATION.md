# Calibration of the first recipe rule (history)

> **History.** This page records how the first recipe, computed from the transfer, was calibrated. That rule is gone:
> the recipe is now ready-made shades in nine zones (`src/lookbrief/palettes.py`), the numbers below describe the
> earlier recipe on earlier renders, and `scripts/calibration_report.py` no longer reproduces them on today's samples
> (they were measured at commit cb2072b). The current distance from the transfer is in [ACCURACY.md](ACCURACY.md).

AI Makeup Transfer returns a picture, not makeup parameters. Look Brief measures the makeup from pixels and
writes an editable AI Makeup VTO recipe (`src/lookbrief/recipe.py`). How close the VTO re-render lands to the
transfer is measured, not assumed (`makeup_map.compare`: CIEDE2000 of median colours on the pixels the transfer
changed, per zone; coverage = share of the zone visibly changed, ΔE76 > 6).

## Before and after, on the three recorded samples

v1 rule (first pass): intensity from colour strength; product shade = skin + gain·(look − skin), gains 1.8 / 2.5 / 1.15.
v2 rule (then): intensity from the transfer's **coverage** (eyes 80 + 130·(cov − 0.325), cheeks 56 + 120·cov),
lips lifted by L* +8 (Makeup VTO lands lip colour darker than the hex it gets — every lip render was darker).

| Sample | Zone | v1 first pass | v1 re-rendered for the record | v2 (at commit cb2072b) | Transfer coverage | v1 coverage | v2 coverage |
|---|---|---|---|---|---|---|---|
| s1-soft-glam | eyes | 2.84 | 2.10 | 0.59 | 29% | 47% | 34% |
| s1-soft-glam | cheeks | 2.17 | 2.17 | 2.32 | 4% | 20% | 1% |
| s1-soft-glam | lips | 6.95 | 6.52 | 2.82 | 18% | 17% | 17% |
| s2-classic-red | eyes | 4.47 | 2.34 | 1.46 | 33% | 26% | 19% |
| s2-classic-red | cheeks | 2.64 | 2.64 | 2.84 | 9% | 26% | 17% |
| s2-classic-red | lips | 6.09 | 4.81 | 1.75 | 21% | 20% | 20% |
| s3-mauve-smoky | eyes | 1.55 | 1.26 | 1.00 | 48% | 39% | 38% |
| s3-mauve-smoky | cheeks | 2.19 | 2.15 | 2.49 | 10% | 23% | 15% |
| s3-mauve-smoky | lips | 4.77 | 4.77 | 2.45 | 23% | 23% | 23% |

Mean shade gap ΔE2000 over 9 zones, both measured on images in this repo: **v1 3.2 → v2 1.97**
(the first pass measured v1 at 3.74; those renders were replaced, only the numbers survive).
Makeup VTO is not deterministic for every effect: the identical v1 recipe rendered twice differs by up to
2.13 ΔE on eyelids and lips, while blush repeats within 0.04 (columns 3 and 4).
So a single-zone difference under ~1 ΔE is noise. Cheeks: v2 gives up 0.2–0.3 ΔE of shade for coverage much
closer to the transfer (v1 painted 2–5× the transfer's blush area).
v1 recipes: `docs/calibration/v1-recipes.json`; v1 re-renders with task IDs: `docs/calibration/*-v1-base.*`.
Reproduced at commit cb2072b with `uv run python scripts/calibration_report.py` (no API calls).

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
