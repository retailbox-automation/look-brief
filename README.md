# Look Brief

**Agree on your wedding makeup before you pay for the trial.** The bride uploads her selfie and the photo she
loves. YouCam **AI Makeup Transfer** puts that exact makeup on *her* face and **AI Hair Transfer** adds the hair;
Look Brief measures the makeup on her eyelids, cheeks and lips, builds three looks from ready-made shades in nine
zones and renders them with **AI Makeup VTO**. She changes a shade or a style zone by zone, and sends the look to her
makeup artist, who confirms every zone by link without an account. The result is one agreed-look card, signed by
the server, so the paid trial only executes what both already saw.

- **Live demo:** https://lookbrief.retailbox-automation.com (Replay: recorded real YouCam API results, no key needed)
- **Run locally in 5 minutes:** see [Run it](#run-it-in-5-minutes)
- License: MIT · built for the YouCam API Skin AI & eCommerce VTO Hackathon (Perfect Corp, Devpost), Oct–Nov 2026

## Judge it in 90 seconds

| Claim | Check it | What you will see |
|---|---|---|
| Real YouCam API results, not mock-ups | Demo → any sample → caption under each picture; `samples/*/manifest.json`, `samples/*/fixtures/` | "Recorded real YouCam API result · task W6__…ldjt90TP · 6.6s · 2026-10-31T23:52:14Z"; the same task ids and sanitized API responses in the repo |
| Three YouCam APIs work as one flow | [API map](#how-it-works) below; `src/lookbrief/engine.py` | Makeup Transfer → Hair Transfer → Makeup VTO, chained per session |
| The distance from the transfer is measured and shown | [`docs/ACCURACY.md`](docs/ACCURACY.md), `uv run python scripts/accuracy_report.py` | The look is ready-made shades chosen for her skin, not a copy of the transfer: mean shade gap ΔE2000 **5.2** on 3 faces (eyelids 3.55, cheeks 4.63, lips 7.41), plus all nine zones |
| History: how the first computed recipe was calibrated | [`docs/CALIBRATION.md`](docs/CALIBRATION.md) | v1 3.2 → v2 1.97 on that earlier recipe, replaced by the ready-made shades |
| The bride's skin is kept, not beautified | `docs/ACCURACY.md` (skin control), [`docs/PLATFORM-FINDINGS.md`](docs/PLATFORM-FINDINGS.md) §1 | Forehead (no makeup) ΔE76 0.0 with `skin_smooth: 0` vs 4.70 with the API default |
| Patchy transfer blush, found and fixed with the API itself | [`docs/PLATFORM-FINDINGS.md`](docs/PLATFORM-FINDINGS.md) §10, `docs/platform-findings/transfer-blush/` | On a face with natural redness Makeup Transfer painted patchy blush for all 5 inspirations (14–32 % of the cheeks); hair first → transfer → a foundation in her shade over the transfer gives 4 %, lips stay at ΔE 0.66. The makeup map is read from that layer; no render carries it |
| The artist confirms each zone; the agreement is verifiable | Demo → "Create the brief link" → artist link → agree; `scripts/verify_card.py` | Ed25519 server attestation over zones, statuses, recipe hash and image hashes; tampering fails verification |
| Tested | `uv run pytest -q`; [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | 729 tests: colour maths vs Sharma 2005, zones, recipe schema, photo check, API client, replay fixtures, both pipeline orders, zone stacking against real multi-zone renders, security regressions, app API, Playwright smoke of both roles with axe WCAG A/AA = 0 violations |
| Every edit button visibly changes the face | [`docs/EDITS.md`](docs/EDITS.md), `tests/test_edit_visibility.py`, `uv run python scripts/edit_visibility_report.py` | Inside the zone the 90th percentile of ΔE2000 is at least 2.5 (brows 3.5); a step below that gets no button. Softer and Bolder go to the next shade of the same colour |
| Honest about cost | `samples/*/recording.json`, `docs/calibration/v1-recording.json`, `docs/platform-findings/` | YouCam credit is read before and after every recording; every result keeps its task id |
| No key in the browser or on the public server | `Dockerfile` (`LOOKBRIEF_LIVE=0`), `src/lookbrief/youcam.py` | Public demo is Replay-only; Live runs server-side with your own key |

## Why

A bride who rarely wears makeup brings a screenshot of someone else's face to a paid trial and often leaves
disappointed: the picture shows a different face, different skin and different light. Look Brief moves the
"is this my look?" moment before the trial and turns it into a brief both sides sign off on. It does not replace
the artist; it gives her a measured starting point and a written agreement.

## How it works

```
selfie + inspiration ──► photo check (local, before any unit is spent)
                         │
                         ├─► AI Makeup Transfer   POST /s2s/v2.0/task/mu-transfer    (2 units)
                         │      └─► makeup map: CIE Lab difference, zones from face landmarks
                         ├─► AI Hair Transfer     POST /s2s/v2.1/task/hair-transfer  (2 units, custom reference)
                         └─► recipe ─► AI Makeup VTO POST /s2s/v2.0/task/makeup-vto  (1 unit per render / edit)
                                         └─► accuracy: transfer vs re-render, per zone
brief link ─► artist: per zone "I'll do this / I'll swap the product / Let's discuss" ─► both agree
           ─► agreed-look card + server attestation (Ed25519)
```

| YouCam API | Endpoint | Our code | Example recorded task |
|---|---|---|---|
| AI Makeup Transfer | `POST /s2s/v2.0/task/mu-transfer` | `engine.py` `LiveEngine.makeup_transfer` | `k-uiHOuju22Y…` (s1, 6.7 s) |
| AI Hair Style — custom reference | `POST /s2s/v2.1/task/hair-transfer` | `engine.py` `LiveEngine.hair_transfer` | `LzsuLtj-Uzxm…` (s1, 6.6 s) |
| AI Makeup VTO | `POST /s2s/v2.0/task/makeup-vto` | `recipe.py` → `engine.py` `LiveEngine.render` | `0c0bebJoDZVg…` (s1 base, 6.7 s) |
| File upload | `POST /s2s/v2.0/file` + `PUT` | `youcam.py` `YouCamClient.upload` | — |
| Credit | `GET /s2s/v1.0/client/credit` | `youcam.py` `YouCamClient.credit` | read before/after every recording |

**The makeup map.** Makeup Transfer returns only a picture. Look Brief subtracts the bare selfie from the
transferred look in CIE Lab, marks pixels that visibly changed (ΔE76 > 6), and assigns them to zones built from
MediaPipe Face Landmarker points (nearest-feature cells around eyelids, cheeks, lips, nose, brows; the forehead is
a no-makeup control). Per zone it reports the median shade on the face, the bare-skin shade under it, strength
and coverage (`src/lookbrief/makeup_map.py`, `landmarks.py`).

**The recipe.** Nine zones: eyelids, eyeliner, lashes, brows, cheeks, bronzer, highlighter, lips, lip liner. Every
colour is a ready-made shade of the palette for her skin group; no colour is computed (`src/lookbrief/palettes.py`,
`recipe.py`). There are three looks: Classic, Soft glam and Evening. A concealer in her own colour sits under every
look, with `skin_smooth: 0` always and no foundation in any render. On a live photo the transfer picks the closest
shade on the lids, cheeks and lips. She taps a circle, Softer or Bolder (the next shade of the same colour) or a
named style of a thin zone; each change is a new render for 1 unit.

**Two orders.** The recorded samples s2 and s3 run Makeup Transfer, then Hair Transfer. The heroine sample and Live
run **hair first**: Hair Transfer on the selfie, then Makeup Transfer on her face with the new hair, so the map, the
metric and every render share the same light. They also record one more step: Makeup VTO puts a foundation in her
own shade (read from her forehead) on top of the transfer, so natural redness is not read as blush. The makeup map
is read from that layer. It is not a zone and no render carries it.

**Replay and Live.** Replay serves recorded real API results from `samples/` with their original task ids and
timestamps — the organiser confirmed this is acceptable for judging (Devpost forum, thread 45693). Live calls the
API from the server only, behind a consent screen, with a unit budget, a per-network daily limit and a
per-session cap; when any limit is reached it falls back to the recorded samples. Uploaded photos are deleted after
24 hours or on request.

**Zone choices stack.** One change shows the recorded render itself. Several changed zones have no recorded render, so
Replay assembles them on the server from recorded single-zone renders, one per zone, and says so on the photo, the brief
and the card; the signed record lists every component task id. Live makes one real call with the whole recipe.
[`docs/EDITS.md`](docs/EDITS.md) has the rule and the measurement.

## Run it in 5 minutes

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/retailbox-automation/look-brief && cd look-brief
uv sync
uv run lookbrief            # http://127.0.0.1:8731 — three recorded samples, no key needed
```

Or with Docker: `docker build -t lookbrief . && docker run -p 8080:8080 lookbrief` → http://127.0.0.1:8080

**Live mode with your own YouCam key** (6 units per look — hair, transfer, render and the foundation layer the map is read from — then 1 per zone edit):

```bash
cp .env.example .env        # put your key in YOUCAM_API_KEY (server side only, never in the browser)
LOOKBRIEF_LIVE=1 uv run --env-file .env lookbrief   # then open /live
```

Limits are environment variables: `LOOKBRIEF_LIVE_UNIT_BUDGET` (default 200), `LOOKBRIEF_LIVE_MIN_CREDIT` (100),
`LOOKBRIEF_LIVE_SESSIONS_PER_IP_DAY` (5), `LOOKBRIEF_LIVE_SESSION_UNIT_CAP` (12). Live status: `GET /api/limits`.

**Record your own sample** (rights-cleared faces only): put `bride.jpg` and `inspiration.jpg` in
`samples/<id>/` with a `sample.json`, then `uv run python scripts/record_sample.py samples/<id>`. The full grid costs
about 70 units; `--dry` lists it first and `--max-units` sets a ceiling.

## The agreed-look card and what the signature means

When the bride link and the artist link have both agreed on the same brief version — every zone answered, no
"Let's discuss" left open — the server signs a JSON statement with Ed25519: brief id and version, each zone's
product shade, intensity, the artist's answer and note, the recipe hash, the SHA-256 of every image, the YouCam
task ids, and both agreement times. It proves what this server recorded; it is **not** a personal signature of
either person. The public demo creates a fresh key at every start (the key lives until the container restarts)
and prints the public key on each card and at `/.well-known/lookbrief-attest.json`.

```bash
python scripts/verify_card.py look-brief-<id>.json \
  --key-url https://lookbrief.retailbox-automation.com/.well-known/lookbrief-attest.json
```

## Tests and checks

```bash
uv run pytest -q                 # 575 unit tests + 24 Playwright tests (run `uv run playwright install chromium` once)
uv run ruff check src tests scripts && uv run mypy src
```

The unit tests check CIEDE2000 against the 34 reference pairs of Sharma, Wu & Dalal (2005), zone geometry on the
recorded faces, cross-machine reproducibility of the recorded maps, the recipe against the documented Makeup VTO
schema and pattern catalog, a plain-language hint for every documented YouCam error code, the API client
(retries, error tasks, key never logged, signed URLs redacted), every replay fixture, and the whole app API
including Live on a fake client (consent, photo check, ledger, caps, budget fallback, deletion). The Playwright
smoke walks the bride and artist paths on a 390×844 phone viewport and runs axe-core (WCAG 2 A/AA) on every screen.

## Platform findings

Ten findings with evidence in this repo — [`docs/PLATFORM-FINDINGS.md`](docs/PLATFORM-FINDINGS.md). The four
that shaped the product: Makeup VTO smooths the whole face unless `skin_smooth` is set to 0; Makeup VTO is not
deterministic for eye shadow and lips (identical recipe, up to 2.13 ΔE2000 apart) while blush is; lip colour
lands darker than the hex it is given; and Makeup Transfer paints patchy blush on a face with natural redness,
which the hair-first order plus a foundation layer under the reading avoids with the API itself.

## Honest limits

- Previews, not photos: Hair Transfer also changes the forehead area (ΔE76 1.9–3.3). Transfer-first samples
  measure the map before hair; the hair-first order measures it on her face with the new hair.
- The look is built from ready-made shades and does not copy the transfer: on the recorded faces the gap is large,
  especially on lips and on one set of eyelids. The accuracy table shows it zone by zone.
- Samples hold what was recorded. A look with several changed zones is assembled from recorded zone renders, not one
  API call: against 18 real multi-zone renders the eye area sits at mean ΔE2000 0.70 before the JPEG and 1.15 after, and
  six zones on the whole face have no real render to compare with. A thin-zone style is recorded on Soft glam only: on
  Classic and Evening it is the step between two recorded renders, and a style with no such step is off.
- Nose and contour changes are reported but not re-rendered.
- No external users yet; the samples are fictional, AI-generated faces.
- The public demo is Replay-only; Live needs your own key.

## How AI was used

The YouCam API does the visual work (makeup transfer, hair transfer, makeup re-render). Sample faces and
inspiration photos are fictional people generated with ChatGPT Images for this project (no real person, no brand).
The code was written with the help of AI coding assistants and reviewed and tested by the team. No language model
runs inside the product.

## Project layout

```
src/lookbrief/   app.py (FastAPI) · youcam.py (API client) · engine.py (Live/Replay) · pipeline.py
                 landmarks.py · makeup_map.py · recipe.py · photo_check.py · attest.py · store.py (SQLite)
samples/         3 public recorded samples: inputs, results, sanitized fixtures, manifest, credit before/after
scripts/         record_sample.py · accuracy_report.py · calibration_report.py · verify_card.py · …
docs/            ACCURACY.md · CALIBRATION.md · PLATFORM-FINDINGS.md (+ evidence)
tests/           unit tests · e2e/ Playwright smoke
```

Third-party: MediaPipe Face Landmarker model (Google, Apache-2.0) in `src/lookbrief/models/`; YouCam API by
Perfect Corp. Team: Mikhail Oskola, Nadezhda Korchagina.
