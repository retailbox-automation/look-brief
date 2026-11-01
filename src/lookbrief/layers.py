"""Replay: zone choices stack, by compositing recorded single-zone renders on the server.

A sample records one change at a time, so a look with several changed zones has no render of its own. Each zone keeps
what its recorded render did to the look (T against R), laid over the look frame in one fixed order. Live is not here:
it sends the whole recipe in one real call. Checked against 18 real multi-zone renders: tests/test_layers.py,
docs/EDITS.md.

The maths takes numpy arrays and masks; `stack_of` picks the sources from the recorded keys. Both are pure.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from . import palettes
from . import recipe as rcp

type Linear = NDArray[np.floating[Any]]
type Mask = NDArray[np.floating[Any]]
type Pixels = NDArray[np.uint8]
type Box = tuple[int, int, int, int]  # y0, y1, x0, x1

METHOD = "lookbrief.zone-stack.v1"
ORDER = ("eyes", "brows", "cheeks", "highlight", "lips", "lip_line", "liner", "lashes")  # never the click order
FLOOR = 1e-3
RATIO_RANGE = (0.03, 12.0)
JPEG_QUALITY = 92
# zone -> (mask zones that move together, dilation px, blur sigma)
EYE_AREA = (("eyes", "liner", "lashes"), 26, 5)
BROW_AREA = (("brows",), 12, 4)
FACE_AREA = (("cheeks", "bronzer", "highlight"), 14, 8)
LIP_AREA = (("lips", "lip_line"), 12, 4)
AREAS = {"eyes": EYE_AREA, "liner": EYE_AREA, "lashes": EYE_AREA, "brows": BROW_AREA, "cheeks": FACE_AREA,
         "highlight": FACE_AREA, "lips": LIP_AREA, "lip_line": LIP_AREA}

# Lookup tables: a whole frame of pow() holds seven 9 MB temporaries at once, on a container that was OOM-killed.
_LEVELS = np.arange(256) / 255
_TO_LINEAR = np.where(_LEVELS <= 0.04045, _LEVELS / 12.92, ((_LEVELS + 0.055) / 1.055) ** 2.4).astype(np.float32)
_STEPS = np.arange(65536) / 65535
_SRGB = np.where(_STEPS <= 0.0031308, _STEPS * 12.92, 1.055 * _STEPS ** (1 / 2.4) - 0.055)
_TO_SRGB = (_SRGB * 255 + 0.5).astype(np.uint8)


def to_linear(rgb: Pixels) -> Linear:
    return _TO_LINEAR[rgb]


def to_pixels(linear: Linear) -> Pixels:
    index = np.clip(linear, 0, 1)
    index *= 65535
    index += 0.5
    return _TO_SRGB[index.astype(np.uint16)]


def linear_color(hex_color: str) -> Linear:
    return to_linear(np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8))


def ratio(c: Linear, r: Linear, t: Linear, m: Mask) -> Linear:
    """The zone changes the frame by the factor its render changed R. It can lighten: a style that goes away."""
    factor = np.clip(np.maximum(t, FLOOR) / np.maximum(r, FLOOR), *RATIO_RANGE)
    return c * (m[..., None] * factor + (1 - m[..., None]))


def _coverage(r: Linear, t: Linear, m: Mask, color: Linear) -> Mask:
    d = r - color
    return np.clip(((r - t) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-4), 0, 1) * m


def alpha(c: Linear, r: Linear, t: Linear, m: Mask, color: Linear) -> Linear:
    """The product as paint: its colour, as far as the render moved towards that colour. It only darkens."""
    a = _coverage(r, t, m, color)[..., None]
    return c * (1 - a) + color * a


def core(c: Linear, r: Linear, t: Linear, m: Mask, color: Linear) -> Linear:
    """Alpha, but the opaque core keeps the depth of the render: the recipe colour of the liner is browner than what
    the API paints on dark lids, and plain alpha turned the wing tip brown."""
    a = _coverage(r, t, m, color)
    out = c * (1 - a[..., None]) + color * a[..., None]
    k = np.clip((a - 0.45) / 0.3, 0, 1)[..., None]
    return out * (1 - k) + np.minimum(out, t) * k


PAINT: dict[str, Callable[..., Linear]] = {"liner": core, "lashes": alpha}  # how they land when they only darken


def paint(zone: str, c: Linear, r: Linear, t: Linear, m: Mask, color: Linear) -> Linear:
    return PAINT[zone](c, r, t, m, color)


def soft_mask(masks: dict[str, NDArray[np.bool_]], zone: str) -> tuple[Box, Mask]:
    """The soft mask of a zone on a crop of the frame. The crop holds the dilation and the tail of the blur (cv2 cuts
    a float blur at 4 sigma), so it equals the mask of the whole frame."""
    import cv2

    names, grow, blur = AREAS[zone]
    union = np.logical_or.reduce([masks[n] for n in names])
    ys, xs = np.nonzero(union)
    if not ys.size:
        raise ValueError(f"zone {zone} is not on this photo")
    pad = grow + 4 * blur + 1
    h, w = union.shape
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, h)
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, w)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    dilated = cv2.dilate(union[y0:y1, x0:x1].astype(np.uint8), kernel).astype(np.float32)
    return (y0, y1, x0, x1), np.asarray(cv2.GaussianBlur(dilated, (0, 0), blur), dtype=np.float32)


@dataclass(frozen=True)
class Plate:
    """One zone ready to land: its crops of the two renders and its mask."""

    zone: str
    blend: str
    box: Box
    mask: Mask
    target: Pixels
    reference: Pixels
    color: Linear | None = None


def compose(frame: Pixels, plates: Iterable[Plate]) -> Pixels:
    """The look frame with every plate laid over it, in the order given. `plates` may be a generator: only one zone's
    crops are held at a time, each decoded render is dropped before the next."""
    c = to_linear(frame)
    for p in plates:
        y0, y1, x0, x1 = p.box
        here, r, t = c[y0:y1, x0:x1], to_linear(p.reference), to_linear(p.target)
        if p.color is None:
            c[y0:y1, x0:x1] = ratio(here, r, t, p.mask)
        else:
            c[y0:y1, x0:x1] = paint(p.zone, here, r, t, p.mask, p.color)
    return to_pixels(c)


def to_jpeg(pixels: Pixels) -> bytes:
    out = io.BytesIO()
    Image.fromarray(pixels).save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


@dataclass(frozen=True)
class Layer:
    zone: str
    target: str  # recorded render keys, without the "render:" of the manifest
    reference: str
    blend: str  # "ratio", or the name of a PAINT function


@dataclass(frozen=True)
class Stack:
    frame: str
    layers: list[Layer]


def canonical(edits: list[list[str]]) -> list[list[str]]:
    """The edits in the order they land. Keeps the recipe from depending on the clicks too: a lip pulls the lip liner
    with it, so a lip liner she chose has to come after the lip."""
    rank = {z: i for i, z in enumerate((rcp.LOOK_ZONE, *ORDER))}
    return sorted(edits, key=lambda e: rank[e[0]])


def stack_of(base: dict, edits: list[list[str]], recorded: set[str]) -> Stack | None:
    """Which recorded renders an edit list is made of, or None if a zone has no source. `base`: the recipe the sample
    started from; `recorded`: the render keys of the sample."""
    ordered = canonical(edits)
    look = [e for e in ordered if e[0] == rcp.LOOK_ZONE]
    frame = rcp.edit_key(look)
    if frame not in recorded:
        return None
    prefix = f"{frame}+" if look else ""
    wide = [*look, *(e for e in ordered if e[0] in palettes.STEP_ZONES)]
    worn = rcp.apply_edits(base, wide)["zones"]  # a lip brings its own lip liner, and its render holds that one
    out = []
    for zone, op in ordered:
        if zone == rcp.LOOK_ZONE:
            continue
        if zone in palettes.STEP_ZONES:  # recorded on every look
            target, reference, blend = f"{prefix}{zone}:{op}", frame, "ratio"
        else:  # recorded on the base look only: T against R is the step between two styles
            own = op == rcp.SHADE_PREFIX + base["zones"][zone]["shade_id"]
            target = "base" if own else f"{zone}:{op}"
            single = f"{zone}:{rcp.SHADE_PREFIX}{worn[zone]['shade_id']}"
            reference = single if single in recorded else "base"
            adds = reference == "base" and zone in PAINT
            blend = PAINT[zone].__name__ if adds else "ratio"  # going back to a lighter style cannot be painted on
        if target not in recorded or reference not in recorded or target == reference:
            return None  # target == reference: the photo would stay while the zone says it changed
        out.append(Layer(zone, target, reference, blend))
    return Stack(frame, out)


def file_name(edits: list[list[str]]) -> str:
    """The same choices give the same file, whatever the click order; a list of nine zones would not fit a name."""
    key = rcp.edit_key(canonical(edits))
    return f"stack-{hashlib.sha256(key.encode()).hexdigest()[:16]}.jpg"


def caption(zone_renders: int) -> str:
    noun = "result" if zone_renders == 1 else "results"
    return f"Assembled from {zone_renders} recorded YouCam Makeup VTO {noun}, one per zone"


def record(stack: Stack, steps: dict) -> dict:
    """What a composed image is made of, for the page and the signed brief."""

    def task(key: str) -> str:
        return str(steps[f"render:{key}"]["task_id"])

    return {"method": METHOD, "caption": caption(len(stack.layers)), "zone_renders": len(stack.layers),
            "frame": {"render": stack.frame, "task_id": task(stack.frame)},
            "layers": [{"zone": x.zone, "blend": x.blend, "render": x.target, "task_id": task(x.target),
                        "reference": x.reference, "reference_task_id": task(x.reference)} for x in stack.layers]}
