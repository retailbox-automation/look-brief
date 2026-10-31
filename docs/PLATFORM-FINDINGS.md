# Platform findings — YouCam API, seen while building Look Brief

Format: what we expected → what we got → how to reproduce → evidence in this repo. All measurements are on
files committed here; dates are 2026-10-31 (UTC). Nothing here is a complaint: most findings shaped the design.

## 1. Makeup VTO smooths the whole face unless you say `skin_smooth: 0`
- **Expected:** a lip/eye/blush recipe changes only those areas.
- **Got:** without a `skin_smooth` effect the engine applies its default smoothing to the entire face. On sample
  s1 the forehead (no makeup) moves by median ΔE76 **4.70** vs the bare selfie; with
  `{"category":"skin_smooth","skinSmoothStrength":0,"skinSmoothColorIntensity":0}` it moves by **0.0**.
- **Why it matters:** a makeup brief must not quietly beautify the bride; we always send `skin_smooth: 0`.
- **Repro:** `uv run python scripts/finding_default_smoothing.py` (1 unit; reuses the file if present).
- **Evidence:** `docs/platform-findings/s1-soft-glam-default-smoothing.{png,json}` (task id, effects sent, credit
  885 → 884) vs `samples/s1-soft-glam/results/render__base.png`.

## 2. Makeup VTO is not deterministic for eye shadow and lip colour (blush is)
- **Expected:** the same recipe on the same photo gives the same picture.
- **Got:** the identical recipe rendered twice differed by up to **2.13 ΔE2000** on eyelids (s2: 4.47 vs 2.34
  against the transfer) and up to 1.28 on lips; blush repeated within **0.04**.
- **Why it matters:** single-zone differences under ~1 ΔE are noise, so our accuracy table reports means over
  zones and samples and every claim is measured on committed images.
- **Evidence / repro:** `docs/CALIBRATION.md` (columns "v1 first pass" vs "v1 re-rendered for the record"),
  `docs/calibration/*-v1-base.*` with task ids; `uv run python scripts/calibration_report.py`.

## 3. Makeup VTO lands lip colour darker than the hex it is given
- **Expected:** a lip render close to the requested shade on the lips.
- **Got:** on all three samples the re-rendered lips were darker than the transfer at the same hex; one
  "a shade lighter" step (L* +8) cut the lip gap from 6.95 / 6.09 / 4.77 to 2.70 / 1.59 / 2.31 ΔE2000.
- **What we did:** the recipe lifts lip L* by 8 by default (`src/lookbrief/recipe.py`, `TUNING["lips"]`).
- **Evidence:** `docs/CALIBRATION.md`; recorded edit renders `samples/*/results/render__lips__lighter.png`.

## 4. Makeup Transfer returns a picture, not parameters — and keeps the bride's skin
- **Expected:** some description of the transferred makeup (colours, zones).
- **Got:** `results.url` only. We recover the makeup by pixel difference in CIE Lab, split by face landmarks.
  The transfer leaves skin untouched: forehead ΔE76 0.37 / 0.44 / 0.73 on the three samples
  (`docs/ACCURACY.md`), and the Facial Color Tones Analyzer saw skin `#be9d88` → `#bf9d86` (ΔE2000 0.74) on our
  development photo — so a "foundation mismatch" warning cannot come from the analyzer.

## 5. Hair Transfer also changes the forehead area
- **Got:** after Hair Transfer (custom reference) the forehead differs from the makeup-only result by median
  ΔE76 2.65 / 1.92 / 3.27 (new hairline/fringe and light), vs 0.37–0.73 for Makeup Transfer.
- **What we did:** in the transfer-first samples the makeup map is measured on the Makeup Transfer result,
  before hair. The newer **hair_first** order runs Hair Transfer on the selfie first and Makeup Transfer on that
  "base", so the map, the metric and every re-render share the same light (`src/lookbrief/pipeline.py`).

## 6. Output formats and sizes differ between endpoints
- Makeup Transfer and Hair Transfer return JPEG at the input size; Makeup VTO returns **PNG (RGBA)**, and for a
  769×1024 input it returned 770×1022. We keep the real format (`engine.image_ext`) and resample every output
  onto the input grid before pixel comparisons (`makeup_map.to_rgb_array`).

## 7. `lip_color` without `style` → HTTP 400 with one merged message for 7 oneOf variants
- **Got:** `"category is not one of the accepted values., or pattern is required …, or colorUnderEyeIntensity,
  coverageLevel is required …"` — the real cause (missing `style: {"type":"full"}`) is not named.
- **Evidence:** `docs/platform-findings/fixtures/makeup-vto-lip_color-without-style-400.json`; guarded by
  `tests/test_recipe.py::test_vto_effects_match_documented_schema`.

## 8. A failed task is HTTP 200 with `task_status: "error"` — and costs nothing
- **Got:** `error_ref_no_face` arrives as a 200 poll response; credit 954 → 954 around it.
- **What we did:** the photo check runs locally before any unit is spent and every documented error code has a
  plain-language hint (`src/lookbrief/photo_check.py`, test `test_every_documented_error_code_has_a_plain_hint`).
- **Evidence:** `docs/platform-findings/fixtures/mu-transfer-error_ref_no_face-http200.json`,
  `…/error-task-units-not-charged.json`.

## 9. Small API edges
- `GET /s2s/v2.0/task/template/look-vto?page_size=50` → 400 "page_size is above the allowed maximum." (20 works):
  `fixtures/look-vto-templates-page_size-50-400.json`, `…-20-200.json`.
- `GET /s2s/v2.0/credit/feature-cost` lists 20 SKUs and none of the makeup features:
  `fixtures/feature-cost-skus.json` — we verify prices by reading credit before/after (`samples/*/recording.json`).
- Result links expire after 2 hours (`X-Amz-Expires=7200`): results are downloaded immediately and signed URLs
  are redacted from every stored fixture (`youcam.redact`, test `test_fixtures_are_sanitized`).

## 10. Makeup Transfer adds blotchy blush to a face with natural cheek redness — whatever the inspiration
- **Expected:** blush in the result roughly follows the inspiration (some inspirations have almost none).
- **Got:** on one selfie with natural redness and freckles, five different inspirations gave a visibly patchy red
  blush every time. Share of the cheek area the transfer changed: A 30 %, B 14 %, C 22 %, D 32 %, E 16 % — even C
  and E, whose blush is nearly invisible. Changing the inspiration does not fix it. Running Hair Transfer after
  the blush was softened brings the redness back (cheek area 5 % → 17 %): Hair Transfer relights the face (§5).
- **What worked (all real API calls, no retouching):** Hair Transfer on the selfie → Makeup Transfer on that →
  Makeup VTO **on top of the transfer** with a foundation in her own shade (forehead colour), coverage 30, no
  smoothing. Blush area fell to 4 % (measured against the haired base), the lips stayed as transferred (ΔE2000 to
  the inspiration 0.66), eyelids 2.6. Freckles get softer too — it is a foundation. In the app this is the
  "Even out redness" step, labelled "foundation in her shade over the transfer", and the artist confirms it as a zone.
- **Also tried:** re-rendering from the bare face with "Cheeks: softer" removes the patches but VTO paints its own,
  darker lips (ΔE 4.8–7.5); a recipe read straight from the inspiration photo gives no patches but flatter colours
  (eyes and lips ΔE 5.5–9.2).
- **Evidence:** `docs/platform-findings/transfer-blush/` — selfie, inspirations A–E, transfers A–E, the three fix
  steps (`fix-1-hair`, `fix-2-transfer`, `fix-3-foundation`) and `evidence.json` with task ids and numbers.
