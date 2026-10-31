# Buttons that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." A probe of 14
units then showed why strength cannot be the button: intensity +-8-10 moves a zone by dE2000 0.6-1.3, and even 14 against
64 on the cheeks by 1.3-2.9.

## The edit rule (`src/lookbrief/recipe.py`, `src/lookbrief/palettes.py`)
- **Softer / Bolder** (lids, cheeks, lips): the next shade of the same colour family in the order of distance to her
  skin (CIEDE2000; lids: the lid colour). The same render as tapping that circle. The end of the way turns the button off.
- **Circles:** every shade of lids, cheeks and lips, gloss and metallic among them.
- **Styles:** liner, lashes, brows, bronzer, highlighter and lip liner offer named steps with their own pattern and
  strength; liner, highlighter and lip liner can be left out.
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
| s0-champagne-rose | 74 | 15 | 0 |

## Measured (dE2000 in the zone)
| Sample | Zone | Edit | p90 | Mean | Verdict |
|---|---|---|---|---|---|
| s0-champagne-rose | wide | `eyes:shade:champagne-glow` | 4.08 | 1.44 | shows |
| s0-champagne-rose | wide | `eyes:shade:peach-bronze` | 2.53 | 1.05 | shows |
| s0-champagne-rose | wide | `eyes:shade:warm-taupe` | 3.17 | 1.16 | shows |
| s0-champagne-rose | wide | `eyes:shade:copper` | 1.77 | 0.79 | quiet |
| s0-champagne-rose | wide | `eyes:shade:rose-brown` | 2.60 | 1.06 | shows |
| s0-champagne-rose | wide | `eyes:shade:plum-brown` | 2.95 | 1.06 | shows |
| s0-champagne-rose | wide | `eyes:shade:chocolate-gold` | 3.51 | 1.18 | shows |
| s0-champagne-rose | thin | `liner:shade:smudge` | 4.20 | 1.91 | shows |
| s0-champagne-rose | thin | `liner:shade:wing` | 10.50 | 3.66 | shows |
| s0-champagne-rose | thin | `liner:shade:none` | 6.18 | 2.26 | shows |
| s0-champagne-rose | thin | `lashes:shade:wispy` | 7.72 | 2.87 | shows |
| s0-champagne-rose | thin | `lashes:shade:volume` | 6.47 | 2.66 | shows |
| s0-champagne-rose | thin | `brows:shade:soft` | 5.73 | 2.53 | shows |
| s0-champagne-rose | thin | `brows:shade:defined` | 3.04 | 1.49 | shows |
| s0-champagne-rose | wide | `cheeks:shade:peach` | 3.54 | 2.39 | shows |
| s0-champagne-rose | wide | `cheeks:shade:coral` | 2.53 | 1.75 | shows |
| s0-champagne-rose | wide | `cheeks:shade:terracotta` | 3.23 | 2.19 | shows |
| s0-champagne-rose | wide | `cheeks:shade:rose` | 2.70 | 1.80 | shows |
| s0-champagne-rose | wide | `cheeks:shade:mauve` | 2.50 | 1.54 | shows |
| s0-champagne-rose | wide | `cheeks:shade:berry` | 3.81 | 2.47 | shows |
| s0-champagne-rose | thin | `bronzer:shade:sculpted` | 1.96 | 1.11 | quiet |
| s0-champagne-rose | thin | `highlight:shade:radiant` | 3.30 | 2.09 | shows |
| s0-champagne-rose | thin | `highlight:shade:none` | 4.63 | 2.31 | shows |
| s0-champagne-rose | wide | `lips:shade:light-pink` | 13.37 | 9.91 | shows |
| s0-champagne-rose | wide | `lips:shade:peach-pink` | 14.23 | 10.72 | shows |
| s0-champagne-rose | wide | `lips:shade:rosy-peach` | 10.05 | 7.13 | shows |
| s0-champagne-rose | wide | `lips:shade:warm-coral` | 7.64 | 6.45 | shows |
| s0-champagne-rose | wide | `lips:shade:nude-rose` | 3.50 | 2.77 | shows |
| s0-champagne-rose | wide | `lips:shade:rose-gloss` | 4.39 | 2.94 | shows |
| s0-champagne-rose | wide | `lips:shade:rosewood` | 5.52 | 4.29 | shows |
| s0-champagne-rose | wide | `lips:shade:raspberry` | 8.64 | 6.62 | shows |
| s0-champagne-rose | wide | `lips:shade:ruby` | 13.39 | 9.90 | shows |
| s0-champagne-rose | thin | `lip_line:shade:defined` | 2.83 | 1.44 | shows |
| s0-champagne-rose | thin | `lip_line:shade:none` | 6.41 | 2.92 | shows |
| s0-champagne-rose | wide | `eyes:softer@champagne-glow` | 2.02 | 0.71 | quiet |
| s0-champagne-rose | wide | `eyes:bolder@champagne-glow` | 4.08 | 1.44 | shows |
| s0-champagne-rose | wide | `eyes:bolder@peach-bronze` | 2.02 | 0.71 | quiet |
| s0-champagne-rose | wide | `eyes:softer@rose-gold-smoke` | 4.08 | 1.44 | shows |
| s0-champagne-rose | wide | `eyes:bolder@rose-gold-smoke` | 3.17 | 1.16 | shows |
| s0-champagne-rose | wide | `eyes:softer@warm-taupe` | 3.17 | 1.16 | shows |
| s0-champagne-rose | wide | `eyes:bolder@warm-taupe` | 2.43 | 0.72 | quiet |
| s0-champagne-rose | wide | `eyes:softer@copper` | 2.83 | 0.88 | shows |
| s0-champagne-rose | wide | `eyes:bolder@copper` | 2.54 | 0.76 | shows |
| s0-champagne-rose | wide | `eyes:softer@rose-brown` | 2.43 | 0.72 | quiet |
| s0-champagne-rose | wide | `eyes:bolder@rose-brown` | 2.40 | 0.69 | quiet |
| s0-champagne-rose | wide | `eyes:softer@plum-brown` | 2.09 | 0.61 | quiet |
| s0-champagne-rose | wide | `eyes:softer@chocolate-gold` | 2.40 | 0.69 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@peach` | 1.43 | 0.94 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@muted-rose` | 2.50 | 1.54 | shows |
| s0-champagne-rose | wide | `cheeks:softer@coral` | 1.43 | 0.94 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@coral` | 1.52 | 0.99 | quiet |
| s0-champagne-rose | wide | `cheeks:softer@terracotta` | 1.52 | 0.99 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@terracotta` | 4.08 | 2.70 | shows |
| s0-champagne-rose | wide | `cheeks:softer@rose` | 2.70 | 1.80 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@rose` | 2.25 | 1.51 | quiet |
| s0-champagne-rose | wide | `cheeks:softer@mauve` | 2.50 | 1.54 | shows |
| s0-champagne-rose | wide | `cheeks:softer@berry` | 1.97 | 1.34 | quiet |
| s0-champagne-rose | wide | `lips:softer@light-pink` | 4.87 | 3.93 | shows |
| s0-champagne-rose | wide | `lips:bolder@light-pink` | 12.43 | 9.15 | shows |
| s0-champagne-rose | wide | `lips:bolder@peach-pink` | 4.61 | 3.74 | shows |
| s0-champagne-rose | wide | `lips:softer@rosy-peach` | 4.61 | 3.74 | shows |
| s0-champagne-rose | wide | `lips:bolder@rosy-peach` | 4.87 | 3.93 | shows |
| s0-champagne-rose | wide | `lips:softer@warm-coral` | 12.27 | 8.95 | shows |
| s0-champagne-rose | wide | `lips:bolder@warm-coral` | 5.24 | 4.54 | shows |
| s0-champagne-rose | wide | `lips:softer@nude-rose` | 12.43 | 9.15 | shows |
| s0-champagne-rose | wide | `lips:bolder@nude-rose` | 3.50 | 2.77 | shows |
| s0-champagne-rose | wide | `lips:softer@dusty-rose` | 3.50 | 2.77 | shows |
| s0-champagne-rose | wide | `lips:bolder@dusty-rose` | 5.52 | 4.29 | shows |
| s0-champagne-rose | wide | `lips:softer@rose-gloss` | 4.52 | 3.70 | shows |
| s0-champagne-rose | wide | `lips:bolder@rose-gloss` | 9.68 | 6.68 | shows |
| s0-champagne-rose | wide | `lips:softer@rosewood` | 5.52 | 4.29 | shows |
| s0-champagne-rose | wide | `lips:softer@raspberry` | 7.42 | 5.94 | shows |
| s0-champagne-rose | wide | `lips:bolder@raspberry` | 5.76 | 4.39 | shows |
| s0-champagne-rose | wide | `lips:softer@ruby` | 5.76 | 4.39 | shows |
