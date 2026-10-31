import json
import re
import time

import pytest
from fastapi.testclient import TestClient
from helpers import HIDDEN_IDS, SAMPLES, UNLISTED_IDS, VISIBLE_IDS, make_v2_samples

from lookbrief import app as app_mod
from lookbrief import attest, palettes
from lookbrief.config import Settings
from lookbrief.youcam import UNITS, TaskResult

SID = "s2-classic-red"  # transfer-first sample these session tests were written for; hair_first has its own tests
assert SID in VISIBLE_IDS
V2_SAMPLES = None  # the recipe v2 contract on the recorded images (helpers.make_v2_samples)


@pytest.fixture(scope="session", autouse=True)
def v2_samples(tmp_path_factory):
    global V2_SAMPLES
    V2_SAMPLES = make_v2_samples(tmp_path_factory.mktemp("samples"))


def _settings(tmp_path, **kw) -> Settings:
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.samples_dir = V2_SAMPLES
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
    assert client.get("/healthz").json()["samples"] == VISIBLE_IDS
    html = client.get("/").text
    assert f"/try/{SID}" in html and "recorded real YouCam API results" in html
    lim = client.get("/api/limits").json()
    assert lim["available"] is False and "no API key" in lim["reason"]


def test_replay_session_state(client):
    sid = _replay_session(client)
    st = client.get(f"/api/sessions/{sid}").json()
    assert st["mode"] == "replay" and st["units_spent"] == 0
    assert st["order"] in ("transfer_first", "hair_first")
    assert set(st["images"]) >= {"bride", "inspiration", "look", "hair", "layer", "render"}
    assert st["steps"]["mu_transfer"]["mode"] == "replay" and st["steps"]["mu_transfer"]["task_id"]
    assert set(st["gaps"]["zones"]) == {"eyes", "cheeks", "lips"}
    assert len(st["outlines"]["eyes"]) == 2 and len(st["outlines"]["cheeks"]) == 2 and len(st["outlines"]["lips"]) == 1
    assert all(0 <= c <= 1 for poly in st["outlines"]["lips"] for pt in poly for c in pt)
    assert st["checks"]["bride"]["ok"] and st["checks"]["inspiration"]["ok"]
    assert abs(st["checks"]["bride"]["yaw_deg"]) < 15
    off = [o for o in st["edit_options"] if not o["available"]]
    assert off and all(o["reason"] in ("current", "softest", "boldest") for o in off), off
    assert not any(o["reason"] == "not_recorded" for o in off), "every button of the base look has its render"
    assert st["recipe"]["version"] == 2 and len(st["recipe"]["zones"]) == 9 and len(st["shades"]) == 9
    for url in st["images"].values():
        assert client.get(url).status_code == 200


def test_the_state_says_the_look_is_the_recipe_render(client):
    st = client.get(f"/api/sessions/{_replay_session(client)}").json()
    assert st["views"] == {"hero": "render", "before": "bride", "after": "render"}
    assert st["images"][st["views"]["hero"]].endswith("/render-base.png")
    assert st["images"][st["views"]["before"]].endswith("/bride.jpg")


def test_the_state_groups_the_zones_for_the_tabs(client):
    st = client.get(f"/api/sessions/{_replay_session(client)}").json()
    assert [g["label"] for g in st["zone_groups"]] == ["Eyes", "Face", "Lips"]
    zones = [z for g in st["zone_groups"] for z in g["zones"]]
    assert [z["zone"] for z in zones] == ["eyes", "liner", "lashes", "brows", "cheeks", "bronzer", "highlight", "lips",
                                          "lip_line"]
    assert zones[0]["label"] == "Eyelids" and zones[-1]["label"] == "Lip liner"


def test_replay_edits_undo_and_a_second_edit_replaces_the_first(client):
    sid = _replay_session(client)
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "bolder"})
    assert r.status_code == 200 and [e[0] for e in r.json()["edits"]] == ["cheeks"]
    assert r.json()["edits"][0][1].startswith("shade:"), "Bolder is stored as the shade it lands on"
    opts = [o for o in r.json()["edit_options"] if o["zone"] not in ("look", "cheeks") and "reason" not in o]
    assert len(opts) > 25, "after one change every recorded single change can still be pressed"
    assert all(o["replaces"] for o in opts), "samples hold one change: each of them replaces the current one"
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "shade:rose-gloss"})
    assert r.status_code == 200 and r.json()["edits"] == [["lips", "shade:rose-gloss"]]
    assert r.json()["images"]["render"].endswith("render-lips-shade-rose-gloss.png")
    r = client.post(f"/api/sessions/{sid}/edits", json={"action": "undo"})
    assert r.json()["edits"] == []
    assert client.post(f"/api/sessions/{sid}/edits", json={"zone": "nose", "op": "softer"}).status_code == 400


def test_a_circle_a_step_and_a_look_through_the_api(client):
    sid = _replay_session(client)  # s2: the classic red lip is pinned to ruby
    softer = palettes.step_from("light", "lips", "#e4b29c", "ruby", "softer")
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "softer"})
    assert r.status_code == 200 and r.json()["edits"] == [["lips", f"shade:{softer}"]]
    via_step = r.json()["images"]["render"]
    assert r.json()["recipe"]["zones"]["lips"]["shade_id"] == softer
    client.post(f"/api/sessions/{sid}/edits", json={"action": "reset"})
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": f"shade:{softer}"})
    assert r.json()["images"]["render"] == via_step, "Softer is the render of the neighbour circle"
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "look", "op": "evening"})
    assert r.status_code == 200 and r.json()["edits"] == [["look", "evening"]]
    assert r.json()["recipe"]["look"] == "evening" and r.json()["images"]["render"].endswith("render-look-evening.png")
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "look", "op": "softglam"})
    assert r.json()["edits"] == [] and r.json()["recipe"]["zones"]["lips"]["shade_id"] == "ruby", "back to the sample"


def test_lighter_and_deeper_are_gone_from_the_api(client):
    sid = _replay_session(client)
    for op in ("lighter", "deeper"):
        assert client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": op}).status_code == 400


def test_the_none_choice_drops_the_zone_from_the_request(client):
    sid = _replay_session(client)
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "highlight", "op": "shade:none"})
    assert r.status_code == 200 and "highlighter" not in [e["category"] for e in r.json()["vto_effects"]]
    assert "highlight" not in [x["zone"] for x in r.json()["shades"]] and len(r.json()["shades"]) == 8


def test_none_is_a_named_style_of_three_zones(client):
    opts = client.get(f"/api/sessions/{_replay_session(client)}").json()["edit_options"]
    assert {o["zone"]: o["name"] for o in opts if o["op"] == "shade:none"} == {
        "liner": "None", "highlight": "None", "lip_line": "None"}


def test_the_state_marks_the_zones_of_named_styles(client):
    st = client.get(f"/api/sessions/{_replay_session(client)}").json()
    style = {z["zone"]: z["style"] for g in st["zone_groups"] for z in g["zones"]}
    assert not style["eyes"] and not style["cheeks"] and not style["lips"]
    assert all(style[z] for z in ("liner", "lashes", "brows", "bronzer", "highlight", "lip_line"))


def test_a_quiet_edit_is_hidden_and_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    import shutil
    samples = tmp_path / "samples"
    shutil.copytree(V2_SAMPLES / SID, samples / SID, symlinks=True)
    mf_path = samples / SID / "manifest.json"
    mf = json.loads(mf_path.read_text())
    mf["quiet_edits"] = ["lips:shade:rosewood"]
    mf_path.write_text(json.dumps(mf))
    c = TestClient(app_mod.create_app(_settings(tmp_path / "x", samples_dir=samples)))
    sid = _replay_session(c)
    opts = c.get(f"/api/sessions/{sid}").json()["edit_options"]
    assert ("lips", "shade:rosewood") not in {(o["zone"], o["op"]) for o in opts}
    r = c.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "shade:rosewood"})
    assert r.status_code == 400 and r.json()["error"] == "quiet"
    assert c.get(f"/api/sessions/{sid}").json()["edits"] == []


@pytest.mark.parametrize("body", [
    {"zone": "lips", "op": "shade:no-such-shade"}, {"zone": "lips", "op": "shade:../../lookbrief.db"},
    {"zone": "look", "op": "party"}, {"zone": "lips"}, {"op": "softer"}, {}])
def test_unknown_edits_are_400_and_change_nothing(client, body):
    sid = _replay_session(client)
    assert client.post(f"/api/sessions/{sid}/edits", json=body).status_code == 400
    assert client.get(f"/api/sessions/{sid}").json()["edits"] == []


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

    calls: list = []

    def run_task(self, name, body, version=None):
        type(self).calls.append((name, body))
        step = {"mu-transfer": "mu_transfer", "hair-transfer": "hair_transfer", "makeup-vto": "render:base"}[name]
        return TaskResult(name, f"task-{name}", f"fake://{step}", 1.0, UNITS[name], {})

    def download(self, url):
        return (SAMPLES / SID / self.mf["steps"][url[len("fake://") :]]["image"]).read_bytes()


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "sk-fake")
    monkeypatch.setattr(app_mod, "YouCamClient", FakeYouCam)
    s = _settings(tmp_path, live_unit_budget=13, live_sessions_per_ip_day=2, live_session_unit_cap=8)
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
    # hair, transfer, render, even-out
    assert st["status"] == "ready" and st["mode"] == "live" and st["units_spent"] == 6
    assert st["order"] == "hair_first" and {"base", "look", "even", "render"} <= set(st["images"])
    assert st["steps"]["even_out"]["label"] == "foundation in her shade over the transfer"
    circles = [f"shade:{s.id}" for s in palettes.ladder(st["recipe"]["group"], "lips")
               if s.id != st["recipe"]["zones"]["lips"]["shade_id"]]
    r = live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": circles[0]})
    assert r.status_code == 200 and r.json()["units_spent"] == 7
    live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": circles[1]})
    r = live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": circles[2]})
    assert r.status_code == 429 and r.json()["error"] == "session_cap"
    lim = live_client.get("/api/limits").json()
    assert lim["budget_spent"] == 8 and lim["budget_left"] == 5 and lim["available"] is False
    b = live_client.post(f"/api/sessions/{sid}/brief").json()
    snap = live_client.get(f"/api/briefs/{b['brief_id']}?t={b['artist_url'].split('t=')[1]}").json()["snapshot"]
    assert {"hair", "skin"} <= set(snap["review_zones"]), "hair and the even-out foundation are confirmed too"
    skin = next(z for z in snap["zones"] if z["zone"] == "skin")
    assert skin["label"] == "Skin" and skin["product_hex"].startswith("#")
    assert live_client.post(f"/api/sessions/{sid}/delete").json() == {"deleted": True}
    st = live_client.get(f"/api/sessions/{sid}").json()
    assert st["deleted"] and st["images"] == {}
    r2 = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r2.status_code == 429 and "budget" in r2.json()["reason"], "5 units left, a look needs 6"
    assert "Recorded samples still work" in r2.json()["reason"]


def test_live_refused_when_credit_low(live_client, monkeypatch):
    monkeypatch.setattr(FakeYouCam, "credit_value", 50)
    r = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    assert r.status_code == 429 and "protect the API balance" in r.json()["reason"]


def test_expired_sessions_are_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    app = app_mod.create_app(_settings(tmp_path))
    c = TestClient(app)
    sid = _replay_session(c)
    assert (tmp_path / "data" / "sessions" / sid).exists()
    app.state.settings.replay_ttl_hours = 0  # the session is now past its TTL
    assert app.state.cleanup_expired() >= 1
    assert not (tmp_path / "data" / "sessions" / sid).exists()
    assert c.get(f"/api/sessions/{sid}").json()["deleted"] is True


# ---------------- regressions from the review of 2026-10-31 ----------------
def _brief(client):
    sid = _replay_session(client)
    b = client.post(f"/api/sessions/{sid}/brief").json()
    return sid, b["brief_id"], b["bride_url"].split("t=")[1], b["artist_url"].split("t=")[1]


def test_artist_never_sees_the_session_id_and_cannot_act_on_it(client, tmp_path, monkeypatch):
    sid, bid, bride, artist = _brief(client)
    view = client.get(f"/api/briefs/{bid}?t={artist}")
    assert sid not in view.text, "the session id is the bride's key and must not reach the artist"
    img = next(iter(view.json()["images"].values()))
    assert img.startswith(f"/b-media/{bid}/") and client.get(img).status_code == 200
    stranger = TestClient(client.app)  # no owner cookie
    assert stranger.post(f"/api/sessions/{sid}/brief").status_code == 403
    assert stranger.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "softer"}).status_code == 403
    assert stranger.get(f"/api/sessions/{sid}").status_code == 403
    assert stranger.get(f"/media/{sid}/bride.jpg").status_code == 403
    assert stranger.get(f"/b-media/{bid}/bride.jpg?t=wrong").status_code == 404
    assert stranger.get(f"/b-media/{bid}/lookbrief.db?t={artist}").status_code == 404


def test_changing_an_answer_withdraws_agreements(client):
    _, bid, bride, artist = _brief(client)
    zones = client.get(f"/api/briefs/{bid}?t={artist}").json()["snapshot"]["review_zones"]
    for z in zones:
        client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": z, "status": "do"})
    client.post(f"/api/briefs/{bid}/agree", json={"t": artist})
    v = client.post(
        f"/api/briefs/{bid}/review", json={"t": artist, "zone": "eyes", "status": "swap", "note": "x"}
    ).json()
    assert v["agreed"] == {}, "a changed answer must withdraw the earlier agreement"
    v = client.post(f"/api/briefs/{bid}/agree", json={"t": bride}).json()
    assert v["attestation"] is None, "the artist has not agreed to the changed answer yet"
    v = client.post(f"/api/briefs/{bid}/agree", json={"t": artist}).json()
    eyes = next(z for z in v["attestation"]["payload"]["zones"] if z["zone"] == "eyes")
    assert eyes["status"] == "swap" and v["attestation"]["payload"]["reviews_sha256"]
    # an identical re-submit is not a change
    same = client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": "eyes", "status": "swap", "note": "x"})
    assert same.status_code == 409  # signed versions are frozen


def test_bride_cannot_agree_before_the_artist_answered(client):
    _, bid, bride, _ = _brief(client)
    assert client.post(f"/api/briefs/{bid}/agree", json={"t": bride}).status_code == 409


def test_live_check_is_off_without_live_and_bombs_are_refused(client, live_client):
    png = ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")
    assert client.post("/api/live/check", files={"photo": png}, data={"role": "bride"}).status_code == 404
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (9000, 9000)).save(buf, format="PNG")  # 81 Mpx in a tiny file
    r = live_client.post(
        "/api/live/check", files={"photo": ("b.png", buf.getvalue(), "image/png")}, data={"role": "bride"}
    )
    assert r.status_code == 200 and r.json()["issues"][0]["code"] == "too_large"


def test_upload_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "sk-fake")
    monkeypatch.setattr(app_mod, "YouCamClient", FakeYouCam)
    c = TestClient(app_mod.create_app(_settings(tmp_path, max_upload_mb=1)))
    big = ("b.jpg", b"\xff\xd8" + b"0" * (1024 * 1024 + 10), "image/jpeg")
    assert c.post("/api/live/check", files={"photo": big}, data={"role": "bride"}).status_code == 413


def test_try_is_rate_limited_per_network(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    c = TestClient(app_mod.create_app(_settings(tmp_path, try_per_ip_day=2)))
    codes = [c.get(f"/try/{SID}", follow_redirects=False).status_code for _ in range(3)]
    assert codes == [303, 303, 429]


def test_replay_session_cap_evicts_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    app = app_mod.create_app(_settings(tmp_path, max_replay_sessions=1))
    c = TestClient(app)
    first = _replay_session(c)
    second = _replay_session(c)
    assert not (tmp_path / "data" / "sessions" / first).exists()
    assert (tmp_path / "data" / "sessions" / second).exists()


def test_a_button_on_the_edge_is_refused_and_changes_nothing(client):
    """A tap on a disabled button must not send an edit that "does nothing": the server applies the same rule."""
    sid = _replay_session(client)
    opt = next(o for o in client.get(f"/api/sessions/{sid}").json()["edit_options"] if o.get("reason") == "boldest")
    assert opt["note"] and not opt["available"]
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": opt["zone"], "op": opt["op"]})
    assert r.status_code == 400 and r.json() == {"error": "boldest", "reason": opt["note"]}
    assert client.get(f"/api/sessions/{sid}").json()["edits"] == []


def test_edit_of_a_zone_missing_from_the_look_is_400(client):
    sid = _replay_session(client)
    store = client.app.state.store
    sess = store.session(sid)
    state = sess["state"]
    state["recipe_base"]["zones"].pop("cheeks")
    state["recipe"]["zones"].pop("cheeks")
    store.update_session(sid, state=state)
    assert client.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "softer"}).status_code == 400


def test_runs_left_by_a_previous_process_are_marked_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    s = _settings(tmp_path)
    app = app_mod.create_app(s)
    sid, _ = app.state.store.create_session("replay", SID, "1.2.3.4", consent=False)
    app.state.store.update_session(sid, status="running")
    app2 = app_mod.create_app(s)  # restart
    assert app2.state.store.session(sid)["status"] == "error"


def test_hidden_samples_are_not_offered(client):
    hidden = HIDDEN_IDS
    assert hidden, "s1 is kept as calibration evidence but hidden"
    html = client.get("/").text
    for h in hidden:
        assert f"/try/{h}" not in html
        assert client.get(f"/try/{h}", follow_redirects=False).status_code == 404


@pytest.mark.parametrize("sid", [s for s in VISIBLE_IDS if s in ("s2-classic-red", "s3-mauve-smoky")])
def test_transfer_first_samples_keep_their_order(client, sid):
    r = client.get(f"/try/{sid}", follow_redirects=False)
    st = client.get(r.headers["location"].replace("/s/", "/api/sessions/")).json()
    assert st["status"] == "ready" and st["order"] == "transfer_first"
    assert "base" not in st["images"] and "even" not in st["images"] and "hair" in st["images"]


def test_unlisted_samples_work_by_link_only(tmp_path, monkeypatch):
    """A sample flagged `unlisted` opens by its /try link but is not on the home page or in /healthz.
    Checked on a copy, so the test does not depend on which real sample is unlisted today (none may be)."""
    import shutil

    samples = tmp_path / "samples"
    listed, unlisted = VISIBLE_IDS[0], VISIBLE_IDS[-1]
    assert listed != unlisted
    for s in (listed, unlisted):
        shutil.copytree(V2_SAMPLES / s, samples / s, symlinks=True)
    meta_path = samples / unlisted / "sample.json"
    meta = json.loads(meta_path.read_text())
    meta["unlisted"] = True
    meta_path.unlink()  # a link to the real sample
    meta_path.write_text(json.dumps(meta))
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    c = TestClient(app_mod.create_app(_settings(tmp_path / "x", samples_dir=samples)))
    html = c.get("/").text
    assert f"/try/{listed}" in html and listed in c.get("/healthz").json()["samples"]
    assert f"/try/{unlisted}" not in html and unlisted not in c.get("/healthz").json()["samples"]
    assert c.get(f"/try/{unlisted}", follow_redirects=False).status_code == 303


def test_heroine_sample_is_on_the_home_page(client):
    html = client.get("/").text
    assert "/try/s0-champagne-rose" in html and not UNLISTED_IDS
    assert "s0-champagne-rose" in client.get("/healthz").json()["samples"]


def test_footer_hides_the_repo_link_until_it_is_public(client, tmp_path, monkeypatch):
    assert "github.com" not in client.get("/").text
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    c = TestClient(app_mod.create_app(_settings(tmp_path / "x", source_url="https://example.org/repo")))
    assert 'href="https://example.org/repo"' in c.get("/").text


@pytest.mark.parametrize(("sample", "edit", "label"), [
    ("s2-classic-red", None, "Agreed look: her recipe, rendered by Makeup VTO"),
    ("s0-champagne-rose", None, "Agreed look: her recipe, rendered by Makeup VTO with foundation in her shade"),
    ("s0-champagne-rose", ["cheeks", "shade:peach"],
     "Agreed look: her recipe, rendered by Makeup VTO with foundation in her shade"),
    ("s2-classic-red", ["lips", "shade:rose-gloss"], "Agreed look: her recipe, rendered by Makeup VTO"),
])
def test_card_shows_the_agreed_look(client, sample, edit, label):
    """The card shows what was agreed: the render of her recipe, edited or not; never the transfer."""
    r = client.get(f"/try/{sample}", follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[1]
    if edit:
        assert client.post(f"/api/sessions/{sid}/edits", json={"zone": edit[0], "op": edit[1]}).status_code == 200
    b = client.post(f"/api/sessions/{sid}/brief").json()
    html = client.get(b["bride_url"].replace("/b/", "/card/")).text
    assert f"<figcaption>{label}</figcaption>" in html
    name = "render-base" if not edit else f"render-{edit[0]}-{edit[1].replace(':', '-')}"
    assert f"{name}.png" in html, "the agreed image is the render of her recipe"


def test_card_lists_every_zone_of_the_recipe_with_its_shade(client):
    sid = _replay_session(client)
    client.post(f"/api/sessions/{sid}/edits", json={"zone": "highlight", "op": "shade:none"})
    b = client.post(f"/api/sessions/{sid}/brief").json()
    bride = b["bride_url"].split("t=")[1]
    snap = client.get(f"/api/briefs/{b['brief_id']}?t={bride}").json()["snapshot"]
    assert "highlight" not in snap["review_zones"], "a product she left out is not reviewed"
    assert len(snap["review_zones"]) == 8 + 2, "eight zones, the hair and the skin"
    html = client.get(b["bride_url"].replace("/b/", "/card/")).text
    assert "Ruby" in html and "Rose gold smoke" in html and "#B0102E" in html
    assert "Highlighter" not in html.split("</table>")[0].split("<table")[1]


def test_the_brief_names_the_concealer_in_the_skin_row(client):
    sid = _replay_session(client)  # s2 has no foundation layer: the concealer is its skin row
    b = client.post(f"/api/sessions/{sid}/brief").json()
    bride = b["bride_url"].split("t=")[1]
    snap = client.get(f"/api/briefs/{b['brief_id']}?t={bride}").json()["snapshot"]
    skin = next(z for z in snap["zones"] if z["zone"] == "skin")
    assert skin["shade_name"].startswith("Concealer") and skin["intensity"] is None and "skin" in snap["review_zones"]
    sid = _sample_session(client, "s0-champagne-rose")
    b = client.post(f"/api/sessions/{sid}/brief").json()
    snap = client.get(f"/api/briefs/{b['brief_id']}?t={b['bride_url'].split('t=')[1]}").json()["snapshot"]
    skin = next(z for z in snap["zones"] if z["zone"] == "skin")
    assert skin["palette"] == ["#dfa588", "#E8B79C"] and skin["intensity"] == 30


def test_edits_after_even_out_keep_her_foundation(live_client, monkeypatch):
    """Blocker found by the media lane (31.10): after "Even out redness" an edit was re-rendered without the
    foundation, so the redness came back. Every re-render must carry the same foundation in her shade."""
    monkeypatch.setattr(FakeYouCam, "calls", [])
    r = live_client.post("/api/live/sessions", files=_files(), data={"consent": "yes"})
    sid = r.json()["session_id"]
    st = live_client.get(f"/api/sessions/{sid}").json()
    st = live_client.post(f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": "shade:rosewood"}).json()
    skin = st["even_out"]["skin_hex"]
    vto = [b["effects"] for n, b in FakeYouCam.calls if n == "makeup-vto"]
    makeup = {"eye_shadow", "blush", "lip_color"}
    renders = [e for e in vto if makeup & {x["category"] for x in e}]
    assert len(renders) == 2, "base re-render + one edit"
    for effects in renders:
        cats = [x["category"] for x in effects]
        assert cats.count("foundation") == 1 and cats.count("skin_smooth") == 1, cats
        f = next(x for x in effects if x["category"] == "foundation")["palettes"][0]
        assert f["color"] == skin and f["coverageIntensity"] == 30
    assert {"foundation", "concealer"} <= {x["category"] for x in st["vto_effects"]}
    assert st["gaps"]["reference"] == "even", "accuracy is measured against the evened look she is shown"
    assert st["map_reference"] == "even", "the recipe is read from the evened look, not the blotchy transfer"


# ---------------- click-test fixes of 2026-10-31 (CT3110-YCBQ) ----------------
def _sample_session(client, sample: str) -> str:
    r = client.get(f"/try/{sample}", follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[1]
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "ready"
    return sid


def _links(b: dict) -> tuple[str, str, str]:
    return b["brief_id"], b["bride_url"].split("t=")[1], b["artist_url"].split("t=")[1]


@pytest.mark.parametrize(("sample", "edit"), [
    ("s0-champagne-rose", None), ("s2-classic-red", None), ("s2-classic-red", ("cheeks", "bolder"))])
def test_brief_target_is_the_recipe_render_she_agrees_to(client, sample, edit):
    sid = _sample_session(client, sample)
    if edit:
        r = client.post(f"/api/sessions/{sid}/edits", json={"zone": edit[0], "op": edit[1]})
        assert r.status_code == 200, r.text
    bid, bride, artist = _links(client.post(f"/api/sessions/{sid}/brief").json())
    for t in (bride, artist):
        v = client.get(f"/api/briefs/{bid}?t={t}").json()
        assert v["snapshot"]["target"] == "render"
        assert client.get(v["images"]["render"]).status_code == 200
    figs = re.findall(r"<figcaption>([^<]*)</figcaption>", client.get(f"/card/{bid}?t={bride}").text)
    assert sum(f.startswith("Agreed look") for f in figs) == 1, f"exactly one photo is the agreed look: {figs}"
    assert figs[0] == "Bare face" and figs[1].startswith("Agreed look")
    assert "How we read the inspiration (Makeup Transfer)" in figs


def test_hair_first_before_photo_is_her_face_with_the_new_hair(client):
    sid = _sample_session(client, "s0-champagne-rose")
    bid, bride, _ = _links(client.post(f"/api/sessions/{sid}/brief").json())
    snap = client.get(f"/api/briefs/{bid}?t={bride}").json()["snapshot"]
    assert snap["before"] == "base"


def test_revise_without_changes_keeps_the_version_and_answers(client):
    sid = _sample_session(client, SID)
    bid, bride, artist = _links(client.post(f"/api/sessions/{sid}/brief").json())
    zones = client.get(f"/api/briefs/{bid}?t={artist}").json()["snapshot"]["review_zones"]
    for z in zones:
        client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": z, "status": "do"})
    client.post(f"/api/briefs/{bid}/agree", json={"t": artist})
    r = client.post(f"/api/briefs/{bid}/revise", json={"t": bride})
    assert r.status_code == 200
    v = r.json()
    assert v["unchanged"] is True and v["version"] == 1
    assert set(v["reviews"]) == set(zones) and "artist" in v["agreed"], "nothing the artist did is wiped"
    # a real change still makes a new version
    client.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "bolder"})
    v = client.post(f"/api/briefs/{bid}/revise", json={"t": bride}).json()
    assert v["version"] == 2 and not v.get("unchanged") and v["reviews"] == {} and v["agreed"] == {}
    assert [e[0] for e in v["snapshot"]["edits"]] == ["cheeks"]


def test_send_brief_twice_reuses_the_links_until_the_look_changes(client):
    sid = _sample_session(client, SID)
    first = client.post(f"/api/sessions/{sid}/brief").json()
    again = client.post(f"/api/sessions/{sid}/brief").json()
    assert again == first, "same look, same links"
    client.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "bolder"})
    changed = client.post(f"/api/sessions/{sid}/brief").json()
    assert changed["brief_id"] != first["brief_id"] and set(changed) == set(first)
    assert client.post(f"/api/sessions/{sid}/brief").json() == changed


@pytest.mark.parametrize("path", ["/s/{sid}", "/b/{bid}?t={t}", "/card/{bid}?t={t}"])
def test_expired_links_get_a_human_page(client, path):
    sid, bid, bride, _ = _brief(client)
    fresh = TestClient(client.app)
    for url in (path.format(sid="nosuchsession", bid="nosuchbrief", t="x"),  # gone after a restart
                path.format(sid="nosuchsession", bid=bid, t="wrong")):  # wrong token: same page, nothing leaked
        r = fresh.get(url)
        assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")
        assert "This link has expired" in r.text and 'href="/"' in r.text and "Start from a sample" in r.text
        assert "Demo links live until the demo server restarts" in r.text
    assert client.get("/api/briefs/nosuchbrief?t=x").json() == {"detail": "brief not found"}, "API stays JSON"
    assert client.get("/api/sessions/nosuchsession").json() == {"detail": "session not found"}


def test_look_link_in_another_browser_gets_a_human_page(client):
    sid, _, _, _ = _brief(client)
    assert client.get(f"/s/{sid}").status_code == 200, "the browser that made it still opens it"
    r = TestClient(client.app).get(f"/s/{sid}")
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/html")
    assert "This look is in another browser" in r.text and "Start from a sample" in r.text
    assert TestClient(client.app).get(f"/api/sessions/{sid}").status_code == 403, "API stays JSON and closed"


def test_footer_live_status_opens_the_live_page(client):
    html = client.get("/").text
    assert 'href="/live">Live status' in html and 'href="/api/limits"' not in html
    assert "Try a recorded sample instead" in client.get("/live").text


# ---------------- click-test fixes, second batch (CT3110-YCBQ) ----------------
def test_hair_first_brief_serves_the_hair_transfer_on_her_selfie(client):
    """s0 has no "hair" image: the Hair Transfer on her selfie is "base", and the brief shows it as the hair."""
    sid = _sample_session(client, "s0-champagne-rose")
    bid, bride, artist = _links(client.post(f"/api/sessions/{sid}/brief").json())
    for t in (bride, artist):
        v = client.get(f"/api/briefs/{bid}?t={t}").json()
        assert "hair" not in v["images"] and v["snapshot"]["order"] == "hair_first"
        r = client.get(v["images"]["base"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/")


def test_card_heading_says_not_agreed_until_both_agreed(client):
    _, bid, bride, artist = _brief(client)
    zones = client.get(f"/api/briefs/{bid}?t={artist}").json()["snapshot"]["review_zones"]
    for z in zones:
        client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": z, "status": "do"})
    client.post(f"/api/briefs/{bid}/agree", json={"t": artist})  # the artist can open the card after agreeing alone
    html = client.get(f"/card/{bid}?t={artist}").text
    assert "<h1>Look card · not agreed yet</h1>" in html and "<h1>Agreed look</h1>" not in html
    assert "<title>Look card · not agreed yet · Look Brief</title>" in html
    client.post(f"/api/briefs/{bid}/agree", json={"t": bride})
    html = client.get(f"/card/{bid}?t={artist}").text
    assert "<h1>Agreed look</h1>" in html and "not agreed yet" not in html
    assert "<title>Agreed look card · Look Brief</title>" in html


def test_home_and_live_page_say_uploads_are_off(client, live_client):
    html = client.get("/").text
    assert "On this demo server uploads are off — try a recorded sample below" in html
    assert 'href="#samples-h">Try the sample look</a>' in html
    live = client.get("/live").text
    assert "<h1>Upload is off in this demo</h1>" in live and "<h1>Your photos</h1>" not in live
    # where Live is available the copy stays as it was
    assert "uploads are off" not in live_client.get("/").text
    assert "<h1>Your photos</h1>" in live_client.get("/live").text


def test_image_work_runs_one_at_a_time(client, monkeypatch):
    """Nine visitors at once OOM-killed the 1.5 GB container (31.10): re-renders and look builds share one slot."""
    import threading as th

    from lookbrief import pipeline
    real, active, peak, guard = pipeline.rerender, [0], [0], th.Lock()

    def slow_rerender(*a, **kw):
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(0.05)
            return real(*a, **kw)
        finally:
            with guard:
                active[0] -= 1

    monkeypatch.setattr(pipeline, "rerender", slow_rerender)
    clients = [TestClient(client.app) for _ in range(4)]
    sids = [_replay_session(c) for c in clients]
    codes = []
    threads = [th.Thread(target=lambda c=c, sid=sid: codes.append(
        c.post(f"/api/sessions/{sid}/edits", json={"zone": "cheeks", "op": "bolder"}).status_code))
        for c, sid in zip(clients, sids, strict=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 4 and peak[0] == 1, (codes, peak[0])
