# Edits that visibly change the face

Nadya tested the demo on an iPhone (31.10.2026): "I tap the lips, pick a strength — nothing changes." Two causes:
the "Makeup + hair" preview showed the Hair Transfer photo and ignored edits (fixed in `static/session.js`: an edit
always switches to the view that carries it), and the recorded edits moved the zone by only dE2000 0.5–1.5
(Makeup VTO barely reacts to intensity +-20 or a shade +-8 L*).

## The edit rule (`src/lookbrief/recipe.py`)
- **Softer:** product shade most of the way to her skin (eyes 0.0, cheeks
  0.2, lips 0.1 of the distance kept), intensity x
  0.25 / 0.4 / 0.3.
  **Not offered** where the zone's whole makeup (bare face -> base render) is below 3.5: softer cannot go
  past bare skin, so the button is off with "Softer: already close to your bare skin." (the server refuses it too).
- **Bolder:** a more vivid shade — chroma +28 / +34 /
  +18 (eyes / cheeks / lips), L* -6 /
  -8 / -0, intensity +20. Mostly chroma,
  so it never looks like lighter/deeper.
- **Lighter / Deeper:** L* +- 24 / 26 /
  14. Lighter lids end at least 14 L* above her skin
  (or they read as softer); a deeper shade that hits L* 5 takes the rest of the step as chroma.

## The gate (`src/lookbrief/visibility.py`, `tests/test_edit_visibility.py`)
Inside the zone outline the app draws (open eye and mouth left out), against the re-render without edits: every
offered edit **mean dE2000 >= 3.5** with **>= 60%** of pixels over 2.3
(just noticeable); every pair of edits of one zone **>= 3.0** (tapping one button after another must
change the photo too). Thresholds checked by eye on 1:1 zone crops; the recordings of build b05012a failed it.
Each recorded recipe equals what `recipe.apply_edit` makes today (test), so Replay shows what the code does.

## Measured (mean dE2000 in the zone, share of pixels over 2.3)
| Sample | Zone | Whole makeup | Softer | Bolder | Lighter | Deeper |
|---|---|---|---|---|---|---|
| s0-champagne-rose | eyes | 2.31 | off — already light | 4.37 (79%) | 6.39 (86%) | 6.51 (88%) |
| s0-champagne-rose | cheeks | 2.34 | off — already light | 4.65 (74%) | 3.63 (67%) | 3.86 (66%) |
| s0-champagne-rose | lips | 1.90 | off — already light | 3.88 (98%) | 5.75 (98%) | 5.74 (97%) |
| s1-soft-glam (hidden) | eyes | 6.27 | 5.87 (85%) | 4.75 (77%) | 9.01 (89%) | 5.83 (83%) |
| s1-soft-glam (hidden) | cheeks | 1.95 | off — already light | 4.20 (80%) | 3.70 (74%) | 4.01 (75%) |
| s1-soft-glam (hidden) | lips | 4.79 | 3.59 (92%) | 4.56 (98%) | 6.64 (99%) | 6.90 (98%) |
| s2-classic-red | eyes | 4.51 | 3.65 (67%) | 4.50 (81%) | 6.99 (92%) | 5.36 (87%) |
| s2-classic-red | cheeks | 3.01 | off — already light | 5.34 (86%) | 4.18 (77%) | 4.40 (77%) |
| s2-classic-red | lips | 16.78 | 13.31 (100%) | 4.44 (100%) | 9.01 (99%) | 7.83 (99%) |
| s3-mauve-smoky | eyes | 7.01 | 6.53 (77%) | 4.98 (74%) | 9.39 (84%) | 3.92 (68%) |
| s3-mauve-smoky | cheeks | 2.76 | off — already light | 4.20 (73%) | 4.30 (72%) | 4.56 (72%) |
| s3-mauve-smoky | lips | 13.33 | 9.63 (99%) | 5.65 (99%) | 6.69 (98%) | 6.01 (98%) |

| Sample | Pairs of one zone | Closest pair | Gate |
|---|---|---|---|
| s0-champagne-rose | 9 | 3.44 (cheeks:bolder>deeper) | PASS |
| s1-soft-glam | 15 | 3.29 (eyes:softer>lighter) | PASS |
| s2-classic-red | 15 | 3.91 (eyes:softer>lighter) | PASS |
| s3-mauve-smoky | 15 | 3.48 (eyes:softer>lighter) | PASS |
