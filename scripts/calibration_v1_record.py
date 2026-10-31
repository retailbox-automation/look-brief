#!/usr/bin/env python3
"""Re-render the PRE-calibration (v1) base recipes of the 3 samples so the "before" number is checkable.

v1 recipe rule (replaced 2026-10-31): intensity from colour strength (eyes 8.5/ΔE, cheeks 12.5/ΔE, lips 5.5/ΔE),
product shade = skin + gain*(look-skin) with gains 1.8 / 2.5 / 1.15, no lip lift. The exact v1 recipes are in
docs/calibration/v1-recipes.json (as recorded in the first pass). Writes docs/calibration/<sample>-v1-base.png
+ a sanitized fixture. 1 unit per sample. Key: YOUCAM_API_KEY or LOOKBRIEF_KEYCHAIN=1.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lookbrief.config import youcam_key  # noqa: E402
from lookbrief.engine import LiveEngine, SessionCtx, image_ext  # noqa: E402
from lookbrief.youcam import YouCamClient, redact  # noqa: E402

OUT = ROOT / "docs" / "calibration"


def main() -> int:
    recipes = json.loads((OUT / "v1-recipes.json").read_text())
    client = YouCamClient(youcam_key(), call_log=ROOT / "data" / "youcam-calls.jsonl")
    eng = LiveEngine(client)
    before = client.credit()
    for sid, recipe in recipes["recipes"].items():
        sd = ROOT / "samples" / sid
        ctx = SessionCtx((sd / "bride.jpg").read_bytes(), (sd / "inspiration.jpg").read_bytes())
        res = eng.render(ctx, recipe, [["calibration", "v1"]])
        name = f"{sid}-v1-base{image_ext(res.image)}"
        (OUT / name).write_bytes(res.image)
        (OUT / f"{sid}-v1-base.json").write_text(
            json.dumps(
                redact(
                    {
                        "sample": sid,
                        "task_id": res.meta.task_id,
                        "recorded_at": res.meta.recorded_at,
                        "seconds": res.meta.seconds,
                        "units": res.meta.units,
                        "recipe": recipe,
                        "image": name,
                    }
                ),
                indent=1,
            )
        )
        print(sid, res.meta.task_id[:12], name)
    after = client.credit()
    (OUT / "v1-recording.json").write_text(
        json.dumps(
            {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "credit_before": before, "credit_after": after},
            indent=1,
        )
    )
    print("credit", before, "->", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
