# Buttons that visibly change the face

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
of a step: **the 90th percentile of dE2000 >= 2.5**. A step below that is quiet: `quiet_edits` in the manifest,
no button, the server refuses it.

Why p90 and not a mean: a mean over the mask dilutes thin elements (a wing liner: mean 3.7, p90 10.5). Why it is the
right measure here: the look screen brings a chosen zone close up (2.3x on eyes and lips, 1.5x on cheeks), so the
strongest part of the zone is what she looks at. The threshold was checked by eye by the critic on close-up crops of
the recording.

| Sample | Measured | Quiet | No render |
|---|---|---|---|
| s0-champagne-rose | 58 | 0 | 0 |

## Measured (dE2000 in the zone)
| Sample | Zone | Edit | p90 | Mean | Verdict |
|---|---|---|---|---|---|
| s0-champagne-rose | wide | `eyes:shade:champagne` | 12.24 | 5.57 | shows |
| s0-champagne-rose | wide | `eyes:shade:warm-taupe` | 8.43 | 3.62 | shows |
| s0-champagne-rose | wide | `eyes:shade:bronze` | 5.79 | 2.84 | shows |
| s0-champagne-rose | wide | `eyes:shade:plum` | 10.86 | 5.27 | shows |
| s0-champagne-rose | wide | `eyes:shade:chocolate` | 13.93 | 6.48 | shows |
| s0-champagne-rose | thin | `liner:shade:flick` | 5.15 | 2.12 | shows |
| s0-champagne-rose | thin | `liner:shade:wing` | 9.62 | 3.58 | shows |
| s0-champagne-rose | thin | `lashes:shade:fluttery` | 9.38 | 4.15 | shows |
| s0-champagne-rose | thin | `lashes:shade:volume` | 10.22 | 4.50 | shows |
| s0-champagne-rose | thin | `brows:shade:soft` | 3.92 | 1.67 | shows |
| s0-champagne-rose | thin | `brows:shade:defined` | 4.26 | 1.96 | shows |
| s0-champagne-rose | wide | `cheeks:shade:peach` | 4.63 | 3.06 | shows |
| s0-champagne-rose | wide | `cheeks:shade:terracotta` | 3.47 | 2.39 | shows |
| s0-champagne-rose | wide | `cheeks:shade:brick` | 2.56 | 1.71 | shows |
| s0-champagne-rose | wide | `cheeks:shade:berry` | 3.12 | 2.06 | shows |
| s0-champagne-rose | thin | `highlight:shade:radiant` | 2.86 | 1.51 | shows |
| s0-champagne-rose | wide | `lips:shade:light-pink` | 12.76 | 9.61 | shows |
| s0-champagne-rose | wide | `lips:shade:peach-pink` | 13.58 | 10.40 | shows |
| s0-champagne-rose | wide | `lips:shade:rosy-peach` | 9.37 | 6.73 | shows |
| s0-champagne-rose | wide | `lips:shade:warm-coral` | 7.25 | 6.14 | shows |
| s0-champagne-rose | wide | `lips:shade:nude-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `lips:shade:rose-gloss` | 3.27 | 1.71 | shows |
| s0-champagne-rose | wide | `lips:shade:warm-rose` | 4.13 | 3.33 | shows |
| s0-champagne-rose | wide | `lips:shade:raspberry` | 9.39 | 7.26 | shows |
| s0-champagne-rose | wide | `lips:shade:ruby` | 15.27 | 10.67 | shows |
| s0-champagne-rose | thin | `lip_line:shade:defined` | 3.61 | 1.59 | shows |
| s0-champagne-rose | wide | `eyes:bolder@champagne` | 15.91 | 6.84 | shows |
| s0-champagne-rose | wide | `eyes:softer@warm-taupe` | 15.91 | 6.84 | shows |
| s0-champagne-rose | wide | `eyes:bolder@warm-taupe` | 8.43 | 3.62 | shows |
| s0-champagne-rose | wide | `eyes:softer@rose-gold` | 8.43 | 3.62 | shows |
| s0-champagne-rose | wide | `eyes:bolder@rose-gold` | 5.79 | 2.84 | shows |
| s0-champagne-rose | wide | `eyes:softer@bronze` | 5.79 | 2.84 | shows |
| s0-champagne-rose | wide | `eyes:bolder@bronze` | 13.92 | 5.77 | shows |
| s0-champagne-rose | wide | `eyes:softer@chocolate` | 13.93 | 6.48 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@peach` | 3.16 | 2.01 | shows |
| s0-champagne-rose | wide | `cheeks:softer@terracotta` | 3.16 | 2.01 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@terracotta` | 3.03 | 2.01 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@warm-rose` | 2.56 | 1.71 | shows |
| s0-champagne-rose | wide | `cheeks:softer@brick` | 2.56 | 1.71 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@brick` | 3.27 | 2.12 | shows |
| s0-champagne-rose | wide | `cheeks:softer@berry` | 3.27 | 2.12 | shows |
| s0-champagne-rose | wide | `lips:softer@light-pink` | 4.92 | 4.02 | shows |
| s0-champagne-rose | wide | `lips:bolder@light-pink` | 12.43 | 9.42 | shows |
| s0-champagne-rose | wide | `lips:bolder@peach-pink` | 4.64 | 3.81 | shows |
| s0-champagne-rose | wide | `lips:softer@rosy-peach` | 4.64 | 3.81 | shows |
| s0-champagne-rose | wide | `lips:bolder@rosy-peach` | 4.92 | 4.02 | shows |
| s0-champagne-rose | wide | `lips:softer@warm-coral` | 12.21 | 9.15 | shows |
| s0-champagne-rose | wide | `lips:bolder@warm-coral` | 5.23 | 4.55 | shows |
| s0-champagne-rose | wide | `lips:softer@nude-rose` | 12.43 | 9.42 | shows |
| s0-champagne-rose | wide | `lips:bolder@nude-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `lips:softer@dusty-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `lips:bolder@dusty-rose` | 4.13 | 3.33 | shows |
| s0-champagne-rose | wide | `lips:softer@rose-gloss` | 4.08 | 3.30 | shows |
| s0-champagne-rose | wide | `lips:bolder@rose-gloss` | 6.87 | 4.60 | shows |
| s0-champagne-rose | wide | `lips:softer@warm-rose` | 4.13 | 3.33 | shows |
| s0-champagne-rose | wide | `lips:softer@raspberry` | 7.95 | 6.26 | shows |
| s0-champagne-rose | wide | `lips:bolder@raspberry` | 6.64 | 4.58 | shows |
| s0-champagne-rose | wide | `lips:softer@ruby` | 6.64 | 4.58 | shows |
