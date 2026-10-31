#!/usr/bin/env python3
"""Record a Replay sample from real YouCam API calls.

    uv run python scripts/record_sample.py samples/<id> [--grid palette|none] [--max-units 25] [--dry]

The folder must contain bride.jpg and inspiration.jpg (rights-cleared: our own or generated faces); `recipe_pins` in
sample.json pin the recipe to an approved look. Runs: photo check -> Makeup Transfer -> makeup map -> base render ->
Hair Transfer (before the transfer in a hair-first sample, on the base render otherwise) -> the grid: every circle of
every zone, the finishes of lips and lids, the other looks. Softer and Bolder need no render of their own.

What the sample already holds is kept and costs nothing: a transfer, a hair-first Hair Transfer, the even-out, any
render with the same recipe. A render made under an older rule or palette is dropped. A run stopped by --max-units
(exit code 4) resumes where it stopped. Writes results/, fixtures/ (signed URLs redacted, no file ids) and manifest.json.
Credit is read before and after and saved in recording.json. --dry prints the paid steps and spends nothing, no key.
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
from lookbrief.engine import BudgetReached, GridEngine, Recorder, SessionCtx, hair_label  # noqa: E402
from lookbrief.youcam import UNITS, YouCamClient  # noqa: E402

VTO = UNITS["makeup-vto"]


def wanted_renders(base: dict, grid: str) -> dict[str, dict]:
    """Render step -> the recipe it must hold."""
    edits = [[], *rcp.record_grid(base)] if grid == "palette" else [[]]
    return {f"render:{rcp.edit_key(e)}": rcp.apply_edits(base, e) for e in edits}


def paid_steps(steps: dict, base: dict, order: str, grid: str) -> list[tuple[str, int]]:
    """What this run would pay for, in recording order: Hair Transfer of a transfer-first sample runs on the base render."""
    costs = {"hair_transfer": UNITS["hair-transfer"], "mu_transfer": UNITS["mu-transfer"], "even_out": VTO}
    first = ("hair_transfer", "mu_transfer", "even_out") if order == "hair_first" else ("mu_transfer",)
    paid = [(k, costs[k]) for k in first if k not in steps]
    renders = [(k, VTO) for k, recipe in wanted_renders(base, grid).items() if (steps.get(k) or {}).get("recipe") != recipe]
    if order == "transfer_first" and (steps.get("hair_transfer") or {}).get("label") != hair_label(base):
        at = 1 if renders[:1] == [("render:base", VTO)] else 0
        renders.insert(at, ("hair_transfer", costs["hair_transfer"]))
    return paid + renders


def skin_of(sd: Path, order: str, steps: dict) -> str:
    """Her forehead on the photo the renders run on: the Hair Transfer of a hair-first sample (s0 #dfa588), else
    bride.jpg. Read from the sample itself, so a --dry and a real run plan the same recipe."""
    bare = steps["hair_transfer"]["image"] if order == "hair_first" and "hair_transfer" in steps else "bride.jpg"
    return pipeline.skin_hex_of(sd, bare, pipeline.face_of(sd, bare))


def drop_stale_renders(recorder: Recorder, wanted: dict[str, dict]) -> None:
    steps = recorder.manifest["steps"]
    for key in [k for k in steps if k.startswith("render:") and steps[k].get("recipe") != wanted.get(k)]:
        step = steps.pop(key)
        (recorder.dir / step["image"]).unlink(missing_ok=True)
        (recorder.dir / "fixtures" / (Path(step["image"]).stem + ".json")).unlink(missing_ok=True)
    recorder.save()


def dry_run(sd: Path, pins: dict | None, steps: dict, order: str, grid: str, max_units: int) -> int:
    if not pins:
        print("no recipe_pins in sample.json: the recipe comes from the photo, nothing to plan", file=sys.stderr)
        return 2
    base = rcp.base_recipe(None, pins["group"], skin_of(sd, order, steps), pins["look"], pins.get("shades"))
    paid = paid_steps(steps, base, order, grid)
    print(f"{sd.name}: order {order}, group {base['group']}, look {base['look']}, skin {base['skin_hex']}")
    for key, units in paid:
        print(f"  {key}  {units}")
    total = sum(u for _, u in paid)
    print(f"renders {sum(k.startswith('render:') for k, _ in paid)}, units {total}")
    if total > max_units:
        print(f"--max-units {max_units} stops it at {max_units} of {total} units")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample_dir", type=Path)
    ap.add_argument("--grid", choices=["palette", "none"], default="palette")
    ap.add_argument("--order", choices=["transfer_first", "hair_first"], default="transfer_first",
                    help="for a new sample; hair_first: Hair Transfer on the selfie first, Makeup Transfer on that, "
                         "plus the even-out step")
    ap.add_argument("--max-units", type=int, default=25)
    ap.add_argument("--dry", action="store_true", help="print the paid steps and their number; no key, no calls")
    args = ap.parse_args()
    sd: Path = args.sample_dir
    meta = json.loads((sd / "sample.json").read_text()) if (sd / "sample.json").exists() else {}
    pins = meta.get("recipe_pins")
    manifest = json.loads((sd / "manifest.json").read_text()) if (sd / "manifest.json").exists() else {}
    order = manifest.get("order") or (args.order if not manifest else "transfer_first")  # s2, s3 predate the field
    if args.dry:
        return dry_run(sd, pins, manifest.get("steps", {}), order, args.grid, args.max_units)
    if pins:
        pins = {**pins, "skin_hex": skin_of(sd, order, manifest.get("steps", {}))}
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
    engine = GridEngine(client, recorder, args.max_units, ledger=ledger)
    ctx = SessionCtx(jpegs["bride"], jpegs["inspiration"])
    work = ROOT / "data" / "record" / sd.name
    credit_before = client.credit()
    print(f"credit before: {credit_before}")
    finished = True
    state = None
    try:
        state = pipeline.build_look(engine, ctx, work, recorder=recorder, order=order, pins=pins)
        base = state["recipe_base"]
        wanted = wanted_renders(base, args.grid)
        drop_stale_renders(recorder, wanted)
        steps = recorder.manifest["steps"]
        base_state = copy.deepcopy(state)
        for edits in rcp.record_grid(base) if args.grid == "palette" else []:
            step = f"render:{rcp.edit_key(edits)}"
            if (steps.get(step) or {}).get("recipe") != wanted[step]:
                pipeline.rerender(engine, ctx, work, state, edits)
        state = base_state
    except BudgetReached as e:
        print(f"stop: --max-units {args.max_units} reached before {e}")
        finished = False
    credit_after = client.credit()
    if finished:
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
    print(f"credit after: {credit_after} (spent {credit_before - credit_after}, this run {engine.spent} units)")
    if not finished:
        return 4
    print(json.dumps({"gaps": state["gaps"], "skin_control_de": state["map"]["skin_control_de"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
