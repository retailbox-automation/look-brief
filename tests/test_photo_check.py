import io
import json
from pathlib import Path

import numpy as np
import pytest
from helpers import SAMPLE_IDS, SAMPLES
from PIL import Image

from lookbrief import photo_check

DOCS = json.loads((Path(__file__).parent / "fixtures" / "youcam_docs_snapshot.json").read_text())


def _jpeg(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_sample_photos_pass(sid):
    for role, name in (("bride", "bride.jpg"), ("inspiration", "inspiration.jpg")):
        res, img = photo_check.check((SAMPLES / sid / name).read_bytes(), role)
        assert res.ok, res.issues
        assert img is not None and max(img.size) <= photo_check.MAX_SIDE


def test_not_an_image():
    res, img = photo_check.check(b"%PDF-1.4 not a photo", "bride")
    assert not res.ok and res.issues[0].code == "not_an_image" and img is None


def test_too_small_blocks_before_any_api_call():
    res, _ = photo_check.check(_jpeg(np.full((200, 150, 3), 128, np.uint8)), "bride")
    assert not res.ok and res.issues[0].code == "too_small"


def test_no_face_blocks():
    rng = np.random.default_rng(3)
    res, _ = photo_check.check(_jpeg(rng.integers(0, 255, (800, 600, 3), dtype=np.uint8)), "inspiration")
    assert not res.ok and res.issues[0].code == "no_face"


def test_large_photo_is_resized_to_api_limit():
    big = Image.open(SAMPLES / SAMPLE_IDS[0] / "bride.jpg").resize((1536, 2048))
    buf = io.BytesIO()
    big.save(buf, format="JPEG")
    res, img = photo_check.check(buf.getvalue(), "bride")
    assert res.ok and img is not None and max(img.size) == 1024


def test_every_documented_error_code_has_a_plain_hint():
    missing = [c for c in DOCS["documented_error_codes"] if c not in photo_check.HINTS]
    assert not missing, missing
    for code in DOCS["documented_error_codes"]:
        h = photo_check.hint_for(code)
        assert h.title and h.fix and "error_" not in h.title
