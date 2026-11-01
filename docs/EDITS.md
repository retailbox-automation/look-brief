# Buttons that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." A probe of 14
units then showed why strength cannot be the button: intensity +-8-10 moves a zone by dE2000 0.6-1.3, and even 14 against
64 on the cheeks by 1.3-2.9.

## The edit rule (`src/lookbrief/recipe.py`, `src/lookbrief/palettes.py`)
- **Softer / Bolder** (lids, cheeks, lips): the next shade of the same colour family in the order of distance to her
  skin (CIEDE2000; lids: the lid colour). The same render as tapping that circle. The end of the way turns the button off.
- **Circles:** every shade of lids, cheeks and lips, metallic and gloss looks among them. They are recorded on all three
  looks; on Classic and Evening a key reads `look:evening+lips:shade:ruby` and is measured against the render of that look.
- **Styles:** liner, lashes, brows, highlighter and lip liner offer named steps with their own pattern and strength;
  the highlighter can be left out. They are recorded on Soft glam only; on Classic and Evening a style is the step
  between two of those renders and the look stays (see below). Bronzer has no choice: a light warm layer that is part
  of the look.
No colour is computed: every colour sent is a shade of the palette.

## Zones stack (`src/lookbrief/layers.py`, `tests/test_layers.py`, `tests/test_zone_stacking.py`)
Nadya on an iPhone (01.11.2026): "When I pick Eyelids, say Chocolate, I like it, but then I want a better wing in this
look. I pick Eyeliner, add Wing, but I want that Chocolate eyelid to stay." A zone holds one choice and the others stay.
"Remove this step" returns one zone to the look; taking a product off entirely exists only for the highlighter.

- **Live** makes one real call with the whole recipe.
- **Replay, a list that is recorded** (one change, a look, a circle on a look): that real render, untouched, with its
  task id.
- **Replay, anything else** is assembled on the server from recorded single-zone renders, one per zone, into one JPEG
  (quality 92), so the brief, the card, the PDF and the signature keep one file. The same choices give the same bytes
  in any click order: the zones land in a fixed order (lids, brows, cheeks, highlighter, lips, lip liner, liner, lashes)
  and the file is named by the sorted choices.
- **Sources.** The frame is the look (`render:base`, `render:look:<look>`). Lids, cheeks, lips: the look's own recorded
  circle against the frame. Thin zones: the Soft glam single of the choice against the Soft glam single of what the
  frame wears, or `render:base` where no such single exists. A choice with no source, or whose two renders are the same
  render, is off and says so: the photo could not change while the tab said it had.
- **Blend**, in linear light inside the mask of the zone: the ratio T/R on the frame. Liner and lashes that add to the
  frame are painted instead, liner keeping the depth of the render in its opaque core (`layers.PAINT`, one line to swap).
  Going back to a lighter style uses the ratio: paint cannot lighten.
- **On disk.** A session keeps at most 60 assembled files. The oldest goes first, never the current look or a file a
  brief shows, so a sent link and its hash keep working, and Undo makes a file that went again, the same bytes.
- **It says so.** "Assembled from N recorded YouCam Makeup VTO results, one per zone" on the photo, before and after,
  the brief and the card, where N counts the zone renders; no single task id is shown as if it were the whole image.
  The signed record holds the method and the task id of every frame, zone render and reference.

Checked against what the samples hold for real: Evening is recorded with Wing and Volume on all 6 lids of all 3 samples,
18 multi-zone renders. The same clicks on Soft glam (lid + Wing + Volume) against them, eye area, dE2000:

| | Mean, average | Mean, worst | p95, average | p95, worst |
|---|---|---|---|---|
| Assembled pixels | 0.81 | 1.05 | 2.98 | 4.25 |
| The same after the JPEG she gets | 1.22 | 1.46 | 3.45 | 4.49 |
| A real render through the same JPEG, against itself | 0.84 | 1.01 | 2.18 | 2.80 |

On the 216-225 pixels of the wing itself: mean 2.54 at worst, against 11.1 at best for the last click alone. Six zones on
the whole face have no real render to compare with. One compose of eight zones: 0.21 s on the development machine, about
39 MB of arrays at its peak, under the same one-at-a-time slot as every render. Not measured on the 1 CPU container.

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
| s0-champagne-rose | 169 | 38 | 0 |
| s2-classic-red | 179 | 33 | 0 |
| s3-mauve-smoky | 161 | 48 | 0 |

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
| s0-champagne-rose | wide | `lips:shade:ruby` | 16.73 | 11.71 | shows |
| s0-champagne-rose | thin | `lip_line:shade:defined` | 3.61 | 1.59 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:champagne` | 6.88 | 2.98 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:warm-taupe` | 18.72 | 8.56 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:rose-gold` | 13.51 | 6.53 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:bronze` | 17.26 | 8.01 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:plum` | 21.50 | 10.56 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:shade:chocolate` | 26.68 | 12.76 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:shade:peach` | 2.45 | 1.57 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:shade:terracotta` | 1.82 | 1.26 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:shade:warm-rose` | 2.42 | 1.57 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:shade:brick` | 3.34 | 2.05 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:shade:berry` | 5.09 | 3.42 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:light-pink` | 8.72 | 6.22 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:peach-pink` | 7.06 | 4.61 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:rosy-peach` | 3.63 | 1.97 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:warm-coral` | 4.44 | 3.70 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:nude-rose` | 4.62 | 3.77 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:dusty-rose` | 6.03 | 4.97 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:rose-gloss` | 5.55 | 4.83 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:warm-rose` | 8.01 | 6.37 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:raspberry` | 14.79 | 11.58 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:shade:ruby` | 21.63 | 15.07 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:champagne` | 14.14 | 6.63 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:warm-taupe` | 6.95 | 3.16 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:rose-gold` | 5.54 | 2.66 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:bronze` | 4.83 | 2.06 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:plum` | 11.31 | 5.12 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:shade:chocolate` | 10.76 | 3.97 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:shade:peach` | 4.82 | 3.18 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:shade:terracotta` | 3.73 | 2.47 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:shade:brick` | 2.53 | 1.70 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:shade:berry` | 2.94 | 1.94 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:light-pink` | 31.53 | 21.93 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:peach-pink` | 31.32 | 21.82 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:rosy-peach` | 28.04 | 18.48 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:warm-coral` | 20.22 | 14.32 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:nude-rose` | 19.23 | 13.45 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:dusty-rose` | 18.34 | 12.78 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:rose-gloss` | 22.35 | 14.14 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:warm-rose` | 15.08 | 10.42 | shows |
| s0-champagne-rose | wide | `look:evening+lips:shade:raspberry` | 9.85 | 6.53 | shows |
| s0-champagne-rose | wide | `eyes:bolder@champagne` | 15.91 | 6.84 | shows |
| s0-champagne-rose | wide | `eyes:softer@warm-taupe` | 15.91 | 6.84 | shows |
| s0-champagne-rose | wide | `eyes:bolder@warm-taupe` | 8.43 | 3.62 | quiet |
| s0-champagne-rose | wide | `eyes:softer@rose-gold` | 8.43 | 3.62 | quiet |
| s0-champagne-rose | wide | `eyes:bolder@rose-gold` | 5.79 | 2.84 | shows |
| s0-champagne-rose | wide | `eyes:softer@bronze` | 5.79 | 2.84 | shows |
| s0-champagne-rose | wide | `eyes:bolder@bronze` | 13.92 | 5.77 | shows |
| s0-champagne-rose | wide | `eyes:softer@chocolate` | 13.93 | 6.48 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@peach` | 3.16 | 2.01 | quiet |
| s0-champagne-rose | wide | `cheeks:softer@terracotta` | 3.16 | 2.01 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@terracotta` | 3.03 | 2.01 | quiet |
| s0-champagne-rose | wide | `cheeks:bolder@warm-rose` | 2.56 | 1.71 | shows |
| s0-champagne-rose | wide | `cheeks:softer@brick` | 2.56 | 1.71 | shows |
| s0-champagne-rose | wide | `cheeks:bolder@brick` | 3.27 | 2.12 | shows |
| s0-champagne-rose | wide | `cheeks:softer@berry` | 3.27 | 2.12 | shows |
| s0-champagne-rose | wide | `lips:softer@light-pink` | 4.92 | 4.02 | shows |
| s0-champagne-rose | wide | `lips:bolder@light-pink` | 12.43 | 9.42 | quiet |
| s0-champagne-rose | wide | `lips:bolder@peach-pink` | 4.64 | 3.81 | quiet |
| s0-champagne-rose | wide | `lips:softer@rosy-peach` | 4.64 | 3.81 | quiet |
| s0-champagne-rose | wide | `lips:bolder@rosy-peach` | 4.92 | 4.02 | shows |
| s0-champagne-rose | wide | `lips:softer@warm-coral` | 12.21 | 9.15 | quiet |
| s0-champagne-rose | wide | `lips:bolder@warm-coral` | 5.23 | 4.55 | shows |
| s0-champagne-rose | wide | `lips:softer@nude-rose` | 12.43 | 9.42 | quiet |
| s0-champagne-rose | wide | `lips:bolder@nude-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `lips:softer@dusty-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `lips:bolder@dusty-rose` | 4.13 | 3.33 | shows |
| s0-champagne-rose | wide | `lips:softer@rose-gloss` | 4.08 | 3.30 | shows |
| s0-champagne-rose | wide | `lips:bolder@rose-gloss` | 6.87 | 4.60 | shows |
| s0-champagne-rose | wide | `lips:softer@warm-rose` | 4.13 | 3.33 | shows |
| s0-champagne-rose | wide | `lips:softer@raspberry` | 7.95 | 6.26 | shows |
| s0-champagne-rose | wide | `lips:bolder@raspberry` | 8.22 | 5.64 | shows |
| s0-champagne-rose | wide | `lips:softer@ruby` | 8.22 | 5.64 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:bolder@champagne` | 16.25 | 6.99 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:softer@warm-taupe` | 16.25 | 6.99 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:bolder@warm-taupe` | 8.75 | 3.74 | quiet |
| s0-champagne-rose | wide | `look:fresh+eyes:softer@rose-gold` | 8.75 | 3.74 | quiet |
| s0-champagne-rose | wide | `look:fresh+eyes:bolder@rose-gold` | 5.71 | 2.84 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:softer@bronze` | 5.71 | 2.84 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:bolder@bronze` | 13.99 | 5.82 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:softer@chocolate` | 14.35 | 6.71 | shows |
| s0-champagne-rose | wide | `look:fresh+eyes:bolder@peach-taupe` | 6.88 | 2.98 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:bolder@peach` | 3.03 | 1.88 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:softer@terracotta` | 3.03 | 1.88 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:bolder@terracotta` | 2.98 | 1.98 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:bolder@warm-rose` | 2.53 | 1.63 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:softer@brick` | 2.53 | 1.63 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:bolder@brick` | 3.26 | 2.13 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:softer@berry` | 3.26 | 2.13 | shows |
| s0-champagne-rose | wide | `look:fresh+cheeks:softer@soft-coral` | 2.45 | 1.57 | quiet |
| s0-champagne-rose | wide | `look:fresh+cheeks:bolder@soft-coral` | 1.82 | 1.26 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:softer@light-pink` | 5.64 | 4.63 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@light-pink` | 12.61 | 9.52 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@peach-pink` | 4.14 | 3.27 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:softer@rosy-peach` | 4.14 | 3.27 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@rosy-peach` | 5.64 | 4.63 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@warm-coral` | 12.50 | 9.40 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@warm-coral` | 4.81 | 4.18 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@nude-rose` | 12.61 | 9.52 | quiet |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@nude-rose` | 3.41 | 2.80 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@dusty-rose` | 3.41 | 2.80 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@dusty-rose` | 4.15 | 3.36 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@rose-gloss` | 4.29 | 3.49 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@rose-gloss` | 6.88 | 4.65 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@warm-rose` | 4.15 | 3.36 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@raspberry` | 8.15 | 6.44 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@raspberry` | 8.09 | 5.33 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@ruby` | 8.09 | 5.33 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:softer@rosy-nude` | 3.63 | 1.97 | shows |
| s0-champagne-rose | wide | `look:fresh+lips:bolder@rosy-nude` | 8.72 | 6.22 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:bolder@champagne` | 14.11 | 6.02 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:softer@warm-taupe` | 14.11 | 6.02 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:bolder@warm-taupe` | 7.52 | 3.17 | quiet |
| s0-champagne-rose | wide | `look:evening+eyes:softer@rose-gold` | 7.52 | 3.17 | quiet |
| s0-champagne-rose | wide | `look:evening+eyes:bolder@rose-gold` | 5.35 | 2.56 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:softer@bronze` | 5.35 | 2.56 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:bolder@bronze` | 12.35 | 5.09 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:softer@chocolate` | 12.61 | 5.81 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:softer@copper-umber` | 4.83 | 2.06 | shows |
| s0-champagne-rose | wide | `look:evening+eyes:bolder@copper-umber` | 10.76 | 3.97 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:bolder@peach` | 3.15 | 2.00 | quiet |
| s0-champagne-rose | wide | `look:evening+cheeks:softer@terracotta` | 3.15 | 2.00 | quiet |
| s0-champagne-rose | wide | `look:evening+cheeks:bolder@terracotta` | 3.05 | 2.03 | quiet |
| s0-champagne-rose | wide | `look:evening+cheeks:bolder@warm-rose` | 2.53 | 1.70 | quiet |
| s0-champagne-rose | wide | `look:evening+cheeks:softer@brick` | 2.53 | 1.70 | quiet |
| s0-champagne-rose | wide | `look:evening+cheeks:bolder@brick` | 3.26 | 2.13 | shows |
| s0-champagne-rose | wide | `look:evening+cheeks:softer@berry` | 3.26 | 2.13 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@light-pink` | 4.88 | 3.97 | shows |
| s0-champagne-rose | wide | `look:evening+lips:bolder@light-pink` | 12.37 | 9.34 | quiet |
| s0-champagne-rose | wide | `look:evening+lips:bolder@peach-pink` | 4.64 | 3.81 | quiet |
| s0-champagne-rose | wide | `look:evening+lips:softer@rosy-peach` | 4.64 | 3.81 | quiet |
| s0-champagne-rose | wide | `look:evening+lips:bolder@rosy-peach` | 4.88 | 3.97 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@warm-coral` | 12.20 | 9.13 | quiet |
| s0-champagne-rose | wide | `look:evening+lips:bolder@warm-coral` | 5.23 | 4.55 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@nude-rose` | 12.37 | 9.34 | quiet |
| s0-champagne-rose | wide | `look:evening+lips:bolder@nude-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@dusty-rose` | 3.32 | 2.65 | shows |
| s0-champagne-rose | wide | `look:evening+lips:bolder@dusty-rose` | 4.11 | 3.32 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@rose-gloss` | 4.08 | 3.30 | shows |
| s0-champagne-rose | wide | `look:evening+lips:bolder@rose-gloss` | 6.87 | 4.60 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@warm-rose` | 4.11 | 3.32 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@raspberry` | 8.15 | 6.43 | shows |
| s0-champagne-rose | wide | `look:evening+lips:bolder@raspberry` | 9.85 | 6.53 | shows |
| s0-champagne-rose | wide | `look:evening+lips:softer@ruby` | 9.85 | 6.53 | shows |
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
| s2-classic-red | wide | `lips:shade:light-pink` | 32.78 | 24.01 | shows |
| s2-classic-red | wide | `lips:shade:peach-pink` | 32.66 | 23.83 | shows |
| s2-classic-red | wide | `lips:shade:rosy-peach` | 29.41 | 20.10 | shows |
| s2-classic-red | wide | `lips:shade:warm-coral` | 19.84 | 15.17 | shows |
| s2-classic-red | wide | `lips:shade:nude-rose` | 19.01 | 14.41 | shows |
| s2-classic-red | wide | `lips:shade:dusty-rose` | 17.99 | 13.80 | shows |
| s2-classic-red | wide | `lips:shade:rose-gloss` | 22.78 | 15.19 | shows |
| s2-classic-red | wide | `lips:shade:warm-rose` | 14.28 | 10.92 | shows |
| s2-classic-red | wide | `lips:shade:raspberry` | 8.90 | 6.91 | shows |
| s2-classic-red | wide | `lips:shade:wine` | 8.85 | 7.82 | shows |
| s2-classic-red | thin | `lip_line:shade:natural` | 2.64 | 1.38 | shows |
| s2-classic-red | thin | `lip_line:shade:defined` | 2.47 | 1.32 | quiet |
| s2-classic-red | wide | `look:fresh+eyes:shade:champagne` | 7.24 | 3.69 | shows |
| s2-classic-red | wide | `look:fresh+eyes:shade:warm-taupe` | 13.65 | 5.61 | shows |
| s2-classic-red | wide | `look:fresh+eyes:shade:rose-gold` | 8.63 | 4.16 | shows |
| s2-classic-red | wide | `look:fresh+eyes:shade:bronze` | 10.40 | 5.11 | shows |
| s2-classic-red | wide | `look:fresh+eyes:shade:plum` | 17.07 | 8.42 | shows |
| s2-classic-red | wide | `look:fresh+eyes:shade:chocolate` | 20.39 | 9.89 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:shade:peach` | 2.59 | 1.75 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:shade:rose` | 2.65 | 1.76 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:shade:terracotta` | 2.34 | 1.51 | quiet |
| s2-classic-red | wide | `look:fresh+cheeks:shade:plum-rose` | 4.73 | 3.10 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:light-pink` | 11.80 | 8.93 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:peach-pink` | 11.44 | 8.65 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:rosy-peach` | 7.20 | 4.81 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:warm-coral` | 5.35 | 4.61 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:nude-rose` | 2.40 | 1.70 | quiet |
| s2-classic-red | wide | `look:fresh+lips:shade:dusty-rose` | 4.66 | 3.69 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:rose-gloss` | 4.70 | 4.14 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:warm-rose` | 6.74 | 4.97 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:raspberry` | 14.31 | 11.17 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:ruby` | 20.71 | 15.43 | shows |
| s2-classic-red | wide | `look:fresh+lips:shade:wine` | 25.24 | 19.08 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:champagne` | 17.78 | 9.00 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:warm-taupe` | 7.07 | 3.84 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:rose-gold` | 7.68 | 4.02 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:bronze` | 7.77 | 3.41 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:plum` | 11.38 | 5.55 | shows |
| s2-classic-red | wide | `look:evening+eyes:shade:chocolate` | 8.62 | 3.19 | shows |
| s2-classic-red | wide | `look:evening+cheeks:shade:peach` | 2.34 | 1.54 | quiet |
| s2-classic-red | wide | `look:evening+cheeks:shade:rose` | 3.08 | 2.05 | shows |
| s2-classic-red | wide | `look:evening+cheeks:shade:terracotta` | 2.60 | 1.70 | shows |
| s2-classic-red | wide | `look:evening+cheeks:shade:plum-rose` | 5.19 | 3.41 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:light-pink` | 41.45 | 28.68 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:peach-pink` | 41.79 | 29.05 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:rosy-peach` | 36.69 | 24.96 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:warm-coral` | 26.66 | 21.13 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:nude-rose` | 24.02 | 18.52 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:dusty-rose` | 22.66 | 17.49 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:rose-gloss` | 27.75 | 18.90 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:warm-rose` | 19.20 | 15.11 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:raspberry` | 13.07 | 11.02 | shows |
| s2-classic-red | wide | `look:evening+lips:shade:ruby` | 9.89 | 8.62 | shows |
| s2-classic-red | wide | `eyes:bolder@champagne` | 18.17 | 8.28 | quiet |
| s2-classic-red | wide | `eyes:softer@warm-taupe` | 18.17 | 8.28 | quiet |
| s2-classic-red | wide | `eyes:bolder@warm-taupe` | 10.01 | 4.57 | shows |
| s2-classic-red | wide | `eyes:softer@rose-gold` | 10.01 | 4.57 | shows |
| s2-classic-red | wide | `eyes:bolder@rose-gold` | 5.98 | 3.18 | shows |
| s2-classic-red | wide | `eyes:softer@bronze` | 5.98 | 3.18 | shows |
| s2-classic-red | wide | `eyes:bolder@bronze` | 15.67 | 6.87 | shows |
| s2-classic-red | wide | `eyes:softer@chocolate` | 14.89 | 7.43 | shows |
| s2-classic-red | wide | `cheeks:bolder@peach` | 2.52 | 1.54 | quiet |
| s2-classic-red | wide | `cheeks:softer@soft-coral` | 2.52 | 1.54 | quiet |
| s2-classic-red | wide | `cheeks:bolder@soft-coral` | 3.22 | 2.14 | shows |
| s2-classic-red | wide | `cheeks:softer@rose` | 3.22 | 2.14 | shows |
| s2-classic-red | wide | `cheeks:bolder@rose` | 4.25 | 2.96 | quiet |
| s2-classic-red | wide | `cheeks:softer@terracotta` | 4.25 | 2.96 | quiet |
| s2-classic-red | wide | `cheeks:softer@plum-rose` | 3.22 | 2.05 | shows |
| s2-classic-red | wide | `lips:softer@light-pink` | 5.77 | 4.59 | shows |
| s2-classic-red | wide | `lips:bolder@light-pink` | 13.85 | 10.43 | shows |
| s2-classic-red | wide | `lips:bolder@peach-pink` | 5.30 | 4.23 | quiet |
| s2-classic-red | wide | `lips:softer@rosy-peach` | 5.30 | 4.23 | quiet |
| s2-classic-red | wide | `lips:bolder@rosy-peach` | 5.77 | 4.59 | shows |
| s2-classic-red | wide | `lips:softer@warm-coral` | 14.31 | 10.70 | shows |
| s2-classic-red | wide | `lips:bolder@warm-coral` | 6.08 | 5.22 | quiet |
| s2-classic-red | wide | `lips:softer@nude-rose` | 13.85 | 10.43 | shows |
| s2-classic-red | wide | `lips:bolder@nude-rose` | 3.81 | 3.14 | shows |
| s2-classic-red | wide | `lips:softer@dusty-rose` | 3.81 | 3.14 | shows |
| s2-classic-red | wide | `lips:bolder@dusty-rose` | 4.94 | 3.94 | shows |
| s2-classic-red | wide | `lips:softer@rose-gloss` | 5.45 | 4.16 | shows |
| s2-classic-red | wide | `lips:bolder@rose-gloss` | 8.87 | 5.41 | shows |
| s2-classic-red | wide | `lips:softer@warm-rose` | 4.94 | 3.94 | shows |
| s2-classic-red | wide | `lips:bolder@warm-rose` | 17.85 | 14.21 | shows |
| s2-classic-red | wide | `lips:softer@raspberry` | 8.87 | 7.26 | shows |
| s2-classic-red | wide | `lips:bolder@raspberry` | 8.90 | 6.91 | shows |
| s2-classic-red | wide | `lips:softer@ruby` | 8.90 | 6.91 | shows |
| s2-classic-red | wide | `lips:bolder@ruby` | 8.85 | 7.82 | shows |
| s2-classic-red | wide | `lips:softer@wine` | 12.18 | 10.22 | shows |
| s2-classic-red | wide | `look:fresh+eyes:bolder@champagne` | 17.88 | 8.15 | quiet |
| s2-classic-red | wide | `look:fresh+eyes:softer@warm-taupe` | 17.88 | 8.15 | quiet |
| s2-classic-red | wide | `look:fresh+eyes:bolder@warm-taupe` | 9.73 | 4.40 | shows |
| s2-classic-red | wide | `look:fresh+eyes:softer@rose-gold` | 9.73 | 4.40 | shows |
| s2-classic-red | wide | `look:fresh+eyes:bolder@rose-gold` | 5.62 | 2.91 | shows |
| s2-classic-red | wide | `look:fresh+eyes:softer@bronze` | 5.62 | 2.91 | shows |
| s2-classic-red | wide | `look:fresh+eyes:bolder@bronze` | 15.76 | 7.03 | shows |
| s2-classic-red | wide | `look:fresh+eyes:softer@chocolate` | 14.63 | 7.32 | shows |
| s2-classic-red | wide | `look:fresh+eyes:bolder@peach-taupe` | 7.24 | 3.69 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:bolder@peach` | 2.59 | 1.75 | quiet |
| s2-classic-red | wide | `look:fresh+cheeks:softer@soft-coral` | 2.59 | 1.75 | quiet |
| s2-classic-red | wide | `look:fresh+cheeks:bolder@soft-coral` | 2.65 | 1.76 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:softer@rose` | 2.65 | 1.76 | shows |
| s2-classic-red | wide | `look:fresh+cheeks:bolder@rose` | 4.24 | 2.94 | quiet |
| s2-classic-red | wide | `look:fresh+cheeks:softer@terracotta` | 4.24 | 2.94 | quiet |
| s2-classic-red | wide | `look:fresh+cheeks:softer@plum-rose` | 3.22 | 2.02 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@light-pink` | 5.89 | 4.72 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@light-pink` | 13.97 | 10.48 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@peach-pink` | 5.42 | 4.36 | quiet |
| s2-classic-red | wide | `look:fresh+lips:softer@rosy-peach` | 5.42 | 4.36 | quiet |
| s2-classic-red | wide | `look:fresh+lips:bolder@rosy-peach` | 5.89 | 4.72 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@warm-coral` | 14.43 | 10.75 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@warm-coral` | 6.09 | 5.22 | quiet |
| s2-classic-red | wide | `look:fresh+lips:softer@nude-rose` | 13.97 | 10.48 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@nude-rose` | 4.09 | 3.30 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@dusty-rose` | 4.09 | 3.30 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@dusty-rose` | 5.19 | 4.09 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@rose-gloss` | 5.45 | 4.15 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@rose-gloss` | 8.82 | 5.43 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@warm-rose` | 5.19 | 4.09 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@warm-rose` | 17.95 | 14.22 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@raspberry` | 8.86 | 7.22 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@raspberry` | 8.58 | 6.81 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@ruby` | 8.58 | 6.81 | shows |
| s2-classic-red | wide | `look:fresh+lips:bolder@ruby` | 8.92 | 7.89 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@wine` | 12.18 | 10.23 | shows |
| s2-classic-red | wide | `look:fresh+lips:softer@rosy-nude` | 11.80 | 8.93 | quiet |
| s2-classic-red | wide | `look:fresh+lips:bolder@rosy-nude` | 2.40 | 1.70 | quiet |
| s2-classic-red | wide | `look:evening+eyes:bolder@champagne` | 15.85 | 7.20 | shows |
| s2-classic-red | wide | `look:evening+eyes:softer@warm-taupe` | 15.85 | 7.20 | shows |
| s2-classic-red | wide | `look:evening+eyes:bolder@warm-taupe` | 8.73 | 4.01 | shows |
| s2-classic-red | wide | `look:evening+eyes:softer@rose-gold` | 8.73 | 4.01 | shows |
| s2-classic-red | wide | `look:evening+eyes:bolder@rose-gold` | 5.50 | 2.78 | shows |
| s2-classic-red | wide | `look:evening+eyes:softer@bronze` | 5.50 | 2.78 | shows |
| s2-classic-red | wide | `look:evening+eyes:bolder@bronze` | 14.11 | 6.15 | shows |
| s2-classic-red | wide | `look:evening+eyes:softer@chocolate` | 13.17 | 6.37 | shows |
| s2-classic-red | wide | `look:evening+eyes:softer@copper-umber` | 7.77 | 3.41 | shows |
| s2-classic-red | wide | `look:evening+eyes:bolder@copper-umber` | 8.62 | 3.19 | shows |
| s2-classic-red | wide | `look:evening+cheeks:bolder@peach` | 2.34 | 1.54 | quiet |
| s2-classic-red | wide | `look:evening+cheeks:softer@soft-coral` | 2.34 | 1.54 | quiet |
| s2-classic-red | wide | `look:evening+cheeks:bolder@soft-coral` | 3.08 | 2.05 | shows |
| s2-classic-red | wide | `look:evening+cheeks:softer@rose` | 3.08 | 2.05 | shows |
| s2-classic-red | wide | `look:evening+cheeks:bolder@rose` | 4.26 | 2.96 | quiet |
| s2-classic-red | wide | `look:evening+cheeks:softer@terracotta` | 4.26 | 2.96 | quiet |
| s2-classic-red | wide | `look:evening+cheeks:softer@plum-rose` | 3.22 | 2.05 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@light-pink` | 5.81 | 4.60 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@light-pink` | 13.76 | 10.33 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@peach-pink` | 5.32 | 4.23 | quiet |
| s2-classic-red | wide | `look:evening+lips:softer@rosy-peach` | 5.32 | 4.23 | quiet |
| s2-classic-red | wide | `look:evening+lips:bolder@rosy-peach` | 5.81 | 4.60 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@warm-coral` | 14.20 | 10.59 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@warm-coral` | 6.10 | 5.23 | quiet |
| s2-classic-red | wide | `look:evening+lips:softer@nude-rose` | 13.76 | 10.33 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@nude-rose` | 4.10 | 3.32 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@dusty-rose` | 4.10 | 3.32 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@dusty-rose` | 5.20 | 4.09 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@rose-gloss` | 5.47 | 4.16 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@rose-gloss` | 8.85 | 5.44 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@warm-rose` | 5.20 | 4.09 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@warm-rose` | 19.20 | 15.11 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@raspberry` | 9.05 | 7.36 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@raspberry` | 8.18 | 6.69 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@ruby` | 8.18 | 6.69 | shows |
| s2-classic-red | wide | `look:evening+lips:bolder@ruby` | 9.89 | 8.62 | shows |
| s2-classic-red | wide | `look:evening+lips:softer@wine` | 13.07 | 11.02 | shows |
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
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:gold` | 9.10 | 3.99 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:copper` | 17.23 | 7.25 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:bronze` | 18.32 | 7.83 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:emerald` | 32.19 | 14.30 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:plum` | 30.57 | 12.75 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:shade:burgundy` | 35.62 | 14.79 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:shade:copper` | 3.33 | 2.18 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:shade:coral-brick` | 2.13 | 1.40 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:shade:mulled-rose` | 1.47 | 0.88 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:shade:warm-berry` | 2.30 | 1.41 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:shade:deep-plum` | 4.81 | 2.86 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:bronze` | 6.34 | 5.42 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:caramel-nude` | 2.10 | 1.72 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:brick` | 8.00 | 5.37 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:deep-red` | 11.25 | 8.18 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:berry-rose` | 9.34 | 7.51 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:berry-gloss` | 7.98 | 7.29 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:plum` | 12.41 | 9.95 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:oxblood` | 15.87 | 10.98 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:shade:dark-berry` | 22.05 | 16.58 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:gold` | 5.40 | 2.30 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:copper` | 7.80 | 2.99 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:bronze` | 7.98 | 2.72 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:emerald` | 31.88 | 13.09 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:plum` | 22.26 | 8.42 | shows |
| s3-mauve-smoky | wide | `look:evening+eyes:shade:burgundy` | 25.03 | 9.18 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:shade:copper` | 4.00 | 3.09 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:shade:coral-brick` | 2.89 | 2.35 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:shade:mulled-rose` | 1.55 | 1.19 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:shade:warm-berry` | 1.54 | 1.10 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:shade:deep-plum` | 2.96 | 2.44 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:bronze` | 15.44 | 11.67 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:caramel-nude` | 13.98 | 10.14 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:brick` | 7.69 | 6.16 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:berry-rose` | 10.11 | 7.88 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:berry-gloss` | 12.67 | 8.97 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:plum` | 12.36 | 10.55 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:oxblood` | 7.03 | 6.13 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:shade:dark-berry` | 17.80 | 15.18 | shows |
| s3-mauve-smoky | wide | `eyes:bolder@gold` | 12.46 | 4.87 | quiet |
| s3-mauve-smoky | wide | `eyes:bolder@copper` | 6.30 | 2.60 | quiet |
| s3-mauve-smoky | wide | `eyes:softer@bronze` | 12.46 | 4.87 | quiet |
| s3-mauve-smoky | wide | `eyes:softer@plum` | 10.46 | 3.91 | quiet |
| s3-mauve-smoky | wide | `eyes:bolder@burgundy` | 10.46 | 3.91 | quiet |
| s3-mauve-smoky | wide | `cheeks:bolder@copper` | 3.51 | 2.86 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@coral-brick` | 3.51 | 2.86 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@coral-brick` | 3.20 | 2.47 | quiet |
| s3-mauve-smoky | wide | `cheeks:softer@mulled-rose` | 2.96 | 2.19 | quiet |
| s3-mauve-smoky | wide | `cheeks:bolder@mulled-rose` | 2.80 | 2.14 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@warm-berry` | 2.80 | 2.14 | shows |
| s3-mauve-smoky | wide | `cheeks:bolder@warm-berry` | 2.54 | 2.15 | shows |
| s3-mauve-smoky | wide | `cheeks:softer@deep-plum` | 2.54 | 2.15 | shows |
| s3-mauve-smoky | wide | `lips:bolder@bronze` | 5.77 | 4.65 | quiet |
| s3-mauve-smoky | wide | `lips:softer@caramel-nude` | 5.77 | 4.65 | quiet |
| s3-mauve-smoky | wide | `lips:bolder@caramel-nude` | 9.55 | 7.25 | shows |
| s3-mauve-smoky | wide | `lips:softer@brick` | 8.44 | 5.68 | shows |
| s3-mauve-smoky | wide | `lips:bolder@brick` | 7.09 | 5.59 | shows |
| s3-mauve-smoky | wide | `lips:softer@deep-red` | 7.09 | 5.59 | shows |
| s3-mauve-smoky | wide | `lips:bolder@deep-red` | 8.40 | 6.68 | quiet |
| s3-mauve-smoky | wide | `lips:softer@berry-rose` | 10.79 | 8.63 | shows |
| s3-mauve-smoky | wide | `lips:bolder@berry-rose` | 9.83 | 6.17 | shows |
| s3-mauve-smoky | wide | `lips:softer@berry-gloss` | 11.79 | 9.41 | shows |
| s3-mauve-smoky | wide | `lips:bolder@berry-gloss` | 14.31 | 7.69 | shows |
| s3-mauve-smoky | wide | `lips:softer@plum` | 4.73 | 3.87 | shows |
| s3-mauve-smoky | wide | `lips:bolder@plum` | 9.74 | 6.65 | shows |
| s3-mauve-smoky | wide | `lips:softer@oxblood` | 9.83 | 6.17 | shows |
| s3-mauve-smoky | wide | `lips:bolder@oxblood` | 9.08 | 6.19 | quiet |
| s3-mauve-smoky | wide | `lips:softer@dark-berry` | 9.74 | 6.65 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:bolder@gold` | 12.54 | 4.90 | quiet |
| s3-mauve-smoky | wide | `look:fresh+eyes:bolder@copper` | 6.32 | 2.61 | quiet |
| s3-mauve-smoky | wide | `look:fresh+eyes:softer@bronze` | 12.54 | 4.90 | quiet |
| s3-mauve-smoky | wide | `look:fresh+eyes:softer@plum` | 10.50 | 3.93 | quiet |
| s3-mauve-smoky | wide | `look:fresh+eyes:bolder@burgundy` | 10.50 | 3.93 | quiet |
| s3-mauve-smoky | wide | `look:fresh+eyes:softer@soft-gold` | 17.23 | 7.25 | shows |
| s3-mauve-smoky | wide | `look:fresh+eyes:bolder@soft-gold` | 18.32 | 7.83 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:bolder@copper` | 3.59 | 2.30 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:softer@coral-brick` | 3.59 | 2.30 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:bolder@coral-brick` | 3.04 | 1.97 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:softer@mulled-rose` | 3.05 | 1.97 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:bolder@mulled-rose` | 2.69 | 1.66 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:softer@warm-berry` | 2.69 | 1.66 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:bolder@warm-berry` | 2.93 | 1.73 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:softer@deep-plum` | 2.93 | 1.73 | shows |
| s3-mauve-smoky | wide | `look:fresh+cheeks:softer@soft-brick` | 2.13 | 1.40 | quiet |
| s3-mauve-smoky | wide | `look:fresh+cheeks:bolder@soft-brick` | 1.47 | 0.88 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@bronze` | 5.47 | 4.50 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@caramel-nude` | 5.47 | 4.50 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@caramel-nude` | 9.82 | 7.89 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@brick` | 8.26 | 5.73 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@brick` | 7.13 | 5.99 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@deep-red` | 7.13 | 5.99 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@deep-red` | 8.48 | 6.86 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@berry-rose` | 11.03 | 9.02 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@berry-rose` | 9.56 | 6.15 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@berry-gloss` | 11.77 | 9.62 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@berry-gloss` | 14.28 | 7.88 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@plum` | 4.49 | 3.83 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@plum` | 9.86 | 6.85 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@oxblood` | 9.56 | 6.15 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@oxblood` | 9.15 | 6.53 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@dark-berry` | 9.86 | 6.85 | shows |
| s3-mauve-smoky | wide | `look:fresh+lips:softer@warm-nude` | 6.34 | 5.42 | quiet |
| s3-mauve-smoky | wide | `look:fresh+lips:bolder@warm-nude` | 2.10 | 1.72 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:bolder@gold` | 12.19 | 4.55 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:bolder@copper` | 6.12 | 2.46 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:softer@bronze` | 12.19 | 4.55 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:softer@plum` | 9.80 | 3.57 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:bolder@burgundy` | 9.80 | 3.57 | quiet |
| s3-mauve-smoky | wide | `look:evening+eyes:bolder@copper-night` | 7.80 | 2.99 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:bolder@copper` | 3.48 | 2.86 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:softer@coral-brick` | 3.48 | 2.86 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:bolder@coral-brick` | 3.11 | 2.45 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:softer@mulled-rose` | 2.83 | 2.11 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:bolder@mulled-rose` | 2.73 | 2.13 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:softer@warm-berry` | 2.73 | 2.13 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:bolder@warm-berry` | 2.51 | 2.11 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:softer@deep-plum` | 2.51 | 2.11 | shows |
| s3-mauve-smoky | wide | `look:evening+cheeks:softer@dark-cherry` | 1.54 | 1.10 | quiet |
| s3-mauve-smoky | wide | `look:evening+cheeks:bolder@dark-cherry` | 2.96 | 2.44 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@bronze` | 5.77 | 4.64 | quiet |
| s3-mauve-smoky | wide | `look:evening+lips:softer@caramel-nude` | 5.77 | 4.64 | quiet |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@caramel-nude` | 9.85 | 7.71 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:softer@brick` | 8.45 | 5.78 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@brick` | 7.69 | 6.16 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:softer@deep-red` | 7.69 | 6.16 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@deep-red` | 10.11 | 7.88 | quiet |
| s3-mauve-smoky | wide | `look:evening+lips:softer@berry-rose` | 10.99 | 8.89 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@berry-rose` | 9.65 | 6.11 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:softer@berry-gloss` | 11.76 | 9.50 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@berry-gloss` | 14.25 | 7.82 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:softer@plum` | 4.49 | 3.80 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@plum` | 9.74 | 6.72 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:softer@oxblood` | 9.65 | 6.11 | shows |
| s3-mauve-smoky | wide | `look:evening+lips:bolder@oxblood` | 9.14 | 6.46 | quiet |
| s3-mauve-smoky | wide | `look:evening+lips:softer@dark-berry` | 9.74 | 6.72 | shows |
