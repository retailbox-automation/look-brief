"""Replay: the whole path of a stacked look through the app, on the real samples: Nadya's case, every look, removal,
Undo, click order, captions, the signed record. Live stays one real call."""

import hashlib
import io
import json
import subprocess
import sys
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from helpers import ROOT, SAMPLES, geometry, grow, load_rgb, recorded_samples, zone_gap
from PIL import Image

from lookbrief import app as app_mod
from lookbrief import layers, makeup_map, pipeline
from lookbrief import recipe as rcp
from lookbrief.color import delta_e2000
from lookbrief.config import Settings
from lookbrief.engine import LiveEngine, ReplayEngine, SessionCtx
from lookbrief.youcam import UNITS, TaskResult

LID = {"s0-champagne-rose": ("chocolate", "Chocolate"), "s2-classic-red": ("chocolate", "Chocolate"),
       "s3-mauve-smoky": ("burgundy", "Burgundy")}
CHAIN = {"s0-champagne-rose": [("eyes", "shade:chocolate"), ("liner", "shade:wing"), ("lashes", "shade:volume"),
                               ("brows", "shade:defined"), ("cheeks", "shade:peach"), ("lips", "shade:ruby")]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "youcam_key", lambda: "")
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.samples_dir = SAMPLES
    return TestClient(app_mod.create_app(s))


def session(client, sample) -> str:
    sid = client.get(f"/try/{sample}", follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "ready"
    return sid


def edit(client, sid, **body) -> dict:
    r = client.post(f"/api/sessions/{sid}/edits", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def image(client, st) -> bytes:
    r = client.get(st["images"]["render"])
    assert r.status_code == 200
    return r.content


def pixels(client, st, size) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(image(client, st))).convert("RGB").resize(size), dtype=np.uint8)


def recorded(sample, key) -> np.ndarray:
    mf, _, _, size = geometry(sample)
    return load_rgb(SAMPLES / sample / mf["steps"][key]["image"], size)


def wing(sample) -> np.ndarray:
    """The pixels the Wing single moves on the lid of her choice, outside the lid mask: the wing itself."""
    _, _, masks, _ = geometry(sample)
    base, single = (makeup_map._lab(recorded(sample, k)) for k in ("render:base", "render:liner:shade:wing"))
    return (delta_e2000(base, single) > 12) & grow(masks["liner"], 30)


# ---------------- acceptance 1 ----------------
@pytest.mark.parametrize("sample", recorded_samples(list(LID)))
def test_nadyas_case_lids_stay_wing_is_added_and_the_tab_keeps_the_shade(client, sample):
    shade, name = LID[sample]
    sid = session(client, sample)
    edit(client, sid, zone="eyes", op=f"shade:{shade}")
    st = edit(client, sid, zone="liner", op="shade:wing")
    assert st["edits"] == [["eyes", f"shade:{shade}"], ["liner", "shade:wing"]] and st["notice"] == ""
    assert {r["zone"]: r["shade_name"] for r in st["shades"]}["eyes"] == name
    assert st["recipe"]["zones"]["liner"]["shade_id"] == "wing"
    _, _, masks, size = geometry(sample)
    now, lid_only = pixels(client, st, size), recorded(sample, f"render:eyes:shade:{shade}")
    lids = masks["eyes"] & ~grow(masks["liner"], 3)
    assert zone_gap(now, lid_only, lids)[0] < 2.0, "the lids stay"
    assert zone_gap(now, recorded(sample, "render:base"), lids)[0] > 3.0, "and the lids are not the look's own"
    assert zone_gap(now, lid_only, wing(sample))[0] > 5.0, "the wing is there"
    assert zone_gap(now, recorded(sample, "render:liner:shade:wing"), lids)[0] > 3.0, "not the old last click"


# ---------------- acceptance 2 ----------------
@pytest.mark.parametrize("sample", recorded_samples(list(LID)))
@pytest.mark.parametrize("look", [None, "fresh", "evening"])
def test_tabs_stack_across_six_zones_on_every_look(client, sample, look):
    sid = session(client, sample)
    st = edit(client, sid, zone="look", op=look) if look else client.get(f"/api/sessions/{sid}").json()
    _, _, masks, size = geometry(sample)
    picked = {}
    for zone in ("eyes", "liner", "lashes", "brows", "cheeks", "lips"):
        opts = [o for o in st["edit_options"] if o["zone"] == zone and o["op"].startswith("shade:") and o["available"]]
        if not opts:
            continue
        before = pixels(client, st, size)
        st = edit(client, sid, zone=zone, op=opts[-1]["op"])
        picked[zone] = opts[-1]["op"].removeprefix("shade:")
        moved = delta_e2000(*[makeup_map._lab(x)[masks[zone]] for x in (before, pixels(client, st, size))])
        assert np.percentile(moved, 90) > 1.0, zone
        assert {z: st["recipe"]["zones"][z]["shade_id"] for z in picked} == picked, "the earlier zones stay"
    assert {"eyes", "cheeks", "lips"} <= set(picked) and len(picked) >= 4
    assert [e[0] for e in st["edits"] if e[0] != "look"] == list(picked)
    assert st["recipe"]["look"] == (look or "softglam")
    assert st["composition"]["zone_renders"] == len(picked)


# ---------------- acceptance 3 ----------------
def test_remove_takes_one_zone_back_to_the_look_and_keeps_the_others(client):
    sample = "s0-champagne-rose"
    sid = session(client, sample)
    edit(client, sid, zone="eyes", op="shade:chocolate")
    edit(client, sid, zone="liner", op="shade:wing")
    st = edit(client, sid, zone="lips", op="shade:ruby")
    st = edit(client, sid, action="remove", zone="liner")
    assert st["edits"] == [["eyes", "shade:chocolate"], ["lips", "shade:ruby"]]
    assert st["recipe"]["zones"]["liner"]["shade_id"] == st["recipe_base"]["zones"]["liner"]["shade_id"]
    assert st["recipe"]["zones"]["eyes"]["shade_id"] == "chocolate"
    other = session(client, sample)
    edit(client, other, zone="eyes", op="shade:chocolate")
    assert image(client, st) == image(client, edit(client, other, zone="lips", op="shade:ruby")), "as if never added"


def test_remove_on_a_look_returns_to_that_look_not_to_soft_glam(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="look", op="evening")
    edit(client, sid, zone="liner", op="shade:flick")
    st = edit(client, sid, action="remove", zone="liner")
    assert st["edits"] == [["look", "evening"]] and st["recipe"]["zones"]["liner"]["shade_id"] == "wing"
    assert st["images"]["render"].endswith("render-look-evening.png") and st["composition"] is None


def test_removing_the_last_change_gives_the_real_render_back(client):
    sid = session(client, "s0-champagne-rose")
    first = client.get(f"/api/sessions/{sid}").json()
    edit(client, sid, zone="eyes", op="shade:chocolate")
    st = edit(client, sid, action="remove", zone="eyes")
    assert st["edits"] == [] and image(client, st) == image(client, first)


@pytest.mark.parametrize("body", [{"action": "remove", "zone": "lips"}, {"action": "remove", "zone": "look"},
                                  {"action": "remove", "zone": "nose"}, {"action": "remove"}])
def test_remove_with_nothing_to_remove_is_refused_and_changes_nothing(client, body):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="look", op="evening")
    st = edit(client, sid, zone="eyes", op="shade:chocolate")
    assert client.post(f"/api/sessions/{sid}/edits", json=body).status_code == 400
    assert client.get(f"/api/sessions/{sid}").json()["edits"] == st["edits"]


# ---------------- acceptance 4 ----------------
def test_undo_walks_a_chain_of_six_zones_back_byte_for_byte_and_reset_clears_it(client):
    sample = "s0-champagne-rose"
    sid = session(client, sample)
    trail = [hashlib.sha256(image(client, client.get(f"/api/sessions/{sid}").json())).hexdigest()]

    def step(**body):
        trail.append(hashlib.sha256(image(client, edit(client, sid, **body))).hexdigest())

    for zone, op in CHAIN[sample]:
        step(zone=zone, op=op)
    step(zone="liner", op="shade:flick")  # a shade change inside one zone
    step(action="remove", zone="brows")  # a removal
    assert len(set(trail)) == len(trail), "every step shows"
    for want in reversed(trail[:-1]):
        got = hashlib.sha256(image(client, edit(client, sid, action="undo"))).hexdigest()
        assert got == want
    assert client.get(f"/api/sessions/{sid}").json()["can_undo"] is False
    for zone, op in CHAIN[sample]:
        edit(client, sid, zone=zone, op=op)
    st = edit(client, sid, action="reset")
    assert st["edits"] == [] and st["can_undo"] is False and st["composition"] is None
    assert hashlib.sha256(image(client, st)).hexdigest() == trail[0]


def test_any_click_order_gives_the_same_file_and_the_same_recipe(client):
    sample = "s0-champagne-rose"
    clicks = [*CHAIN[sample], ("lip_line", "shade:defined")]
    one, two = session(client, sample), session(client, sample)
    for zone, op in clicks:
        a = edit(client, one, zone=zone, op=op)
    for zone, op in reversed(clicks):
        b = edit(client, two, zone=zone, op=op)
    assert image(client, a) == image(client, b)
    assert a["images"]["render"].rsplit("/", 1)[1] == b["images"]["render"].rsplit("/", 1)[1]
    assert a["recipe_sha256"] == b["recipe_sha256"]


def test_a_lip_liner_she_chose_survives_either_click_order(client):
    """A lip pulls the plain liner with it (s2), so applying the clicks as they came would give two recipes."""
    clicks = [("lips", "shade:raspberry"), ("lip_line", "shade:natural")]
    one, two = session(client, "s2-classic-red"), session(client, "s2-classic-red")
    for zone, op in clicks:
        a = edit(client, one, zone=zone, op=op)
    for zone, op in reversed(clicks):
        b = edit(client, two, zone=zone, op=op)
    assert a["recipe"]["zones"]["lip_line"]["shade_id"] == b["recipe"]["zones"]["lip_line"]["shade_id"] == "natural"
    assert a["recipe_sha256"] == b["recipe_sha256"] and image(client, a) == image(client, b)


def test_bolder_steps_inside_a_stack_and_keeps_the_other_zones(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:bronze")
    edit(client, sid, zone="liner", op="shade:wing")
    st = edit(client, sid, zone="eyes", op="bolder")  # bronze -> chocolate on this palette
    assert sorted(st["edits"]) == [["eyes", "shade:chocolate"], ["liner", "shade:wing"]]
    assert st["composition"]["zone_renders"] == 2


def test_softer_back_to_the_look_drops_that_zone_and_keeps_the_others(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    edit(client, sid, zone="liner", op="shade:wing")
    st = edit(client, sid, zone="eyes", op="softer")  # chocolate -> rose gold, the lid Soft glam wears
    assert st["edits"] == [["liner", "shade:wing"]] and st["recipe"]["zones"]["eyes"]["shade_id"] == "rose-gold"
    assert st["composition"] is None and st["images"]["render"].endswith("render-liner-shade-wing.png")


# ---------------- what stays a real render ----------------
def test_one_change_stays_the_real_render_with_its_task_id(client):
    sid = session(client, "s0-champagne-rose")
    st = edit(client, sid, zone="eyes", op="shade:chocolate")
    assert st["composition"] is None and st["images"]["render"].endswith("render-eyes-shade-chocolate.png")
    assert image(client, st) == (SAMPLES / "s0-champagne-rose/results/render__eyes__shade__chocolate.png").read_bytes()
    assert st["steps"]["render:eyes:shade:chocolate"]["task_id"]


def test_a_style_on_a_look_is_assembled_because_no_render_holds_it(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="look", op="evening")
    st = edit(client, sid, zone="liner", op="shade:flick")
    assert st["composition"]["zone_renders"] == 1
    assert st["composition"]["caption"] == "Assembled from 1 recorded YouCam Makeup VTO result, one per zone"


def test_a_style_soft_glam_holds_and_the_look_does_not_is_off_and_says_why(client):
    sid = session(client, "s0-champagne-rose")
    st = edit(client, sid, zone="look", op="fresh")  # Classic wears a soft brown liner, recorded on no single
    opt = next(o for o in st["edit_options"] if (o["zone"], o["op"]) == ("liner", "shade:classic"))
    assert opt["reason"] == "not_recorded" and opt["note"]
    r = client.post(f"/api/sessions/{sid}/edits", json={"zone": "liner", "op": "shade:classic"})
    assert r.status_code == 409 and r.json()["error"] == "not_recorded"


def test_a_session_holds_one_file_per_look_however_often_she_goes_there(client, tmp_path):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    edit(client, sid, zone="liner", op="shade:wing")
    edit(client, sid, action="undo")
    edit(client, sid, zone="liner", op="shade:wing")
    assert len(list((tmp_path / "data" / "sessions" / sid).glob("stack-*.jpg"))) == 1


# ---------------- the cap of a session ----------------
LIPS = ["light-pink", "peach-pink", "rosy-peach", "warm-coral", "nude-rose", "rose-gloss", "warm-rose", "raspberry"]


def stack_files(tmp_path, sid) -> set[str]:
    return {p.name for p in (tmp_path / "data" / "sessions" / sid).glob("stack-*.jpg")}


def file_of(st) -> str:
    return st["images"]["render"].rsplit("/", 1)[1]


def test_the_cap_holds_while_she_keeps_choosing_and_the_current_look_stays(client, tmp_path, monkeypatch):
    monkeypatch.setattr(layers, "MAX_STACK_FILES", 3)
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    for lip in LIPS:
        st = edit(client, sid, zone="lips", op=f"shade:{lip}")
        assert len(stack_files(tmp_path, sid)) <= 3 and file_of(st) in stack_files(tmp_path, sid)
        assert client.get(st["images"]["render"]).status_code == 200


def test_a_file_a_brief_shows_survives_eviction_with_its_links_and_its_hash(client, tmp_path, monkeypatch):
    monkeypatch.setattr(layers, "MAX_STACK_FILES", 3)
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    sent = edit(client, sid, zone="lips", op=f"shade:{LIPS[0]}")
    b = client.post(f"/api/sessions/{sid}/brief").json()
    artist = b["artist_url"].split("t=")[1]
    view = client.get(f"/api/briefs/{b['brief_id']}?t={artist}").json()
    for lip in LIPS[1:]:
        edit(client, sid, zone="lips", op=f"shade:{lip}")
    assert file_of(sent) in stack_files(tmp_path, sid), "the oldest file, and the brief still shows it"
    assert len(stack_files(tmp_path, sid)) == 3, "and the cap held around it"
    r = client.get(view["images"]["render"])
    assert r.status_code == 200, "the /b-media link of the sent brief"
    assert hashlib.sha256(r.content).hexdigest() == view["snapshot"]["images_sha256"]["render"]
    assert client.get(b["artist_url"].replace("/b/", "/card/")).status_code == 200


def test_after_a_brief_is_revised_the_file_it_no_longer_shows_can_go(client, tmp_path, monkeypatch):
    monkeypatch.setattr(layers, "MAX_STACK_FILES", 3)
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    first = edit(client, sid, zone="lips", op=f"shade:{LIPS[0]}")
    b = client.post(f"/api/sessions/{sid}/brief").json()
    edit(client, sid, zone="lips", op=f"shade:{LIPS[1]}")
    bride = b["bride_url"].split("t=")[1]
    assert client.post(f"/api/briefs/{b['brief_id']}/revise", json={"t": bride}).status_code == 200
    for lip in LIPS[2:]:
        edit(client, sid, zone="lips", op=f"shade:{lip}")
    assert file_of(first) not in stack_files(tmp_path, sid)


def test_undo_after_eviction_makes_the_same_bytes_again(client, tmp_path, monkeypatch):
    monkeypatch.setattr(layers, "MAX_STACK_FILES", 3)
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    trail = []
    for lip in LIPS:
        st = edit(client, sid, zone="lips", op=f"shade:{lip}")
        trail.append((file_of(st), hashlib.sha256(image(client, st)).hexdigest()))
    assert trail[0][0] not in stack_files(tmp_path, sid), "precondition: the first file was evicted"
    for name, digest in reversed(trail[:-1]):
        st = edit(client, sid, action="undo")
        assert file_of(st) == name and hashlib.sha256(image(client, st)).hexdigest() == digest
        assert len(stack_files(tmp_path, sid)) <= 3


def test_a_brief_waits_for_an_edit_in_flight(client, monkeypatch):
    """The edit may evict the file of the look the brief is about to reference: one at a time per session, and the
    brief reads the session after the edit."""
    real, entered, go = pipeline.rerender, threading.Event(), threading.Event()

    def held(*a, **kw):
        entered.set()
        assert go.wait(20)
        return real(*a, **kw)

    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    monkeypatch.setattr(pipeline, "rerender", held)
    done: dict = {}
    other = TestClient(client.app, cookies=client.cookies)
    changing = threading.Thread(target=lambda: done.update(edit=client.post(
        f"/api/sessions/{sid}/edits", json={"zone": "lips", "op": f"shade:{LIPS[0]}"})))
    changing.start()
    assert entered.wait(20)
    briefing = threading.Thread(target=lambda: done.update(brief=other.post(f"/api/sessions/{sid}/brief")))
    briefing.start()
    briefing.join(0.5)
    assert briefing.is_alive(), "the brief must not read the session while an edit is under way"
    go.set()
    changing.join(30)
    briefing.join(30)
    assert done["edit"].status_code == 200 and done["brief"].status_code == 200
    b = done["brief"].json()
    snap = client.get(f"/api/briefs/{b['brief_id']}?t={b['bride_url'].split('t=')[1]}").json()["snapshot"]
    assert [e[0] for e in snap["edits"]] == ["eyes", "lips"], "the brief holds the look after the edit"


# ---------------- acceptance 5 ----------------
ASSEMBLED = "Assembled from 3 recorded YouCam Makeup VTO results, one per zone"


def _three(client, sid) -> dict:
    edit(client, sid, zone="eyes", op="shade:chocolate")
    edit(client, sid, zone="liner", op="shade:wing")
    return edit(client, sid, zone="lashes", op="shade:volume")


def test_a_composed_look_says_so_and_names_no_single_task(client):
    st = _three(client, (sid := session(client, "s0-champagne-rose")))
    assert st["composition"]["caption"] == ASSEMBLED
    assert "render:eyes:shade:chocolate+liner:shade:wing+lashes:shade:volume" not in st["steps"]
    assert "rendered by" not in json.dumps(st["composition"])
    b = client.post(f"/api/sessions/{sid}/brief").json()
    html = client.get(b["bride_url"].replace("/b/", "/card/")).text
    assert f"<figcaption>Agreed look: her recipe. {ASSEMBLED}</figcaption>" in html
    assert "rendered by" not in html.lower()


def test_a_card_of_one_change_keeps_todays_words(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    b = client.post(f"/api/sessions/{sid}/brief").json()
    html = client.get(b["bride_url"].replace("/b/", "/card/")).text
    assert "<figcaption>Agreed look: her recipe, rendered by Makeup VTO</figcaption>" in html
    assert "Assembled from" not in html


# ---------------- acceptance 6 ----------------
def _signed(client, sid) -> dict:
    b = client.post(f"/api/sessions/{sid}/brief").json()
    bid, bride, artist = b["brief_id"], b["bride_url"].split("t=")[1], b["artist_url"].split("t=")[1]
    for z in client.get(f"/api/briefs/{bid}?t={artist}").json()["snapshot"]["review_zones"]:
        client.post(f"/api/briefs/{bid}/review", json={"t": artist, "zone": z, "status": "do"}).raise_for_status()
    client.post(f"/api/briefs/{bid}/agree", json={"t": artist})
    return client.post(f"/api/briefs/{bid}/agree", json={"t": bride}).json()["attestation"]


def test_the_signature_covers_the_method_and_every_component_task(client, tmp_path):
    sample = "s0-champagne-rose"
    sid = session(client, sample)
    _three(client, sid)
    att = _signed(client, sid)
    steps = json.loads((SAMPLES / sample / "manifest.json").read_text())["steps"]
    made = att["payload"]["composition"]
    assert made["method"] == "lookbrief.zone-stack.v1" and made["zone_renders"] == 3
    assert made["frame"]["task_id"] == steps["render:base"]["task_id"]
    assert [x["task_id"] for x in made["layers"]] == [steps[f"render:{k}"]["task_id"] for k in (
        "eyes:shade:chocolate", "liner:shade:wing", "lashes:shade:volume")]
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(att))
    tampered = json.loads(good.read_text())
    tampered["payload"]["composition"]["layers"][0]["task_id"] = "someone-else"
    bad.write_text(json.dumps(tampered))
    run = [sys.executable, str(ROOT / "scripts" / "verify_card.py")]
    ok = subprocess.run([*run, str(good)], capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0 and "VALID" in ok.stdout and "lookbrief.zone-stack.v1" in ok.stdout, ok.stdout + ok.stderr
    assert subprocess.run([*run, str(bad)], capture_output=True, text=True, timeout=60).returncode == 1


def test_a_real_render_signs_no_composition(client):
    sid = session(client, "s0-champagne-rose")
    edit(client, sid, zone="eyes", op="shade:chocolate")
    assert _signed(client, sid)["payload"]["composition"] is None


# ---------------- limits ----------------
def test_composing_waits_for_the_slot_of_image_work(client, monkeypatch):
    real, active, peak, guard = ReplayEngine.compose, [0], [0], threading.Lock()

    def tracked(self, *a, **kw):
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(0.05)
            return real(self, *a, **kw)
        finally:
            with guard:
                active[0] -= 1

    monkeypatch.setattr(ReplayEngine, "compose", tracked)
    clients = [TestClient(client.app) for _ in range(4)]
    sids = [session(c, "s0-champagne-rose") for c in clients]
    for c, sid in zip(clients, sids, strict=True):
        edit(c, sid, zone="eyes", op="shade:chocolate")
    codes = []
    threads = [threading.Thread(target=lambda c=c, sid=sid: codes.append(c.post(
        f"/api/sessions/{sid}/edits", json={"zone": "liner", "op": "shade:wing"}).status_code))
        for c, sid in zip(clients, sids, strict=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 4 and peak[0] == 1, (codes, peak[0])


def test_one_compose_adds_under_40_mb():
    """A full look: eight zones. numpy buffers are traced; PIL decodes one render at a time on top."""
    import tracemalloc

    sample = "s0-champagne-rose"
    mf, face, _, _ = geometry(sample)
    base = mf["steps"]["render:base"]["recipe"]
    edits = [[z, op] for z, op in CHAIN[sample]] + [["highlight", "shade:radiant"], ["lip_line", "shade:defined"]]
    engine = ReplayEngine(SAMPLES / sample)
    stack = engine.stack_of(base, edits)
    recipe = rcp.apply_edits(base, layers.canonical(edits))
    tracemalloc.start()
    engine.compose(stack, recipe, face)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 40 * 1024 * 1024, peak / 1024 / 1024


# ---------------- acceptance 7 ----------------
class OneCallClient:
    """A Live client that holds every real call: Live must stay one call with the whole recipe."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def upload(self, content, name, content_type="image/jpeg"):
        return f"file-{name}"

    def run_task(self, name, body, version=None):
        self.calls.append((name, body))
        return TaskResult(name, f"task-{len(self.calls)}", "fake://render", 1.0, UNITS[name], {})

    def download(self, url):
        return (SAMPLES / "s2-classic-red/results/render__base.png").read_bytes()


def test_live_sends_the_whole_recipe_in_one_call_whatever_was_chosen_before(tmp_path):
    sample = SAMPLES / "s2-classic-red"
    mf = json.loads((sample / "manifest.json").read_text())
    ctx = SessionCtx((sample / "bride.jpg").read_bytes(), (sample / "inspiration.jpg").read_bytes())
    ctx.ids["bride"] = "file-bride"
    client = OneCallClient()
    engine = LiveEngine(client)
    workdir = tmp_path / "live"
    workdir.mkdir()
    (workdir / "bride.jpg").write_bytes(ctx.bride_jpeg)
    (workdir / "look.jpg").write_bytes((sample / mf["steps"]["mu_transfer"]["image"]).read_bytes())
    state = {"steps": {}, "images": {"look": "look.jpg"}, "order": "transfer_first", "bare": "bride.jpg",
             "recipe_base": mf["steps"]["render:base"]["recipe"], "map": mf["map"], "gaps_base": {}}
    edits = [["eyes", "shade:chocolate"], ["liner", "shade:wing"], ["lips", "shade:wine"]]
    state = pipeline.rerender(engine, ctx, workdir, state, edits)
    assert [name for name, _ in client.calls] == ["makeup-vto"], "one real call, nothing composed"
    sent = {e["category"]: e for e in client.calls[0][1]["effects"]}
    wanted = rcp.apply_edits(state["recipe_base"], edits)["zones"]
    assert sent["eye_shadow"]["palettes"][0]["color"] == wanted["eyes"]["palette"][0]
    assert sent["eye_liner"]["pattern"]["name"] == wanted["liner"]["pattern"] == "Upper4"
    assert sent["lip_color"]["palettes"][0]["color"] == wanted["lips"]["palette"][0]
    assert state["composition"] is None and state["images"]["render"].endswith(".png")
    assert state["steps"][f"render:{rcp.edit_key(edits)}"]["task_id"] == "task-1"


def test_live_plans_any_list_without_asking_what_is_recorded():
    base = json.loads((SAMPLES / "s2-classic-red/manifest.json").read_text())["steps"]["render:base"]["recipe"]
    state = {"recipe_base": base, "recipe": base, "edits": [["eyes", "shade:chocolate"]]}
    assert pipeline.plan_edit(state, "liner", "shade:wing", None) == {
        "edits": [["eyes", "shade:chocolate"], ["liner", "shade:wing"]], "notice": ""}
