"""Engines behind one interface.

* LiveEngine — real YouCam calls (server-side key), optionally recording every result into a
  sample folder so the same run can be replayed later.
* ReplayEngine — serves recorded real YouCam results from samples/<id>/manifest.json. This is the
  default for judges (allowed by the organiser, Devpost forum thread 45693): no key, no units, and
  every result is labelled as recorded with its original task_id and timestamp.
* GridEngine — a LiveEngine for recording a sample's grid: what the sample already holds is served
  from it for free, and spending stops at a ceiling.
"""

from __future__ import annotations

import io
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from . import layers, visibility
from .landmarks import FaceGeometry
from .makeup_map import to_rgb_array
from .photo_check import to_jpeg
from .recipe import EVEN_OUT_LABEL, edit_key, even_out_effects, recipe_sha256, vto_body
from .youcam import UNITS, YouCamClient, redact


class NotRecorded(Exception):
    """Replay has no recording for this request."""


class BudgetReached(Exception):
    """The next paid call would pass the recording ceiling."""


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


def hair_label(recipe: dict) -> str:
    """Marks a Hair Transfer with the base render it ran on: a new base means the recorded hair shows old makeup."""
    return f"on base render {recipe_sha256(recipe)[:12]}"


def keep_base_render(ctx: SessionCtx, image: bytes, recipe: dict) -> None:
    """Makeup VTO returns a PNG; uploads are declared JPEG."""
    ctx.ids["render_jpeg"] = to_jpeg(Image.open(io.BytesIO(image)).convert("RGB"))
    ctx.ids["render_label"] = hair_label(recipe)


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

    def hair_transfer(self, ctx: SessionCtx, on: str = "render") -> StepResult:
        """on="render": hair on the base render of the recipe, so the preview wears the new look (transfer_first);
        on="selfie": hair on the bare selfie, which becomes the base for the makeup transfer (hair_first)."""
        ref = self._file_id(ctx, "inspiration", ctx.inspiration_jpeg, "inspiration.jpg")
        label = ""
        if on == "selfie":
            src = self._source(ctx, "bride")
        else:
            rendered = ctx.ids.get("render_jpeg")
            if rendered is None:
                raise RuntimeError("hair transfer runs on the base render; render it first")
            src = self._file_id(ctx, "render_result", rendered, "render.jpg")
            label = ctx.ids["render_label"]
        body = {"src_file_id": src, "ref_file_id": ref, "hair_color": "ref"}
        out = self._run("hair_transfer", "hair-transfer", body, label=label)
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
        out = self._run(f"render:{edit_key(edits)}", "makeup-vto", body, label=edit_key(edits), recipe=recipe)
        if not edits:
            keep_base_render(ctx, out.image, recipe)
        return out


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

    def hair_transfer(self, ctx: SessionCtx, on: str = "render") -> StepResult:
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

    def quiet_edits(self) -> list[str]:
        """Buttons whose step does not show on this sample's photo (scripts/edit_visibility_report.py --write)."""
        return list(self.manifest.get("quiet_edits", []))

    def recorded_render_keys(self) -> list[str]:
        return [k.split(":", 1)[1] for k in self.manifest["steps"] if k.startswith("render:")]

    def stack_of(self, base: dict, edits: list[list[str]]) -> layers.Stack | None:
        return layers.stack_of(base, edits, set(self.recorded_render_keys()))

    def composition(self, stack: layers.Stack) -> dict:
        return layers.record(stack, self.manifest["steps"])

    def _pixels(self, key: str, size: tuple[int, int]) -> layers.Pixels:
        return to_rgb_array(Image.open(self.dir / self.manifest["steps"][f"render:{key}"]["image"]), size=size)

    def compose(self, stack: layers.Stack, recipe: dict, face: FaceGeometry) -> layers.Pixels:
        """One image for a stack of recorded zone renders. Keep it under the semaphore of image work."""
        size = (face.width, face.height)
        masks = visibility.zone_masks(face)

        def plates() -> Iterator[layers.Plate]:
            for x in stack.layers:
                box, mask = layers.soft_mask(masks, x.zone)
                y0, y1, x0, x1 = box
                color = None if x.blend == "ratio" else layers.linear_color(recipe["zones"][x.zone]["palette"][0])
                yield layers.Plate(x.zone, x.blend, box, mask, self._pixels(x.target, size)[y0:y1, x0:x1].copy(),
                                   self._pixels(x.reference, size)[y0:y1, x0:x1].copy(), color)

        return layers.compose(self._pixels(stack.frame, size), plates())


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


class GridEngine(LiveEngine):
    """Live calls only for what the sample does not hold yet: Makeup Transfer, a hair-first Hair Transfer and the
    even-out are never paid twice, a render with the same recipe is kept, and a stopped run resumes where it stopped.
    The manifest is saved after every paid step, so `max_units` can stop it anywhere."""

    def __init__(self, client: YouCamClient, recorder: Recorder, max_units: int, ledger: Ledger | None = None):
        super().__init__(client, ledger=ledger, recorder=recorder)
        self.steps = recorder.manifest["steps"]
        self.dir = recorder.dir
        self.max_units = max_units
        self.spent = 0

    def _run(self, step: str, task: str, body: dict, label: str = "", recipe: dict | None = None) -> StepResult:
        if self.spent + UNITS[task] > self.max_units:
            raise BudgetReached(step)
        out = super()._run(step, task, body, label, recipe)
        self.spent += out.meta.units
        return out

    def _recorded(self, key: str) -> StepResult | None:
        rec = self.steps.get(key)
        if rec is None:
            return None
        meta = StepMeta(key, "live", rec["task_id"], rec["seconds"], 0, rec["recorded_at"], rec.get("label", ""))
        return StepResult((self.dir / rec["image"]).read_bytes(), meta)

    def makeup_transfer(self, ctx: SessionCtx, on: str = "bride") -> StepResult:
        got = self._recorded("mu_transfer")
        if got is None:
            return super().makeup_transfer(ctx, on)
        ctx.ids["mu_jpeg"] = got.image
        return got

    def hair_transfer(self, ctx: SessionCtx, on: str = "render") -> StepResult:
        got = self._recorded("hair_transfer")
        if got is None or (on == "render" and got.meta.label != ctx.ids.get("render_label")):
            return super().hair_transfer(ctx, on)
        if on == "selfie":
            ctx.ids["base_jpeg"] = got.image
        return got

    def even_out(self, ctx: SessionCtx, skin_hex: str, coverage: int = 30) -> StepResult:
        return self._recorded("even_out") or super().even_out(ctx, skin_hex, coverage)

    def render(self, ctx: SessionCtx, recipe: dict, edits: list[list[str]], on: str = "bride") -> StepResult:
        key = f"render:{edit_key(edits)}"
        got = self._recorded(key)
        if got is None or self.steps[key].get("recipe") != recipe:
            return super().render(ctx, recipe, edits, on)
        if not edits:
            keep_base_render(ctx, got.image, recipe)
        return got
