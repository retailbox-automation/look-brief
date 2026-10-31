#!/usr/bin/env python3
"""Export an example agreed-look card (HTML + PDF) from a recorded sample, without any API call.

    uv run python scripts/export_card.py [sample_id] [out_dir]      # default: first visible sample, examples/

Starts the app on a free port (Replay, ephemeral key), walks the brief: artist answers every zone, both agree,
then saves agreed-look-card.html, agreed-look-card.pdf and the signed JSON.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "LOOKBRIEF_LIVE": "0", "LOOKBRIEF_ATTEST_EPHEMERAL": "1",
           "LOOKBRIEF_DATA": tempfile.mkdtemp(prefix="lb-card-"), "YOUCAM_API_KEY": "",
           "LOOKBRIEF_PUBLIC_URL": "https://lookbrief.retailbox-automation.com"}
    proc = subprocess.Popen([sys.executable, "-m", "lookbrief"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                samples = json.load(urllib.request.urlopen(base + "/healthz", timeout=1))["samples"]
                break
            except OSError:
                time.sleep(0.2)
        sid = sys.argv[1] if len(sys.argv) > 1 else samples[0]
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "examples"
        out.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 900, "height": 1200})
            page = ctx.new_page()
            page.goto(f"{base}/try/{sid}")
            page.wait_for_selector("#look:not([hidden])", timeout=30_000)
            api = ctx.request
            sess = page.url.rsplit("/", 1)[1]
            b = api.post(f"{base}/api/sessions/{sess}/brief").json()
            bid, bride, artist = b["brief_id"], b["bride_url"].split("t=")[1], b["artist_url"].split("t=")[1]
            view = api.get(f"{base}/api/briefs/{bid}?t={artist}").json()
            notes = {"cheeks": "I'll use a cream blush one shade cooler", "skin": "Same shade, light layer"}
            for z in view["snapshot"]["review_zones"]:
                status = "swap" if z == "cheeks" else "do"
                api.post(f"{base}/api/briefs/{bid}/review", data={"t": artist, "zone": z, "status": status,
                                                                  "note": notes.get(z, "")})
            api.post(f"{base}/api/briefs/{bid}/agree", data={"t": artist})
            v = api.post(f"{base}/api/briefs/{bid}/agree", data={"t": bride}).json()
            assert v["attestation"], "not signed"
            (out / "agreed-look-card.json").write_text(json.dumps(v["attestation"], indent=1))
            page.goto(f"{base}/card/{bid}?t={bride}")
            page.wait_for_load_state("networkidle")
            html = page.content()

            def inline_img(m: re.Match) -> str:  # self-contained copy: images as data URIs
                r = api.get(base + m.group(1).replace("&amp;", "&"))
                mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
                return f'src="data:{mime};base64,{base64.b64encode(r.body()).decode()}"'

            html = re.sub(r'src="(/[^"]+)"', inline_img, html)
            css = (ROOT / "src" / "lookbrief" / "static" / "app.css").read_text()
            html = re.sub(r'<link rel="stylesheet" href="/static/app.css"[^>]*>', f"<style>{css}</style>", html)
            html = re.sub(r'href="/api/briefs/[^"]+"', 'href="agreed-look-card.json"', html)
            (out / "agreed-look-card.html").write_text(html)
            page.pdf(path=str(out / "agreed-look-card.pdf"), format="A4", print_background=True,
                     margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
            browser.close()
        print(f"card for {sid}: {out}/agreed-look-card.pdf, .html, .json")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
