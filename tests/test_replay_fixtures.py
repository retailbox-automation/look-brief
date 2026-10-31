import hashlib
import json
import re

import pytest
from helpers import SAMPLE_IDS, SAMPLES

from lookbrief import recipe as rcp
from lookbrief import visibility
from lookbrief.engine import NotRecorded, ReplayEngine, SessionCtx

SIGNED = re.compile(r"X-Amz-|Signature=|Expires=")


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_manifest_complete_and_files_present(sid):
    sd = SAMPLES / sid
    mf = json.loads((sd / "manifest.json").read_text())
    steps = mf["steps"]
    assert {"mu_transfer", "hair_transfer", "render:base"} <= set(steps)
    if mf.get("order") == "hair_first":
        assert "even_out" in steps, "hair_first samples record the even-out step"
    offered = visibility.edit_visibility(sd)["offered"]  # softer is not offered on zones too light to soften
    for key in offered:
        assert f"render:{key}" in steps, f"missing recorded edit {key}"
    for key, st in steps.items():
        assert (sd / st["image"]).is_file()
        assert st["task_id"] and st["recorded_at"].endswith("Z") and st["mode"] == "live"
        if key.startswith("render:"):
            edits = [] if key == "render:base" else [p.split(":") for p in key.split(":", 1)[1].split("+")]
            assert st["recipe"] == rcp.apply_edits(steps["render:base"]["recipe"], edits), key


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_fixtures_are_sanitized(sid):
    for f in (SAMPLES / sid / "fixtures").glob("*.json"):
        text = f.read_text()
        assert not SIGNED.search(text), f"signed URL left in {f.name}"
        assert "_file_id" not in json.dumps(json.loads(text)["request_without_file_ids"])
        assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)


@pytest.mark.parametrize("sid", SAMPLE_IDS)
def test_sample_inputs_match_declared_hashes(sid):
    meta = json.loads((SAMPLES / sid / "sample.json").read_text())
    for name, info in meta["files"].items():
        assert hashlib.sha256((SAMPLES / sid / name).read_bytes()).hexdigest() == info["sha256"]


def test_replay_engine_serves_recordings_and_refuses_unknown():
    sd = SAMPLES / SAMPLE_IDS[0]
    eng = ReplayEngine(sd)
    ctx = SessionCtx(b"", b"")
    mu = eng.makeup_transfer(ctx)
    assert mu.meta.mode == "replay" and mu.meta.units == 0 and len(mu.image) > 1000
    base = eng.recorded_recipe([])
    assert eng.render(ctx, base, []).meta.step == "render:base"
    with pytest.raises(NotRecorded):
        eng.render(ctx, base, [["lips", "lighter"], ["eyes", "softer"]])
