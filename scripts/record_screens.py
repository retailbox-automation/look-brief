#!/usr/bin/env python3
"""Screen recordings of the guided path for the demo video, on a recorded sample (Replay, no API calls).

    uv run python scripts/record_screens.py OUT_DIR [--sample s0-champagne-rose]

One clip per step, phone viewport 390x844 @2x (MP4, 780x1688, 30 fps; frames from the DevTools screencast), plus a PNG per step at 1290x2796
(430x932 @3x). Steps: a-photos-check, b-transfer-reveal, c-zone-map, d-hair-even-out, e-cheeks-softer,
f-artist-brief, g-agreed-card. Every frame shows real recorded YouCam results with their Replay labels.
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


def new_session(browser, base: str, sample: str) -> tuple[str, list]:
    """Create a ready session in a throwaway context; return its URL and the owner cookie."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{base}/try/{sample}")
    page.wait_for_selector("#look:not([hidden])", timeout=30_000)
    url, cookies = page.url, ctx.cookies()
    ctx.close()
    return url, cookies


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


# ---------- the seven steps (each gets a ready page on its session) ----------
def step_a(page) -> None:  # photos + photo check (top of the look screen: inspiration -> you strip, check pill)
    pause(page, 1800)
    page.locator(".hero-strip").hover()
    pause(page, 2200)
    page.locator("#hero-check").scroll_into_view_if_needed()
    pause(page, 1500)


def step_b(page) -> None:  # transfer reveal: before/after slider
    page.locator("#ba").scroll_into_view_if_needed()
    pause(page, 800)
    for v in list(range(100, -1, -5)) + list(range(0, 51, 5)):
        page.locator("#ba").fill(str(v))
        page.wait_for_timeout(60)
    pause(page, 1500)


def step_c(page) -> None:  # zone map: tap each zone, outlines + sheet follow
    page.evaluate("window.scrollTo(0, 0)")
    pause(page, 900)
    for z in ("Eyelids", "Cheeks", "Lips"):
        page.get_by_role("button", name=z, exact=True).click()
        pause(page, 1600)


def step_d(page) -> None:  # hair is already in the look (hair first); toggle "Even out redness"
    page.evaluate("window.scrollTo(0, 0)")
    pause(page, 1200)
    for name in ("Even out redness", "Transfer", "Even out redness"):
        btn = page.get_by_role("button", name=name, exact=True)
        if btn.count():
            btn.click()
            pause(page, 1800)


def step_e(page) -> None:  # "Cheeks: softer" re-rendered by Makeup VTO (recorded)
    page.evaluate("window.scrollTo(0, 0)")
    page.get_by_role("button", name="Cheeks", exact=True).click()
    pause(page, 1200)
    page.get_by_role("button", name="Cheeks: softer").click()
    page.wait_for_selector("#edit-msg:has-text('Updated.')", timeout=20_000)
    pause(page, 2500)


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
    pause(page, 2000)


def step_g(page) -> None:  # the agreed-look card with the server attestation
    pause(page, 1500)
    for y in range(0, 2600, 120):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(90)
    pause(page, 1500)


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--sample", default="s0-champagne-rose")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    proc, base = start_server()
    made = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            def page_for(url: str, cookies: list, view: dict, scale: int, video_dir: Path | None):
                kw = {"viewport": view, "device_scale_factor": scale, "is_mobile": True, "has_touch": True}
                ctx = browser.new_context(**kw)
                if cookies:
                    ctx.add_cookies(cookies)
                page = ctx.new_page()
                page.goto(url)
                return ctx, page

            def brief_links(session_url: str, cookies: list) -> tuple[str, str, str]:
                ctx = browser.new_context()
                ctx.add_cookies(cookies)
                sid = session_url.rsplit("/", 1)[1]
                b = ctx.request.post(f"{base}/api/sessions/{sid}/brief").json()
                ctx.close()
                return b["brief_id"], b["bride_url"], b["artist_url"]

            steps = [("a-photos-check", step_a, "look"), ("b-transfer-reveal", step_b, "look"),
                     ("c-zone-map", step_c, "look"), ("d-hair-even-out", step_d, "look"),
                     ("e-cheeks-softer", step_e, "look"), ("f-artist-brief", step_f, "artist"),
                     ("g-agreed-card", step_g, "card")]
            for name, fn, where in steps:
                for kind in ("video", "png"):
                    url, cookies = new_session(browser, base, args.sample)
                    if where in ("artist", "card"):
                        bid, bride_url, artist_url = brief_links(url, cookies)
                        if where == "artist":
                            url = base + artist_url
                        else:  # sign it first, then film the card
                            api = browser.new_context().request
                            artist_t, bride_t = artist_url.split("t=")[1], bride_url.split("t=")[1]
                            v = api.get(f"{base}/api/briefs/{bid}?t={artist_t}").json()
                            for z in v["snapshot"]["review_zones"]:
                                api.post(f"{base}/api/briefs/{bid}/review", data={
                                    "t": artist_t, "zone": z, "status": "swap" if z == "cheeks" else "do",
                                    "note": "I'll use a cream blush, one shade cooler" if z == "cheeks" else ""})
                            api.post(f"{base}/api/briefs/{bid}/agree", data={"t": artist_t})
                            api.post(f"{base}/api/briefs/{bid}/agree", data={"t": bride_t})
                            url = f"{base}/card/{bid}?t={bride_t}"
                    tmp = Path(tempfile.mkdtemp(prefix=f"lb-{name}-")) if kind == "video" else None
                    view, scale = (VIDEO_VIEW, 2) if kind == "video" else (PNG_VIEW, 3)
                    ctx, page = page_for(url, cookies, view, scale, tmp)
                    if where == "look":
                        page.wait_for_selector("#look:not([hidden])", timeout=30_000)
                    else:
                        page.wait_for_load_state("networkidle")
                    rec = Screencast(ctx, page) if kind == "video" else None
                    if rec:
                        rec.start()
                    fn(page)
                    if kind == "png":
                        if where in ("artist", "card"):
                            page.evaluate("window.scrollTo(0, 0)")
                            pause(page, 400)
                        page.screenshot(path=str(out / f"{name}.png"))
                        made.append(f"{name}.png")
                    if rec and tmp is not None:
                        rec.stop()
                        mp4 = out / f"{name}.mp4"
                        rec.encode(tmp, mp4)
                        made.append(mp4.name)
                        shutil.rmtree(tmp, ignore_errors=True)
                    ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    (out / "README.json").write_text(json.dumps({
        "sample": args.sample, "made": made, "video": "390x844 @2x", "png": "430x932 @3x = 1290x2796",
        "source": "Replay of recorded real YouCam API results (no API calls); scripts/record_screens.py"}, indent=1))
    print("\n".join(made))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
