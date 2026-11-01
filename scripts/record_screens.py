#!/usr/bin/env python3
"""Screen recordings of the guided path for the demo video, on a recorded sample (Replay, no API calls).

    uv run python scripts/record_screens.py OUT_DIR [--sample s0-champagne-rose]

One clip per step, phone viewport 390x844 @2x (MP4, 780x1688, 30 fps; frames from the DevTools screencast), plus a PNG per step at 1290x2796
(430x932 @3x). Steps, all on ONE bride session: a-photos-check, b-before-after, c-zone-map, d-looks, e-shade-circle,
e2-liner-style (when the sample offers it), f-artist-brief, g-agreed-card; plus h-samples (home page, two other
looks) and h-home.png. Every frame shows real recorded YouCam results with their Replay labels.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO_VIEW = {"width": 390, "height": 844}
PNG_VIEW = {"width": 430, "height": 932}


def start_server() -> tuple[subprocess.Popen, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "LOOKBRIEF_LIVE": "0", "LOOKBRIEF_ATTEST_EPHEMERAL": "1",
           "LOOKBRIEF_DATA": tempfile.mkdtemp(prefix="lb-rec-"), "YOUCAM_API_KEY": "",
           "LOOKBRIEF_PUBLIC_URL": "https://lookbrief.retailbox-automation.com"}
    proc = subprocess.Popen([sys.executable, "-m", "lookbrief"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            return proc, base
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not start")


class Screencast:
    """Records device-pixel frames through the Chrome DevTools screencast (Playwright's own video recorder
    captures at CSS pixels, so a 2x viewport came out half-size in a grey frame)."""

    def __init__(self, ctx, page):
        self.cdp = ctx.new_cdp_session(page)
        self.frames: list[tuple[float, bytes]] = []
        self.cdp.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, params: dict) -> None:
        import base64

        self.frames.append((float(params["metadata"]["timestamp"]), base64.b64decode(params["data"])))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    def start(self) -> None:
        self.t0 = time.time()
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 780, "maxHeight": 1688,
                                               "everyNthFrame": 1})

    def stop(self) -> None:
        self.t_end = time.time()
        self.cdp.send("Page.stopScreencast")

    def encode(self, tmp: Path, mp4: Path) -> None:
        if not self.frames:
            raise RuntimeError("no frames captured")
        lines = []
        for i, (ts, data) in enumerate(self.frames):
            f = tmp / f"{i:05d}.jpg"
            f.write_bytes(data)
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else max(self.t_end, ts + 0.5)
            lines += [f"file '{f}'", f"duration {max(nxt - ts, 1 / 60):.4f}"]
        lines.append(f"file '{tmp / f'{len(self.frames) - 1:05d}.jpg'}'")
        (tmp / "list.txt").write_text("\n".join(lines) + "\n")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                        "-vf", "scale=780:1688:force_original_aspect_ratio=decrease,pad=780:1688:(ow-iw)/2:(oh-ih)/2:color=white,fps=30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18", str(mp4)], check=True)


def pause(page, ms: int) -> None:
    page.wait_for_timeout(ms)


# ---------- the seven steps, filmed in ONE session: the edit of (e) is what the artist (f) and the card (g) show ----------
STORY_SHADE = ("Lips", "Lips: Ruby")  # the circle of (e); the most visible change on the heroine's lips
STORY_STYLE = ("Eyeliner", "Eyeliner: Wing")  # a named style of a thin zone
LOOKS = ("Classic", "Evening", "Soft glam")


def step_a(page) -> None:  # photos + photo check (top of the look screen: inspiration -> you strip, check pill)
    pause(page, 1800)
    page.locator(".hero-strip").hover()
    pause(page, 2200)
    page.locator("#hero-check").scroll_into_view_if_needed()
    pause(page, 1500)


def prep_b(page) -> None:  # the slider starts at the left edge, in view, before the clip starts
    page.locator("#ba").scroll_into_view_if_needed()
    page.locator("#ba").fill("0")
    pause(page, 300)


def step_b(page) -> None:  # before and after: one smooth move of the slider from left to right, handle visible
    pause(page, 700)
    for v in range(0, 101):
        page.locator("#ba").fill(str(v))
        page.wait_for_timeout(24)
    pause(page, 1500)


def prep_top(page) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    pause(page, 300)


def step_c(page) -> None:  # zone map over her look: outlines first, then the zones (outlines step aside)
    pause(page, 2600)
    for z in ("Eyelids", "Cheeks", "Lips"):
        page.get_by_role("button", name=z, exact=True).click()
        pause(page, 1300)


def prep_sheet(page) -> None:  # the buttons and as much of the photo as fits
    page.evaluate("window.scrollTo(0, 260)")
    pause(page, 300)


def step_d(page) -> None:  # another look with one tap, each held on screen, back to the first
    pause(page, 1000)
    for name in LOOKS:
        page.get_by_role("button", name=name, exact=True).click()
        page.wait_for_selector(f".look-btn[aria-pressed=true]:has-text('{name}')", timeout=20_000)
        page.evaluate("window.scrollTo(0, 0)")
        pause(page, 2400)


def prep_e(page) -> None:  # the zone of the story is open, the photo and the circles both on screen
    page.evaluate("window.scrollTo(0, 0)")
    page.get_by_role("button", name=STORY_SHADE[0], exact=True).click()
    pause(page, 300)


def step_e(page) -> None:  # a circle: ~1 s, tap, the photo comes back into view, hold the result >= 3 s
    pause(page, 1000)
    page.get_by_role("button", name=STORY_SHADE[1], exact=True).click()
    page.wait_for_selector("#edit-msg:has-text('Updated')", timeout=20_000)
    pause(page, 3400)


def style_offered(page) -> bool:
    """A sample's quiet list can hide the story's style."""
    return page.get_by_role("button", name=STORY_STYLE[1], exact=True).count() > 0


def prep_e2(page) -> None:  # one recorded change at a time: back to her look off camera
    page.get_by_role("button", name="Undo last change").click()
    page.wait_for_selector("#edit-msg:has-text('Undone')", timeout=20_000)
    page.evaluate("window.scrollTo(0, 0)")
    pause(page, 300)


def step_e2(page) -> None:  # a style by name: the zone, the style, hold the result
    pause(page, 800)
    page.get_by_role("button", name=STORY_STYLE[0], exact=True).click()
    pause(page, 700)
    page.get_by_role("button", name=STORY_STYLE[1], exact=True).click()
    page.wait_for_selector("#edit-msg:has-text('Updated')", timeout=20_000)
    pause(page, 3000)


def step_f(page) -> None:  # the artist's link: answer every zone, add a note, agree
    pause(page, 1200)
    reviews = page.locator("fieldset.review")
    for i in range(reviews.count()):
        fs = reviews.nth(i)
        fs.scroll_into_view_if_needed()
        zone = (fs.get_attribute("data-testid") or "").replace("review-", "")
        label = "I'll swap the product" if zone == "cheeks" else "I'll do this"
        fs.get_by_label(label).check()
        pause(page, 700)
        if zone == "cheeks":
            note = page.locator("input[name=note-cheeks]")
            note.click()
            note.type("I'll use a cream blush, one shade cooler", delay=35)
            note.press("Tab")
            pause(page, 600)
    page.get_by_role("button", name="Agree to this look").scroll_into_view_if_needed()
    pause(page, 600)
    page.get_by_role("button", name="Agree to this look").click()
    page.wait_for_selector("#agree-help:has-text('Waiting for the bride')", timeout=10_000)
    pause(page, 2000)


def step_g(page) -> None:  # the agreed-look card with the server attestation
    pause(page, 1500)
    for y in range(0, 2600, 120):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(90)
    pause(page, 1500)


def step_h(page, base: str) -> None:  # the home page lists different looks: open two of them (5-7 s)
    pause(page, 700)
    for sid in ("s2-classic-red", "s3-mauve-smoky"):
        page.get_by_test_id(f"sample-{sid}").scroll_into_view_if_needed()
        page.get_by_test_id(f"sample-{sid}").click()
        page.wait_for_selector("#look:not([hidden])", timeout=30_000)
        pause(page, 1500)
        if sid != "s3-mauve-smoky":
            page.go_back()
            page.wait_for_selector("[data-testid^=sample-]", timeout=10_000)
            pause(page, 300)


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--sample", default="s0-champagne-rose")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    proc, base = start_server()
    made: list[str] = []
    checks: dict = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for kind in ("video", "png"):
                view, scale = (VIDEO_VIEW, 2) if kind == "video" else (PNG_VIEW, 3)
                ctx = browser.new_context(viewport=view, device_scale_factor=scale, is_mobile=True, has_touch=True)

                def film(page, name: str, fn, prep=None, top_png: bool = False, ctx=ctx, kind=kind) -> None:
                    if prep:
                        prep(page)
                    rec = Screencast(ctx, page) if kind == "video" else None
                    tmp = Path(tempfile.mkdtemp(prefix=f"lb-{name}-")) if rec else None
                    if rec:
                        rec.start()
                    fn(page)
                    if rec and tmp is not None:
                        rec.stop()
                        rec.encode(tmp, out / f"{name}.mp4")
                        made.append(f"{name}.mp4")
                        shutil.rmtree(tmp, ignore_errors=True)
                    else:
                        if top_png:
                            page.evaluate("window.scrollTo(0, 0)")
                            pause(page, 400)
                        page.screenshot(path=str(out / f"{name}.png"))
                        made.append(f"{name}.png")

                # one bride session for (a)-(e); the brief is sent from it, so (f) and (g) carry her edit
                look = ctx.new_page()
                look.goto(f"{base}/try/{args.sample}")
                look.wait_for_selector("#look:not([hidden])", timeout=30_000)
                film(look, "a-photos-check", step_a, prep_top)
                film(look, "b-before-after", step_b, prep_b)
                film(look, "c-zone-map", step_c, prep_top)
                film(look, "d-looks", step_d, prep_sheet)
                film(look, "e-shade-circle", step_e, prep_e)
                filmed_style = style_offered(look)
                if filmed_style:
                    prep_e2(look)
                    film(look, "e2-liner-style", step_e2)
                look.get_by_role("button", name="Send brief to my makeup artist").click()
                look.wait_for_selector("[data-testid=artist-link][href^='/b/']", timeout=10_000)
                artist_url = look.get_by_test_id("artist-link").get_attribute("href")
                bride_url = look.get_by_test_id("bride-link").get_attribute("href")
                bid, artist_t, bride_t = artist_url.split("/b/")[1].split("?")[0], artist_url.split("t=")[1], \
                    bride_url.split("t=")[1]
                snap = ctx.request.get(f"{base}/api/briefs/{bid}?t={artist_t}").json()["snapshot"]
                edits = snap.get("edits") or []
                checks[kind] = {"edits": edits, "style_filmed": filmed_style}
                artist = ctx.new_page()
                artist.goto(base + artist_url)
                artist.wait_for_load_state("networkidle")
                film(artist, "f-artist-brief", step_f, top_png=True)
                ctx.request.post(f"{base}/api/briefs/{bid}/agree", data={"t": bride_t})  # she agrees too
                card = ctx.new_page()
                card.goto(f"{base}/card/{bid}?t={bride_t}")
                card.wait_for_load_state("networkidle")
                wanted = "render-" + "_".join(f"{z}-{op.replace(':', '-')}" for z, op in edits)
                checks[kind]["card_has_edit_render"] = bool(edits) and wanted in card.content()
                if not checks[kind]["card_has_edit_render"]:
                    raise RuntimeError(f"the edit of (e) did not reach the brief and the card: {checks[kind]}")
                film(card, "g-agreed-card", step_g, top_png=True)
                # (h) the home page: different looks, two of them opened
                home = ctx.new_page()
                home.goto(base + "/")
                home.wait_for_selector("[data-testid^=sample-]", timeout=10_000)
                if kind == "png":
                    pause(home, 600)
                    home.screenshot(path=str(out / "h-home.png"))
                    made.append("h-home.png")
                else:
                    film(home, "h-samples", lambda pg: step_h(pg, base))
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    (out / "README.json").write_text(json.dumps({
        "sample": args.sample, "made": made, "video": "390x844 @2x", "png": "430x932 @3x = 1290x2796",
        "one_session": "a-e on one bride session; the brief is sent from it after the edit, so f and g show it",
        "edit_carried": checks,
        "source": "Replay of recorded real YouCam API results (no API calls); scripts/record_screens.py"}, indent=1))
    print("\n".join(made))
    print(json.dumps(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
