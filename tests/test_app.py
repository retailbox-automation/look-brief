import json

import pytest
from fastapi.testclient import TestClient
from helpers import SAMPLE_IDS, SAMPLES

from lookbrief import app as app_mod
from lookbrief import attest
from lookbrief.config import Settings
from lookbrief.youcam import UNITS, TaskResult

SID = SAMPLE_IDS[0]


def _settings(tmp_path, **kw) -> Settings:
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.samples_dir = SAMPLES
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    return TestClient(app_mod.create_app(_settings(tmp_path)))


def _replay_session(client) -> str:
    r = client.get(f"/try/{SID}", follow_redirects=False)
    assert r.status_code == 303
    sid = r.headers["location"].rsplit("/", 1)[1]
    st = client.get(f"/api/sessions/{sid}").json()
    assert st["status"] == "ready", st
    return sid


def test_health_index_and_live_off_without_key(client):
    assert client.get("/healthz").json()["samples"] == SAMPLE_IDS
    html = client.get("/").text
    assert f"/try/{SID}" in html and "recorded real YouCam API results" in html
    lim = client.get("/api/limits").json()
    assert lim["available"] is False and "no API key" in lim["reason"]


def test_replay_session_state(client):
    sid = _replay_session(client)
    st = client.get(f"/api/sessions/{sid}").json()
    assert st["mode"] == "replay" and st["units_spent"] == 0
    assert set(st["images"]) >= {"bride", "inspiration", "look", "hair", "layer", "render"}
    assert st["steps"]["mu_transfer"]["mode"] == "replay" and st["steps"]["mu_transfer"]["task_id"]
    assert set(st["gaps"]["zones"]) == {"eyes", "cheeks", "lips"}
    assert len(st["outlines"]["eyes"]) == 2 and len(st["outlines"]["cheeks"]) == 2 and len(st["outlines"]["lips"]) == 1
    assert all(0 <= c <= 1 for poly in st["outlines"]["lips"] for pt in poly for c in pt)
    assert all(o["available"] for o in st["edit_options"])
    for url in st["images"].values():
        assert client.get(url).status_code == 200


def test_replay_edits_undo_and_unrecorded_combo(client):
    sid = _replay_session(client)
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "softer"})
    assert r.status_code == 200 and r.json()["edits"] == [["cheeks", "softer"]]
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "lighter"})
    assert r.status_code == 409 and r.json()["error"] == "not_recorded"
    r = client.post(f"/api/sessions/{sid}/edits", json={"action": "undo"})
    assert r.json()["edits"] == []
    assert client.post(f"/api/sessions/{sid}/edits", json={"zone": "nose", "op": "softer"}).status_code == 400


def test_brief_review_agree_attest(client):
    sid = _replay_session(client)
    b = client.post(f"/api/sessions/{sid}/brief").json()
    bid = b["brief_id"]
    bride, artist = b["bride_url"].split("t=")[1], b["artist_url"].split("t=")[1]
    assert client.get(f"/b/{bid}?t=wrong").status_code == 404
    assert "no account needed" in client.get(b["artist_url"]).text
    assert (
        client.post(f"/api/briefs/{bid}/review", json={"t": bride, "zone": "eyes", "status": "do"}).status_code == 403
    )
    assert client.post(f"/api/briefs/{bid}/agree", json={"t": artist}).status_code == 409
    zones = client.get(f"/api/briefs/{bid}?t={artist}").json()["snapshot"]["review_zones"]
    assert "hair" in zones
    for z in zones:
        client.post(
            f"/api/briefs/{bid}/review", json={"t": artist, "zone": z, "status": "discuss" if z == "lips" else "do"}
        )
    assert client.post(f"/api/briefs/{bid}/agree", json={"t": artist}).status_code == 409, "open discussion blocks"
    client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": "lips", "status": "swap", "note": "cooler red"})
    assert client.post(f"/api/briefs/{bid}/agree", json={"t": artist}).json()["attestation"] is None
    v = client.post(f"/api/briefs/{bid}/agree", json={"t": bride}).json()
    att = v["attestation"]
    assert att and set(att["payload"]["agreed_at"]) == {"bride", "artist"}
    pub = client.get("/.well-known/lookbrief-attest.json").json()["public_key_b64"]
    assert attest.verify(att, pub)
    lips = next(z for z in att["payload"]["zones"] if z["zone"] == "lips")
    assert lips["status"] == "swap" and lips["note"] == "cooler red"
    assert client.get(f"/api/briefs/{bid}/attestation.json?t={bride}").json() == att
    assert "Server-attested agreement" in client.get(f"/card/{bid}?t={bride}").text
    assert (
        client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": "eyes", "status": "swap"}).status_code
        == 409
    )


def test_media_paths_are_locked_down(client):
    sid = _replay_session(client)
    assert client.get(f"/media/{sid}/..%2Flookbrief.db").status_code == 404
    assert client.get(f"/media/{sid}/lookbrief.db").status_code == 404
    assert client.get("/media/../../etc/passwd").status_code == 404
    assert client.get(f"/sample-media/{SID}/manifest.json").status_code == 404


# ---------------- Live mode with a fake YouCam client (no network) ----------------
class FakeYouCam:
    credit_value = 900

    def __init__(self, *a, **kw):
        self.mf = json.loads((SAMPLES / SID / "manifest.json").read_text())
        self.n = 0

    def credit(self):
        return self.credit_value

    def upload(self, content, name, content_type="image/jpeg"):
        self.n += 1
        return f"file-{self.n}"

    def run_task(self, name, body, version=None):
        step = {"mu-transfer": "mu_transfer", "hair-transfer": "hair_transfer", "makeup-vto": "render:base"}[name]
        return TaskResult(name, f"task-{name}", f"fake://{step}", 1.0, UNITS[name], {})

    def download(self, url):
        return (SAMPLES / SID / self.mf["steps"][url[len("fake://") :]]["image"]).read_bytes()


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "sk-fake")
    monkeypatch.setattr(app_mod, "YouCamClient", FakeYouCam)
    s = _settings(tmp_path, live_unit_budget=12, live_sessions_per_ip_day=2, live_session_unit_cap=7)
    return TestClient(app_mod.create_app(s))


def _files():
    return {
        "bride": ("b.jpg", (SAMPLES / SID / "bride.jpg").read_bytes(), "image/jpeg"),
        "inspiration": ("i.jpg", (SAMPLES / SID / "inspiration.jpg").read_bytes(), "image/jpeg"),
    }


def test_live_requires_consent_and_checks_photos(live_client):
    assert live_client.post("/api/live/sessions", files=_files()).status_code == 400
    bad = {"bride": ("b.jpg", b"not an image", "image/jpeg"), "inspiration": _files()["inspiration"]}
    r = live_client.post("/api/live/sessions", files=bad, data={"consent": "yes"})
    assert r.status_code == 422 and r.json()["checks"]["bride"]["issues"][0]["code"] == "not_an_image"


def test_live_flow_ledger_caps_and_delete(live_client):
    r = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    st = live_client.get(f"/api/sessions/{sid}").json()
    assert st["status"] == "ready" and st["mode"] == "live" and st["units_spent"] == 5
    r = live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "lighter"})
    assert r.status_code == 200 and r.json()["units_spent"] == 6
    live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "eyes", "op": "softer"})
    r = live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "eyes", "op": "softer"})
    assert r.status_code == 429 and r.json()["error"] == "session_cap"
    lim = live_client.get("/api/limits").json()
    assert lim["budget_spent"] == 7 and lim["budget_left"] == 5 and lim["available"] is True
    assert live_client.post(f"/api/sessions/{sid}/delete").json() == {"deleted": True}
    st = live_client.get(f"/api/sessions/{sid}").json()
    assert st["deleted"] and st["images"] == {}
    r2 = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r2.status_code == 200  # 5 more units: budget 12 now fully spent
    r3 = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r3.status_code == 429 and "budget" in r3.json()["reason"], "falls back to recorded samples"
    assert "Recorded samples still work" in r3.json()["reason"]


def test_live_refused_when_credit_low(live_client, monkeypatch):
    monkeypatch.setattr(FakeYouCam, "credit_value", 50)
    r = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r.status_code == 429 and "protect the API balance" in r.json()["reason"]
