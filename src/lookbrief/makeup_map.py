"""The makeup map: what the artist will add, zone by zone.

AI Makeup Transfer returns only a picture (no makeup parameters), so the brief is measured from
pixels: (bride wearing the inspiration look) - (bare selfie), in CIE Lab, split into zones by face
landmarks. The same zone cells are reused to compare a Makeup VTO re-render with the transfer
(`compare`), which gives the honest "transfer vs re-render" metric shown in the app and README.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from .color import delta_e76, delta_e2000, lab_to_hex, srgb_to_lab
from .landmarks import ZONE_LABELS, FaceGeometry, face_mask, zone_cells

CHANGE_THRESHOLD = 6.0  # dE76 above which a pixel counts as "makeup added" (visible change)
MAKEUP_ZONES = ("eyes", "cheeks", "lips")
REPORTED_ZONES = ("eyes", "cheeks", "lips", "nose", "skin")
EXTRA_LABELS = {"nose": "Nose & contour", "brows": "Brows"}


@dataclass
class ZoneStat:
    zone: str
    label: str
    cell_px: int
    changed_px: int
    coverage: float  # changed / cell, 0..1
    strength_de: float  # median dE76 over changed pixels (how strong the colour is)
    color_after: str  # median colour of the look over changed pixels (what the eye sees)
    color_before: str  # median bare-skin colour under the same pixels
    delta_e2000: float  # CIEDE2000 between color_before and color_after


@dataclass
class MakeupMap:
    width: int
    height: int
    changed_share_of_face: float
    explained_share: float  # share of changed face pixels that fall in eyes/cheeks/lips
    skin_control_de: float  # median dE76 on the forehead control cell (should be ~0)
    zones: dict[str, ZoneStat] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["zones"] = {k: asdict(v) for k, v in self.zones.items()}
        return d

    @staticmethod
    def from_dict(d: dict) -> MakeupMap:
        zones = {k: ZoneStat(**v) for k, v in d["zones"].items()}
        return MakeupMap(d["width"], d["height"], d["changed_share_of_face"], d["explained_share"],
                         d["skin_control_de"], zones)


def to_rgb_array(img: Image.Image, size: tuple[int, int] | None = None) -> NDArray[np.uint8]:
    img = img.convert("RGB")
    if size is not None and img.size != size:
        # Makeup VTO can return 770x1022 for a 769x1024 input: bring every output back to the input grid.
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.uint8)


def _lab(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    return srgb_to_lab(rgb.astype(np.float64) / 255.0)


def _median_lab(lab: NDArray[np.float64], mask: NDArray[np.bool_]) -> NDArray[np.float64]:
    return np.median(lab[mask], axis=0)


def change_map(bare: NDArray[np.uint8], look: NDArray[np.uint8]) -> NDArray[np.float64]:
    return delta_e76(_lab(bare), _lab(look))


def compute(bare: NDArray[np.uint8], look: NDArray[np.uint8], face: FaceGeometry) -> MakeupMap:
    if bare.shape != look.shape:
        raise ValueError(f"bare {bare.shape} and look {look.shape} must share one pixel grid")
    lab_b, lab_l = _lab(bare), _lab(look)
    de = delta_e76(lab_b, lab_l)
    changed = de > CHANGE_THRESHOLD
    cells = zone_cells(face)
    fmask = face_mask(face)
    changed_face = changed & fmask
    n_changed = int(changed_face.sum())
    zones: dict[str, ZoneStat] = {}
    for name in REPORTED_ZONES:
        cell = cells[name]
        sel = cell & changed
        n_cell, n_sel = int(cell.sum()), int(sel.sum())
        use = sel if n_sel >= 40 else cell  # too few changed pixels: describe the cell itself
        if int(use.sum()) == 0:
            continue
        before, after = _median_lab(lab_b, use), _median_lab(lab_l, use)
        zones[name] = ZoneStat(
            zone=name,
            label=ZONE_LABELS.get(name) or EXTRA_LABELS.get(name, name),
            cell_px=n_cell,
            changed_px=n_sel,
            coverage=round(n_sel / n_cell, 4) if n_cell else 0.0,
            strength_de=round(float(np.median(de[sel])) if n_sel else 0.0, 2),
            color_after=lab_to_hex(after),
            color_before=lab_to_hex(before),
            delta_e2000=round(float(delta_e2000(before, after)), 2),
        )
    in_makeup = sum(int((cells[z] & changed).sum()) for z in MAKEUP_ZONES)
    return MakeupMap(
        width=bare.shape[1],
        height=bare.shape[0],
        changed_share_of_face=round(n_changed / max(int(fmask.sum()), 1), 4),
        explained_share=round(in_makeup / n_changed, 4) if n_changed else 0.0,
        skin_control_de=round(float(np.median(de[cells["skin"]])), 2) if cells["skin"].any() else 0.0,
        zones=zones,
    )


@dataclass
class ZoneGap:
    zone: str
    label: str
    color_transfer: str
    color_render: str
    color_gap_de2000: float  # CIEDE2000 between median colours on the transfer's makeup pixels
    pixel_gap_de2000: float  # median per-pixel CIEDE2000 on the same pixels
    coverage_transfer: float
    coverage_render: float


def compare(bare: NDArray[np.uint8], transfer: NDArray[np.uint8], render: NDArray[np.uint8],
            face: FaceGeometry) -> dict:
    """Transfer vs Makeup VTO re-render, per zone, on the pixels the transfer changed."""
    lab_b, lab_t, lab_r = _lab(bare), _lab(transfer), _lab(render)
    ch_t = delta_e76(lab_b, lab_t) > CHANGE_THRESHOLD
    ch_r = delta_e76(lab_b, lab_r) > CHANGE_THRESHOLD
    cells = zone_cells(face)
    gaps: dict[str, dict] = {}
    for name in MAKEUP_ZONES:
        cell = cells[name]
        sel = cell & ch_t
        if int(sel.sum()) < 40 or int(cell.sum()) == 0:
            continue
        mt, mr = _median_lab(lab_t, sel), _median_lab(lab_r, sel)
        gaps[name] = asdict(ZoneGap(
            zone=name,
            label=ZONE_LABELS[name],
            color_transfer=lab_to_hex(mt),
            color_render=lab_to_hex(mr),
            color_gap_de2000=round(float(delta_e2000(mt, mr)), 2),
            pixel_gap_de2000=round(float(np.median(delta_e2000(lab_t[sel], lab_r[sel]))), 2),
            coverage_transfer=round(float(sel.sum() / cell.sum()), 4),
            coverage_render=round(float((cell & ch_r).sum() / cell.sum()), 4),
        ))
    skin = cells["skin"]
    skin_render_de = float(np.median(delta_e76(lab_b[skin], lab_r[skin]))) if skin.any() else 0.0
    return {"zones": gaps, "skin_control_render_de76": round(skin_render_de, 2)}


def heatmap(bare: NDArray[np.uint8], look: NDArray[np.uint8]) -> Image.Image:
    """Visual of the makeup layer: changed pixels coloured by strength over a dimmed grey selfie."""
    de = change_map(bare, look)
    changed = de > CHANGE_THRESHOLD
    grey = np.asarray(Image.fromarray(bare).convert("L"), dtype=np.float64)
    out = np.repeat((grey * 0.35)[..., None], 3, axis=2)
    t = np.clip(de / 25.0, 0, 1)
    warm = np.stack([255 * np.ones_like(t), 210 - 150 * t, 120 - 110 * t], axis=-1)
    out[changed] = warm[changed]
    return Image.fromarray(out.astype(np.uint8))
