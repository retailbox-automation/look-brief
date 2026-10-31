"""Photo check before any unit is spent: local face checks plus plain-language hints for every
documented YouCam error code (Makeup Transfer, Hair Transfer, Makeup VTO)."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from . import landmarks
from .color import srgb_to_lab

MAX_SIDE = 1024  # mu-transfer accepts long side <= 1024
MIN_SIDE = 320
MAX_PIXELS = 40_000_000  # refuse before decoding: a tiny PNG can claim 144 Mpx and exhaust memory
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class Hint:
    title: str
    fix: str


HINTS: dict[str, Hint] = {
    # local checks
    "not_an_image": Hint("We couldn't open this file", "Upload a JPG or PNG photo."),
    "too_small": Hint("This photo is too small", "Use a photo at least 320 px on the short side."),
    "too_large": Hint("This photo is too large", "Use a photo under 40 megapixels and 12 MB."),
    "no_face": Hint("We can't find a face", "Use a photo where the face is clearly visible, facing the camera."),
    "many_faces": Hint("There's more than one face", "Crop the photo so only one face is in it."),
    "face_too_small": Hint("The face is too small in the frame", "Crop closer so the face fills more of the photo."),
    "large_angle": Hint("The head is turned too far", "Pick a photo where the face looks straight at the camera."),
    "tilted": Hint("The head is tilted", "A straight, level photo gives a more accurate map."),
    "eyes_closed": Hint("The eyes look closed", "Eye makeup can only be read with open eyes."),
    "too_dark": Hint("The photo is very dark", "Daylight from a window works best; avoid a flash."),
    "too_bright": Hint("The photo is overexposed", "Move out of direct light so the skin keeps its detail."),
    # documented API errors (ai_makeup_transfer.yaml, ai_hairstyle.yaml, makeup_vto.yaml)
    "error_src_no_face": Hint("We can't find a face in your selfie", "Use a clear, front-facing selfie."),
    "error_ref_no_face": Hint("We can't find a face in the inspiration photo",
                              "Pick an inspiration photo where the face is clearly visible."),
    "error_src_face_too_small": Hint("Your face is too small in the selfie", "Crop closer to your face."),
    "error_ref_face_too_small": Hint("The face in the inspiration photo is too small", "Crop closer to the face."),
    "error_src_large_face_angle": Hint("Your head is turned in the selfie", "Look straight at the camera."),
    "error_ref_large_face_angle": Hint("The inspiration face is turned too far",
                                       "Pick a front-facing inspiration photo."),
    "error_src_eye_closed": Hint("Your eyes are closed in the selfie", "Take one with your eyes open."),
    "error_ref_eye_closed": Hint("The eyes are closed in the inspiration photo",
                                 "Pick one where the eye makeup is visible with open eyes."),
    "error_src_eye_occluded": Hint("Something covers your eyes", "Move hair or glasses away from your eyes."),
    "error_ref_eye_occluded": Hint("Hair or a hand covers the eyes in the inspiration photo",
                                   "Pick a photo with both eyes visible."),
    "error_src_lip_occluded": Hint("Something covers your lips", "Keep hands and hair away from your mouth."),
    "error_ref_lip_occluded": Hint("The lips are covered in the inspiration photo", "Pick one with visible lips."),
    "error_inappropriate_ref_case01": Hint("This inspiration photo can't be used",
                                           "Pick a different, everyday portrait-style photo."),
    "error_inappropriate_ref_case02": Hint("This inspiration photo can't be used",
                                           "Pick a different, everyday portrait-style photo."),
    "error_no_face": Hint("We can't find a face", "Use a clear, front-facing photo."),
    "error_large_face_angle": Hint("The head is turned too far", "Use a front-facing photo."),
    "error_face_angle_invalid": Hint("The head is turned too far", "Use a front-facing photo."),
    "error_face_position_invalid": Hint("The whole face needs to be in the frame", "Don't crop the chin or forehead."),
    "error_face_position_out_of_boundary": Hint("The face is too close or cut off", "Step back a little."),
    "error_face_position_too_small": Hint("The face is too small", "Move closer to the camera."),
    "error_below_min_image_size": Hint("This photo is too small", "Use a larger photo."),
    "error_exceed_max_image_size": Hint("This photo is too large", "We resize automatically; try again."),
    "error_no_shoulder": Hint("Hair preview needs shoulders in the photo", "Use a photo framed down to the shoulders."),
    "error_hair_too_short": Hint("Hair preview needs a bit more visible hair", "Use a photo where your hair shows."),
    "error_insufficient_landmarks": Hint("We can't read the face shape", "Use a sharper, front-facing photo."),
    "error_pose": Hint("We can't read the head pose", "Use a front-facing photo."),
    "error_face_pose": Hint("We can't read the head pose", "Use a front-facing photo."),
    "error_face_parsing": Hint("We can't read the face", "Use a sharper photo with even light."),
    "error_nsfw_content_detected": Hint("This photo was rejected by the safety filter", "Use a portrait photo."),
    "error_decode_image": Hint("We couldn't read this image", "Re-save it as JPG and try again."),
    "error_download_image": Hint("The service couldn't fetch the photo", "Try again in a minute."),
    "error_inference": Hint("The service had a hiccup", "Try again in a minute — no units were spent."),
    "error_upload": Hint("The service couldn't save the result", "Try again in a minute — no units were spent."),
}


def hint_for(code: str) -> Hint:
    return HINTS.get(code, Hint("Something went wrong with this photo", f"Try a different photo ({code})."))


@dataclass
class Issue:
    code: str
    severity: str  # "block" | "warn"
    title: str
    fix: str


@dataclass
class CheckResult:
    role: str
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    width: int = 0
    height: int = 0
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    face_width_share: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TooLarge(ValueError):
    pass


def normalize(content: bytes) -> Image.Image:
    """Decode, honour EXIF rotation, RGB, long side <= 1024."""
    raw = Image.open(io.BytesIO(content))
    w, h = raw.size
    if w * h > MAX_PIXELS:
        raise TooLarge(f"{w}x{h}")
    raw.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: decode at reduced scale when possible
    img: Image.Image = ImageOps.exif_transpose(raw).convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return img


def to_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _eye_open_ratio(p: np.ndarray, upper: list[int], lower: list[int]) -> float:
    width = float(np.linalg.norm(p[upper[0]] - p[upper[-1]]))
    gap = float(np.mean(np.linalg.norm(p[upper[2:-2]] - p[lower[2:-2]], axis=1)))
    return gap / width if width else 0.0


def check(content: bytes, role: str) -> tuple[CheckResult, Image.Image | None]:
    res = CheckResult(role=role, ok=True)

    def add(code: str, severity: str) -> None:
        h = hint_for(code)
        res.issues.append(Issue(code, severity, h.title, h.fix))
        if severity == "block":
            res.ok = False

    try:
        img = normalize(content)
    except (TooLarge, Image.DecompressionBombError, Image.DecompressionBombWarning):
        add("too_large", "block")
        return res, None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        add("not_an_image", "block")
        return res, None
    res.width, res.height = img.size
    if min(img.size) < MIN_SIDE:
        add("too_small", "block")
        return res, img
    rgb = np.asarray(img, dtype=np.uint8)
    face = landmarks.detect(rgb)
    if face is None:
        add("no_face", "block")
        return res, img
    if face.face_count > 1:
        add("many_faces", "block" if role == "inspiration" else "warn")
    x0, y0, x1, y1 = face.face_box
    res.face_width_share = round((x1 - x0) / img.size[0], 3)
    res.yaw_deg, res.pitch_deg, res.roll_deg = (round(face.yaw_deg, 1), round(face.pitch_deg, 1),
                                                round(face.roll_deg, 1))
    if res.face_width_share < 0.18:
        add("face_too_small", "block")
    if abs(face.yaw_deg) > 25 or abs(face.pitch_deg) > 25:
        add("large_angle", "block")
    elif abs(face.yaw_deg) > 15:
        add("large_angle", "warn")
    if abs(face.roll_deg) > 20:
        add("tilted", "warn")
    p = face.points
    eye_r = _eye_open_ratio(p, landmarks.R_UPPER_LID, landmarks.R_LOWER_LID)
    eye_l = _eye_open_ratio(p, landmarks.L_UPPER_LID, landmarks.L_LOWER_LID)
    if min(eye_r, eye_l) < 0.06:
        add("eyes_closed", "block")
    fmask = landmarks.face_mask(face)
    if fmask.any():
        light = float(np.median(srgb_to_lab(rgb[fmask].astype(np.float64) / 255.0)[:, 0]))
        if light < 25:
            add("too_dark", "warn")
        elif light > 92:
            add("too_bright", "warn")
    return res, img
