"""Two engines behind one interface.

* LiveEngine — real YouCam calls (server-side key), optionally recording every result into a
  sample folder so the same run can be replayed later.
* ReplayEngine — serves recorded real YouCam results from samples/<id>/manifest.json. This is the
  default for judges (allowed by the organiser, Devpost forum thread 45693): no key, no units, and
  every result is labelled as recorded with its original task_id and timestamp.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .recipe import EVEN_OUT_LABEL, edit_key, even_out_effects, vto_body
from .youcam import YouCamClient, redact


class NotRecorded(Exception):
    """Replay has no recording for this request."""


@dataclass
class StepMeta:
    step: str
    mode: str  # "live" | "replay"
    task_id: str
    seconds: float
    units: int
    recorded_at: str
    label: str = ""


@dataclass
class StepResult:
    image: bytes
    meta: StepMeta


@dataclass
class SessionCtx:
    bride_jpeg: bytes
    inspiration_jpeg: bytes
    ids: dict = field(default_factory=dict)  # cached file ids / urls (live only)


Ledger = Callable[[str, int, str, bool], None]


def image_ext(content: bytes) -> str:
    """YouCam returns JPEG for transfers and PNG for Makeup VTO: keep the real format."""
    return ".png" if content[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LiveEngine:
    mode = "live"

    def __init__(self, client: YouCamClient, ledger: Ledger | None = None, recorder: Recorder | None = None):
        self.client = client
        self.ledger = ledger or (lambda op, units, task_id, ok: None)
        self.recorder = recorder

    def _file_id(self, ctx: SessionCtx, key: str, content: bytes, name: str) -> str:
        if key not in ctx.ids:
            ctx.ids[key] = self.client.upload(content, name)
        return str(ctx.ids[key])

    def _run(self, step: str, task: str, body: dict, label: str = "", recipe: dict | None = None) -> StepResult:
        try:
            res = self.client.run_task(task, body)
        except Exception:
            self.ledger(task, 0, "", False)
            raise
        self.ledger(task, res.units, res.task_id, True)
        img = self.client.download(res.result_url)
        meta = StepMeta(step, "live", res.task_id, res.seconds, res.units, _now(), label)
        if self.recorder:
            self.recorder.add(step, img, meta, body, res.raw, recipe)
        return StepResult(img, meta)

    def _source(self, ctx: SessionCtx, on: str) -> str:
        if on == "base":  # her face with the inspiration hair (hair_first order)
            return self._file_id(ctx, "base", ctx.ids["base_jpeg"], "base.jpg")
        return self._file_id(ctx, "bride", ctx.bride_jpeg, "bride.jpg")

    def makeup_transfer(self, ctx: SessionCtx, on: str = "bride") -> StepResult:
        src = self._source(ctx, on)
        ref = self._file_id(ctx, "inspiration", ctx.inspiration_jpeg, "inspiration.jpg")
        out = self._run("mu_transfer", "mu-transfer", {"src_file_id": src, "ref_file_id": ref})
        ctx.ids["mu_jpeg"] = out.image
        return out

    def hair_transfer(self, ctx: SessionCtx, on: str = "look") -> StepResult:
        """on="look": hair on the makeup-transfer result (transfer_first); on="selfie": hair on the bare selfie,
        which becomes the base for the makeup transfer (hair_first)."""
        ref = self._file_id(ctx, "inspiration", ctx.inspiration_jpeg, "inspiration.jpg")
        if on == "selfie":
            src = self._source(ctx, "bride")
        else:
            mu = ctx.ids.get("mu_jpeg")
            if mu is None:
                raise RuntimeError("hair transfer runs on the makeup-transfer result; run that first")
            src = self._file_id(ctx, "mu_result", mu, "look.jpg")
        out = self._run("hair_transfer", "hair-transfer", {"src_file_id": src, "ref_file_id": ref, "hair_color": "ref"})
        if on == "selfie":
            ctx.ids["base_jpeg"] = out.image
        return out

    def even_out(self, ctx: SessionCtx, skin_hex: str, coverage: int = 30) -> StepResult:
        mu = ctx.ids.get("mu_jpeg")
        if mu is None:
            raise RuntimeError("even-out runs on the makeup-transfer result; run that first")
        src = self._file_id(ctx, "mu_result", mu, "look.jpg")
        body = {"src_file_id": src, "version": "1.0", "effects": even_out_effects(skin_hex, coverage)}
        return self._run("even_out", "makeup-vto", body, label=EVEN_OUT_LABEL)

    def render(self, ctx: SessionCtx, recipe: dict, edits: list[list[str]], on: str = "bride") -> StepResult:
        src = self._source(ctx, on)
        body = {"src_file_id": src, **vto_body(recipe)}
        return self._run(f"render:{edit_key(edits)}", "makeup-vto", body, label=edit_key(edits), recipe=recipe)


class ReplayEngine:
    mode = "replay"

    def __init__(self, sample_dir: Path):
        self.dir = sample_dir
        self.manifest = json.loads((sample_dir / "manifest.json").read_text())

    def _step(self, key: str) -> StepResult:
        rec = self.manifest["steps"].get(key)
        if rec is None:
            raise NotRecorded(key)
        meta = StepMeta(key, "replay", rec["task_id"], rec["seconds"], 0, rec["recorded_at"], rec.get("label", ""))
        return StepResult((self.dir / rec["image"]).read_bytes(), meta)

    def makeup_transfer(self, ctx: SessionCtx, on: str = "bride") -> StepResult:
        return self._step("mu_transfer")

    def hair_transfer(self, ctx: SessionCtx, on: str = "look") -> StepResult:
        return self._step("hair_transfer")

    def even_out(self, ctx: SessionCtx, skin_hex: str, coverage: int = 30) -> StepResult:
        return self._step("even_out")

    def render(self, ctx: SessionCtx, recipe: dict, edits: list[list[str]], on: str = "bride") -> StepResult:
        return self._step(f"render:{edit_key(edits)}")

    def order(self) -> str:
        return str(self.manifest.get("order", "transfer_first"))

    def recorded_map(self) -> dict | None:
        return self.manifest.get("map")

    def recorded_recipe(self, edits: list[list[str]]) -> dict | None:
        rec = self.manifest["steps"].get(f"render:{edit_key(edits)}")
        return rec.get("recipe") if rec else None

    def recorded_render_keys(self) -> list[str]:
        return [k.split(":", 1)[1] for k in self.manifest["steps"] if k.startswith("render:")]


class Recorder:
    """Writes live results into a sample folder: images + manifest + sanitized API fixtures."""

    def __init__(self, sample_dir: Path):
        self.dir = sample_dir
        (sample_dir / "results").mkdir(parents=True, exist_ok=True)
        (sample_dir / "fixtures").mkdir(parents=True, exist_ok=True)
        mf = sample_dir / "manifest.json"
        self.manifest = json.loads(mf.read_text()) if mf.exists() else {"steps": {}}
        self.manifest.setdefault("steps", {})

    def set_map(self, map_dict: dict) -> None:
        self.manifest["map"] = map_dict
        self.save()

    def set_order(self, order: str) -> None:
        self.manifest["order"] = order
        self.save()

    def add(self, step: str, image: bytes, meta: StepMeta, request: dict, response: dict,
            recipe: dict | None = None) -> None:
        safe = step.replace(":", "__").replace("+", "_")
        img_rel = f"results/{safe}{image_ext(image)}"
        (self.dir / img_rel).write_bytes(image)
        req = {k: v for k, v in request.items() if not k.endswith("_file_id")}
        fixture = {
            "step": step,
            "task_id": meta.task_id,
            "recorded_at": meta.recorded_at,
            "seconds": meta.seconds,
            "units": meta.units,
            "request_without_file_ids": req,
            "response": redact(response),
        }
        (self.dir / "fixtures" / f"{safe}.json").write_text(json.dumps(fixture, indent=1, ensure_ascii=False))
        entry = {**asdict(meta), "image": img_rel, "mode": "live"}
        if recipe is not None:
            entry["recipe"] = recipe
        self.manifest["steps"][step] = entry
        self.save()

    def save(self) -> None:
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=1, ensure_ascii=False))
