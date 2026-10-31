#!/usr/bin/env python3
"""Record a Replay sample from real YouCam API calls.

    uv run python scripts/record_sample.py samples/<id> [--grid single|none] [--max-units 25]

The folder must contain bride.jpg and inspiration.jpg (rights-cleared: our own or generated faces).
Runs: photo check -> Makeup Transfer -> Hair Transfer -> makeup map -> base re-render -> (optional)
one re-render per single-zone edit. Writes results/, fixtures/ (signed URLs redacted, no file ids)
and manifest.json. Credit is read before and after and saved in recording.json.
Key: env YOUCAM_API_KEY, or LOOKBRIEF_KEYCHAIN=1 on macOS. Units are spent only on success.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lookbrief import photo_check, pipeline  # noqa: E402
from lookbrief import recipe as rcp  # noqa: E402
from lookbrief.config import youcam_key  # noqa: E402
from lookbrief.engine import LiveEngine, Recorder, SessionCtx, StepMeta, StepResult  # noqa: E402
from lookbrief.makeup_map import MakeupMap  # noqa: E402
from lookbrief.youcam import UNITS, YouCamClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample_dir", type=Path)
    ap.add_argument("--grid", choices=["single", "none"], default="single")
    ap.add_argument("--order", choices=["transfer_first", "hair_first"], default="transfer_first",
                    help="hair_first: Hair Transfer on the selfie first, Makeup Transfer on that, plus the even-out step")
    ap.add_argument("--max-units", type=int, default=25)
    ap.add_argument("--only-edits", action="store_true", help="skip transfer; add renders to an existing sample")
    ap.add_argument("--reuse-transfer", type=Path, metavar="META_JSON",
                    help="use an already paid Makeup Transfer result (JSON with task_id etc.; .jpg next to it)")
    ap.add_argument(
        "--rerender",
        action="store_true",
        help="keep the recorded transfer and map; replace every recipe render (after a tuning change)",
    )
    args = ap.parse_args()
    sd: Path = args.sample_dir
    key = youcam_key()
    if not key:
        print("no key: set YOUCAM_API_KEY or LOOKBRIEF_KEYCHAIN=1", file=sys.stderr)
        return 2

    checks = {}
    jpegs = {}
    for role, name in (("bride", "bride.jpg"), ("inspiration", "inspiration.jpg")):
        res, img = photo_check.check((sd / name).read_bytes(), role)
        checks[role] = res.to_dict()
        if not res.ok or img is None:
            print(json.dumps(checks, indent=1))
            print(f"photo check blocked {role}; nothing spent", file=sys.stderr)
            return 3
        jpegs[role] = photo_check.to_jpeg(img)

    planned = 0 if args.only_edits else UNITS["mu-transfer"] + UNITS["hair-transfer"] + UNITS["makeup-vto"]
    if args.order == "hair_first" and not args.only_edits:
        planned += UNITS["makeup-vto"]  # even-out
    ledger_path = ROOT / "data" / "units-ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def ledger(op: str, units: int, task_id: str, ok: bool) -> None:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sample": sd.name,
            "op": op,
            "units": units,
            "task_id": task_id,
            "ok": ok,
        }
        with ledger_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"  {rec['ts']} {op} ok={ok} units={units} task={task_id}")

    client = YouCamClient(key, call_log=ROOT / "data" / "youcam-calls.jsonl")
    recorder = Recorder(sd)
    engine = LiveEngine(client, ledger=ledger, recorder=recorder)
    ctx = SessionCtx(jpegs["bride"], jpegs["inspiration"])
    work = ROOT / "data" / "record" / sd.name
    credit_before = client.credit()
    print(f"credit before: {credit_before}")
    if args.reuse_transfer:
        meta_in = json.loads(args.reuse_transfer.read_text())
        img_path = args.reuse_transfer.with_suffix(".jpg")
        reused = StepResult(img_path.read_bytes(), StepMeta("mu_transfer", "live", meta_in["task_id"], meta_in["seconds"],
                                                            meta_in["units"], meta_in["recorded_at"]))

        def reuse(ctx_: SessionCtx) -> StepResult:
            ctx_.ids["mu_jpeg"] = reused.image
            recorder.add("mu_transfer", reused.image, reused.meta, {"reused": str(args.reuse_transfer.name)},
                         {"note": "recorded earlier by the same script family; see the source JSON"})
            return reused

        engine.makeup_transfer = reuse  # type: ignore[method-assign]
        planned -= UNITS["mu-transfer"]
    if args.rerender:
        state = json.loads((work / "state.json").read_text())
        if state.get("order") == "hair_first":  # re-renders run on her face with the new hair (and carry the even-out)
            ctx.ids["base_jpeg"] = (work / state["images"]["base"]).read_bytes()
        for key in [k for k in recorder.manifest["steps"] if k.startswith("render:")]:
            step = recorder.manifest["steps"].pop(key)
            (sd / step["image"]).unlink(missing_ok=True)
            (sd / "fixtures" / (Path(step["image"]).stem + ".json")).unlink(missing_ok=True)
        recorder.save()
        # re-measure the map from the current reference (the evened look for hair first) before re-rendering
        mmap = pipeline.measure_map(work, state, pipeline.face_of(work, state["bare"]))
        recorder.set_map(mmap.to_dict())
        state["recipe_base"] = rcp.base_recipe(MakeupMap.from_dict(recorder.manifest["map"]))
        state = pipeline.rerender(engine, ctx, work, state, [])
        planned = UNITS["makeup-vto"]
    elif args.only_edits:
        state = json.loads((work / "state.json").read_text())
    else:
        state = pipeline.build_look(engine, ctx, work, recorder=recorder, order=args.order)
    spent = planned
    base_state = copy.deepcopy(state)
    if args.grid == "single":
        for zone in list(state["recipe_base"]["zones"]):
            for op in rcp.EDIT_OPS:
                edits = [[zone, op]]
                if f"render:{rcp.edit_key(edits)}" in recorder.manifest["steps"]:
                    continue
                if spent + UNITS["makeup-vto"] > args.max_units:
                    print(f"stop: --max-units {args.max_units} reached")
                    break
                pipeline.rerender(engine, ctx, work, state, edits)
                spent += UNITS["makeup-vto"]
        state = base_state
    credit_after = client.credit()
    (work / "state.json").write_text(json.dumps(state, indent=1))
    rec_path = sd / "recording.json"
    history = json.loads(rec_path.read_text()) if rec_path.exists() else []
    history.append(
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "credit_before": credit_before,
            "credit_after": credit_after,
            "units_spent": credit_before - credit_after,
            "photo_check": checks,
        }
    )
    rec_path.write_text(json.dumps(history, indent=1))
    print(f"credit after: {credit_after} (spent {credit_before - credit_after})")
    print(json.dumps({"gaps": state["gaps"], "skin_control_de": state["map"]["skin_control_de"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
