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
of a step: **the 90th percentile of dE2000 >= 2.5**, for the brows **>= 3.5** (the
critic's second look at close-up crops of the brows). A step below that is quiet: `quiet_edits` in the manifest,
no button, the server refuses it.

Why p90 and not a mean: a mean over the mask dilutes thin elements (a wing liner: mean 3.7, p90 10.5). Why it is the
right measure here: the look screen brings a chosen zone close up (2.3x on eyes and lips, 1.5x on cheeks), so the
strongest part of the zone is what she looks at. The threshold was checked by eye by the critic on close-up crops of
the recording.

| Sample | Measured | Quiet | No render |
|---|---|---|---|
| s0-champagne-rose | 58 | 0 | 0 |
| s2-classic-red | 63 | 3 | 0 |
| s3-mauve-smoky | 55 | 3 | 0 |

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
| s2-classic-red | wide | `eyes:shade:champagne` | 13.49 | 6.47 | shows |
| s2-classic-red | wide | `eyes:shade:warm-taupe` | 10.01 | 4.57 | shows |
| s2-classic-red | wide | `eyes:shade:bronze` | 5.98 | 3.18 | shows |
| s2-classic-red | wide | `eyes:shade:plum` | 12.02 | 6.16 | shows |
| s2-classic-red | wide | `eyes:shade:chocolate` | 14.89 | 7.43 | shows |
| s2-classic-red | thin | `liner:shade:flick` | 6.00 | 2.55 | shows |
| s2-classic-red | thin | `liner:shade:wing` | 9.61 | 3.92 | shows |
| s2-classic-red | thin | `lashes:shade:fluttery` | 7.90 | 3.03 | shows |
| s2-classic-red | thin | `lashes:shade:volume` | 8.54 | 3.19 | shows |
| s2-classic-red | thin | `brows:shade:soft` | 2.11 | 1.19 | quiet |
| s2-classic-red | thin | `brows:shade:defined` | 3.18 | 1.72 | quiet |
| s2-classic-red | wide | `cheeks:shade:peach` | 2.52 | 1.54 | shows |
| s2-classic-red | wide | `cheeks:shade:rose` | 3.22 | 2.14 | shows |
| s2-classic-red | wide | `cheeks:shade:terracotta` | 2.59 | 1.68 | shows |
| s2-classic-red | wide | `cheeks:shade:plum-rose` | 5.21 | 3.47 | shows |
| s2-classic-red | thin | `highlight:shade:radiant` | 2.65 | 1.63 | shows |
| s2-classic-red | wide | `lips:shade:light-pink` | 32.78 | 20.76 | shows |
| s2-classic-red | wide | `lips:shade:peach-pink` | 32.47 | 20.51 | shows |
| s2-classic-red | wide | `lips:shade:rosy-peach` | 29.11 | 17.15 | shows |
| s2-classic-red | wide | `lips:shade:warm-coral` | 19.40 | 12.97 | shows |
| s2-classic-red | wide | `lips:shade:nude-rose` | 18.45 | 12.19 | shows |
| s2-classic-red | wide | `lips:shade:dusty-rose` | 17.62 | 11.70 | shows |
| s2-classic-red | wide | `lips:shade:rose-gloss` | 22.41 | 12.86 | shows |
| s2-classic-red | wide | `lips:shade:warm-rose` | 13.58 | 9.02 | shows |
| s2-classic-red | wide | `lips:shade:raspberry` | 7.85 | 5.39 | shows |
| s2-classic-red | wide | `lips:shade:wine` | 8.63 | 7.14 | shows |
| s2-classic-red | thin | `lip_line:shade:natural` | 2.64 | 1.38 | shows |
| s2-classic-red | thin | `lip_line:shade:defined` | 2.47 | 1.32 | quiet |
| s2-classic-red | wide | `eyes:bolder@champagne` | 18.17 | 8.28 | shows |
| s2-classic-red | wide | `eyes:softer@warm-taupe` | 18.17 | 8.28 | shows |
| s2-classic-red | wide | `eyes:bolder@warm-taupe` | 10.01 | 4.57 | shows |
| s2-classic-red | wide | `eyes:softer@rose-gold` | 10.01 | 4.57 | shows |
| s2-classic-red | wide | `eyes:bolder@rose-gold` | 5.98 | 3.18 | shows |
| s2-classic-red | wide | `eyes:softer@bronze` | 5.98 | 3.18 | shows |
| s2-classic-red | wide | `eyes:bolder@bronze` | 15.67 | 6.87 | shows |
| s2-classic-red | wide | `eyes:softer@chocolate` | 14.89 | 7.43 | shows |
| s2-classic-red | wide | `cheeks:bolder@peach` | 2.52 | 1.54 | shows |
| s2-classic-red | wide | `cheeks:softer@soft-coral` | 2.52 | 1.54 | shows |
| s2-classic-red | wide | `cheeks:bolder@soft-coral` | 3.22 | 2.14 | shows |
| s2-classic-red | wide | `cheeks:softer@rose` | 3.22 | 2.14 | shows |
| s2-classic-red | wide | `cheeks:bolder@rose` | 4.25 | 2.96 | shows |
| s2-classic-red | wide | `cheeks:softer@terracotta` | 4.25 | 2.96 | shows |
| s2-classic-red | wide | `cheeks:softer@plum-rose` | 3.22 | 2.05 | shows |
| s2-classic-red | wide | `lips:softer@light-pink` | 5.77 | 4.32 | shows |
| s2-classic-red | wide | `lips:bolder@light-pink` | 13.93 | 9.58 | shows |
| s2-classic-red | wide | `lips:bolder@peach-pink` | 5.23 | 3.92 | shows |
| s2-classic-red | wide | `lips:softer@rosy-peach` | 5.23 | 3.92 | shows |
| s2-classic-red | wide | `lips:bolder@rosy-peach` | 5.77 | 4.32 | shows |
| s2-classic-red | wide | `lips:softer@warm-coral` | 14.45 | 9.91 | shows |
| s2-classic-red | wide | `lips:bolder@warm-coral` | 6.06 | 5.06 | shows |
| s2-classic-red | wide | `lips:softer@nude-rose` | 13.93 | 9.58 | shows |
| s2-classic-red | wide | `lips:bolder@nude-rose` | 4.05 | 3.04 | shows |
| s2-classic-red | wide | `lips:softer@dusty-rose` | 4.05 | 3.04 | shows |
| s2-classic-red | wide | `lips:bolder@dusty-rose` | 5.18 | 3.83 | shows |
| s2-classic-red | wide | `lips:softer@rose-gloss` | 5.43 | 3.92 | shows |
| s2-classic-red | wide | `lips:bolder@rose-gloss` | 8.81 | 4.99 | shows |
| s2-classic-red | wide | `lips:softer@warm-rose` | 5.18 | 3.83 | shows |
| s2-classic-red | wide | `lips:bolder@warm-rose` | 17.65 | 12.10 | shows |
| s2-classic-red | wide | `lips:softer@raspberry` | 8.86 | 6.50 | shows |
| s2-classic-red | wide | `lips:bolder@raspberry` | 7.85 | 5.39 | shows |
| s2-classic-red | wide | `lips:softer@ruby` | 7.85 | 5.39 | shows |
| s2-classic-red | wide | `lips:bolder@ruby` | 8.63 | 7.14 | shows |
| s2-classic-red | wide | `lips:softer@wine` | 11.47 | 8.50 | shows |
| s3-mauve-smoky | wide | `eyes:shade:copper` | 13.07 | 4.75 | shows |
| s3-mauve-smoky | wide | `eyes:shade:bronze` | 12.46 | 4.87 | shows |
| s3-mauve-smoky | wide | `eyes:shade:emerald` | 30.11 | 13.18 | shows |
| s3-mauve-smoky | wide | `eyes:shade:plum` | 28.08 | 10.90 | shows |
| s3-mauve-smoky | wide | `eyes:shade:burgundy` | 30.81 | 11.91 | shows |
| s3-mauve-smoky | thin | `liner:shade:flick` | 6.03 | 2.68 | shows |
| s3-mauve-smoky | thin | `liner:shade:wing` | 10.74 | 4.21 | shows |
| s3-mauve-smoky | thin | `lashes:shade:fluttery` | 9.24 | 3.61 | shows |
| s3-mauve-smoky | thin | `lashes:shade:volume` | 8.63 | 3.41 | shows |
| s3-mauve-smoky | thin | `brows:shade:soft` | 1.92 | 0.85 | quiet |
| s3-mauve-smoky | thin | `brows:shade:defined` | 1.78 | 0.79 | quiet |
| s3-mauve-smoky | wide | `cheeks:shade:copper` | 2.96 | 2.19 | shows |
| s3-mauve-smoky | wide | `cheeks:shade:coral-brick` | 3.20 | 2.47 | shows |
| s3-mauve-smoky | wide | `cheeks:shade:warm-berry` | 2.80 | 2.14 | shows |
| s3-mauve-smoky | wide | `cheeks:shade:deep-plum` | 4.26 | 3.55 | shows |
| s3-mauve-smoky | thin | `highlight:shade:radiant` | 1.99 | 1.21 | quiet |
| s3-mauve-smoky | thin | `highlight:shade:none` | 6.74 | 3.70 | shows |
| s3-mauve-smoky | wide | `lips:shade:bronze` | 14.16 | 11.17 | shows |
| s3-mauve-smoky | wide | `lips:shade:caramel-nude` | 9.55 | 7.25 | shows |
| s3-mauve-smoky | wide | `lips:shade:brick` | 10.79 | 8.63 | shows |
| s3-mauve-smoky | wide | `lips:shade:deep-red` | 8.40 | 6.68 | shows |
| s3-mauve-smoky | wide | `lips:shade:berry-gloss` | 4.90 | 2.51 | shows |
| s3-mauve-smoky | wide | `lips:shade:plum` | 4.73 | 3.87 | shows |
| s3-mauve-smoky | wide | `lips:shade:oxblood` | 9.83 | 6.17 | shows |
| s3-mauve-smoky | wide | `lips:shade:dark-berry` | 13.96 | 10.28 | shows |
| s3-mauve-smoky | thin | `lip_line:shade:defined` | 3.93 | 1.51 | shows |
| s3-mauve-smoky | wide | `eyes:bolder@gold` | 12.46 | 4.87 | shows |
| s3-mauve-smoky | wide | `eyes:bolder@copper` | 6.30 | 2.60 | shows |
| s3-mauve-smoky | wide | `eyes:softer@bronze` | 12.46 | 4.87 | shows |
| s3-mauve-smoky | wide | `eyes:softer@plum` | 10.46 | 3.91 | shows |
| s3-mauve-smoky | wide | `eyes:bolder@burgundy` | 10.46 | 3.91 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@copper` | 3.51 | 2.86 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@coral-brick` | 3.51 | 2.86 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@coral-brick` | 3.20 | 2.47 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@mulled-rose` | 2.96 | 2.19 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@mulled-rose` | 2.80 | 2.14 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@warm-berry` | 2.80 | 2.14 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@warm-berry` | 2.54 | 2.15 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@deep-plum` | 2.54 | 2.15 | shows |
| s3-mauve-smoky | wide | `lips:bolder@bronze` | 5.77 | 4.65 | shows |
| s3-mauve-smoky | wide | `lips:softer@caramel-nude` | 5.77 | 4.65 | shows |
| s3-mauve-smoky | wide | `lips:bolder@caramel-nude` | 9.55 | 7.25 | shows |
| s3-mauve-smoky | wide | `lips:softer@brick` | 8.44 | 5.68 | shows |
| s3-mauve-smoky | wide | `lips:bolder@brick` | 7.09 | 5.59 | shows |
| s3-mauve-smoky | wide | `lips:softer@deep-red` | 7.09 | 5.59 | shows |
| s3-mauve-smoky | wide | `lips:bolder@deep-red` | 8.40 | 6.68 | shows |
| s3-mauve-smoky | wide | `lips:softer@berry-rose` | 10.79 | 8.63 | shows |
| s3-mauve-smoky | wide | `lips:bolder@berry-rose` | 9.83 | 6.17 | shows |
| s3-mauve-smoky | wide | `lips:softer@berry-gloss` | 11.79 | 9.41 | shows |
| s3-mauve-smoky | wide | `lips:bolder@berry-gloss` | 14.31 | 7.69 | shows |
| s3-mauve-smoky | wide | `lips:softer@plum` | 4.73 | 3.87 | shows |
| s3-mauve-smoky | wide | `lips:bolder@plum` | 9.74 | 6.65 | shows |
| s3-mauve-smoky | wide | `lips:softer@oxblood` | 9.83 | 6.17 | shows |
| s3-mauve-smoky | wide | `lips:bolder@oxblood` | 9.08 | 6.19 | shows |
| s3-mauve-smoky | wide | `lips:softer@dark-berry` | 9.74 | 6.65 | shows |
