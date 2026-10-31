"""Face landmarks (MediaPipe Face Landmarker, Google, Apache-2.0) and makeup-zone polygons.

Indices refer to the 478-point MediaPipe face mesh topology. "r_" = the person's right side
(image left on a non-mirrored photo), "l_" = the person's left side.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_landmarker.task"

# Upper eyelid, outer corner -> inner corner.
R_UPPER_LID = [33, 246, 161, 160, 159, 158, 157, 173, 133]
L_UPPER_LID = [263, 466, 388, 387, 386, 385, 384, 398, 362]
R_LOWER_LID = [33, 7, 163, 144, 145, 153, 154, 155, 133]
L_LOWER_LID = [263, 249, 390, 373, 374, 380, 381, 382, 362]
# Lower edge of the eyebrow, outer -> inner.
R_BROW_LOWER = [46, 53, 52, 65, 55]
L_BROW_LOWER = [276, 283, 282, 295, 285]
LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LIPS_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
R_CHEEK = [117, 118, 101, 36, 205, 187, 123]
L_CHEEK = [346, 347, 330, 266, 425, 411, 352]
FOREHEAD = [109, 10, 338, 337, 336, 9, 107, 108]
R_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
L_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
NOSE = [168, 6, 197, 195, 5, 4, 1, 19, 94, 2, 98, 327, 129, 358, 64, 294, 48, 278, 219, 439, 115, 344,
        220, 440, 45, 275]
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

ZONE_NAMES = ("eyes", "cheeks", "lips", "skin")
ZONE_LABELS = {"eyes": "Eyelids", "cheeks": "Cheeks", "lips": "Lips", "skin": "Skin (control)",
               "nose": "Nose & contour", "brows": "Brows"}


@dataclass(frozen=True)
class FaceGeometry:
    """Landmarks in pixel coordinates plus a rough head pose."""

    points: NDArray[np.float64]  # (478, 2) x, y in pixels
    width: int
    height: int
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    face_count: int

    @property
    def interocular_px(self) -> float:
        return float(np.linalg.norm(self.points[33] - self.points[263]))

    @property
    def face_box(self) -> tuple[float, float, float, float]:
        xs, ys = self.points[:, 0], self.points[:, 1]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


_lock = threading.Lock()


@cache
def _landmarker():
    from mediapipe.tasks.python import BaseOptions, vision

    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=2,
        output_facial_transformation_matrixes=True,
    )
    return vision.FaceLandmarker.create_from_options(opts)


def _pose_from_matrix(m: NDArray[np.float64]) -> tuple[float, float, float]:
    r = np.asarray(m, dtype=np.float64)[:3, :3]
    sy = math.hypot(r[0, 0], r[1, 0])
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    yaw = math.degrees(math.atan2(-r[2, 0], sy))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


def detect(rgb: NDArray[np.uint8]) -> FaceGeometry | None:
    """Run the landmarker on an RGB uint8 image. Returns the largest face or None."""
    import mediapipe as mp

    h, w = rgb.shape[:2]
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    with _lock:
        res = _landmarker().detect(image)
    if not res.face_landmarks:
        return None
    faces = []
    for i, lms in enumerate(res.face_landmarks):
        pts = np.array([[p.x * w, p.y * h] for p in lms], dtype=np.float64)
        area = float(np.ptp(pts[:, 0]) * np.ptp(pts[:, 1]))
        faces.append((area, i, pts))
    faces.sort(key=lambda t: t[0], reverse=True)
    _, idx, pts = faces[0]
    yaw = pitch = roll = 0.0
    if res.facial_transformation_matrixes:
        yaw, pitch, roll = _pose_from_matrix(res.facial_transformation_matrixes[idx])
    return FaceGeometry(pts, w, h, yaw, pitch, roll, len(res.face_landmarks))


def _resample(poly: NDArray[np.float64], n: int) -> NDArray[np.float64]:
    seg = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    t = np.concatenate([[0], np.cumsum(seg)])
    t /= t[-1] if t[-1] > 0 else 1
    s = np.linspace(0, 1, n)
    return np.stack([np.interp(s, t, poly[:, 0]), np.interp(s, t, poly[:, 1])], axis=1)


def _eyelid_polygon(pts: NDArray, lid: list[int], brow: list[int], reach: float = 0.7) -> NDArray:
    """Area between the upper lid line and `reach` of the way up to the lower brow edge."""
    lid_line = _resample(pts[lid], 24)
    brow_line = _resample(pts[brow], 24)
    # lid runs outer->inner, brow runs outer->inner too: pair point-wise.
    top = lid_line + reach * (brow_line - lid_line)
    return np.concatenate([lid_line, top[::-1]])


def _hull(points: NDArray) -> NDArray:
    import cv2

    return cv2.convexHull(points.astype(np.float32)).reshape(-1, 2).astype(np.float64)


def _eye_core(p: NDArray, upper: list[int], lower: list[int], brow: list[int], iod: float) -> list[NDArray]:
    lid_area = _eyelid_polygon(p, upper, brow, reach=0.85)
    opening = np.concatenate([p[upper], p[lower][::-1]])
    lower_line = _resample(p[lower], 16)
    band = np.concatenate([lower_line, (lower_line + [0.0, 0.10 * iod])[::-1]])
    return [lid_area, opening, band]


def core_polygons(face: FaceGeometry) -> dict[str, list[NDArray[np.float64]]]:
    """Seed regions per feature. Makeup zones = changed pixels assigned to their nearest seed."""
    p, iod = face.points, face.interocular_px
    return {
        "eyes": _eye_core(p, R_UPPER_LID, R_LOWER_LID, R_BROW_LOWER, iod)
        + _eye_core(p, L_UPPER_LID, L_LOWER_LID, L_BROW_LOWER, iod),
        "cheeks": [p[R_CHEEK], p[L_CHEEK]],
        "lips": [p[LIPS_OUTER]],
        "skin": [p[FOREHEAD]],
        "brows": [_hull(p[R_BROW]), _hull(p[L_BROW])],
        "nose": [_hull(p[NOSE])],
    }


def zone_polygons(face: FaceGeometry) -> dict[str, list[NDArray[np.float64]]]:
    """Display outlines of the core regions for the four reported zones."""
    cores = core_polygons(face)
    return {k: cores[k] for k in ZONE_NAMES}


def _fill(polys: list[NDArray], w: int, h: int) -> NDArray[np.bool_]:
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    for poly in polys:
        d.polygon([tuple(map(float, xy)) for xy in poly], fill=255)
    return np.asarray(img) > 0


def face_mask(face: FaceGeometry) -> NDArray[np.bool_]:
    return _fill([face.points[FACE_OVAL]], face.width, face.height)


def zone_cells(face: FaceGeometry, cutoff_iod: float = 0.45) -> dict[str, NDArray[np.bool_]]:
    """Partition the face into cells: each pixel goes to its nearest feature core (Voronoi on
    distance transforms), up to `cutoff_iod` x inter-ocular distance. Keys: eyes, cheeks, lips,
    skin, brows, nose; pixels further than the cutoff from every core belong to no cell."""
    import cv2

    w, h = face.width, face.height
    cores = core_polygons(face)
    names = list(cores)
    dists = []
    for name in names:
        core = _fill(cores[name], w, h)
        if name == "lips":
            core &= ~_fill([face.points[LIPS_INNER]], w, h)
        inv = np.where(core, 0, 255).astype(np.uint8)
        dists.append(cv2.distanceTransform(inv, cv2.DIST_L2, 3))
    stack = np.stack(dists)
    nearest = stack.argmin(axis=0)
    within = stack.min(axis=0) <= cutoff_iod * face.interocular_px
    inside_face = face_mask(face)
    mouth = _fill([face.points[LIPS_INNER]], w, h)
    eyes_open = _fill([np.concatenate([face.points[R_UPPER_LID], face.points[R_LOWER_LID][::-1]]),
                       np.concatenate([face.points[L_UPPER_LID], face.points[L_LOWER_LID][::-1]])], w, h)
    valid = within & inside_face & ~mouth & ~eyes_open
    return {name: (nearest == i) & valid for i, name in enumerate(names)}
