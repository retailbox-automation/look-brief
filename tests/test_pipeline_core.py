"""The look as data: what the hero shows, which buttons work and why, and how a sample's grid is recorded."""

import io
import json

import pytest
from helpers import SAMPLES, make_v2_samples
from PIL import Image

from lookbrief import palettes, pipeline
from lookbrief import recipe as rcp
from lookbrief.engine import BudgetReached, GridEngine, LiveEngine, Recorder, ReplayEngine, SessionCtx, hair_label
from lookbrief.youcam import UNITS, TaskResult


def _state(base=None, edits=None):
    base = base or rcp.look_recipe("light", "softglam")
    edits = edits or []
    return {"recipe_base": base, "edits": edits, "recipe": rcp.apply_edits(base, edits)}


def _options(state, keys=None):
    return {(o["zone"], o["op"]): o for o in pipeline.edit_options(state, keys)}


# ---------------- buttons ----------------
def test_options_cover_looks_steps_strength_and_every_circle():
    opts = _options(_state())
    assert {("look", k) for k in palettes.LOOK_IDS} <= set(opts)
    for z in palettes.ZONES:
        assert {(z, op) for op in rcp.EDIT_OPS} <= set(opts), z
        assert {(z, f"shade:{s.id}") for s in palettes.ladder("light", z)} <= set(opts), z
    assert len(opts) == 3 + 36 + 43


def test_a_circle_carries_what_the_sheet_draws():
    base = rcp.look_recipe("light", "softglam")
    opts = _options(_state(base))
    ruby = opts[("lips", "shade:ruby")]
    assert ruby["hex"] == "#B0102E" and ruby["name"] == "Ruby" and ruby["texture"] == "matte"
    assert ruby["selected"] is False and ruby["available"] is True
    now = opts[("lips", f"shade:{base['zones']['lips']['shade_id']}")]
    assert now["selected"] is True and now["available"] is False and now["reason"] == "current"
    eyes = opts[("eyes", f"shade:{base['zones']['eyes']['shade_id']}")]
    assert eyes["colors"] == ["#C98F7E", "#5C342A"] and eyes["hex"] == "#C98F7E"


def test_a_button_on_the_edge_is_off_and_says_why():
    base = rcp.look_recipe("light", "softglam")
    top = palettes.ladder("light", "lips")[0].id
    opts = _options(_state(base, [["lips", f"shade:{top}"]]))
    o = opts[("lips", "lighter")]
    assert o["available"] is False and o["reason"] == "lightest" and o["note"]
    assert opts[("lips", "deeper")]["available"] is True
    assert all(o.get("reason") != "light" for o in opts.values()), "the old reason is gone"


def test_the_softer_gate_of_the_old_rule_is_gone():
    assert not hasattr(pipeline, "softer_blocked")


def test_replay_offers_only_what_is_recorded():
    base = rcp.look_recipe("light", "softglam")
    keys = {"base", "lips:softer", "look:evening", "lips:shade:ruby"}
    opts = _options(_state(base), keys)
    assert opts[("lips", "softer")]["available"] and opts[("look", "evening")]["available"]
    assert opts[("lips", "shade:ruby")]["available"]
    assert not opts[("lips", "bolder")]["available"] and opts[("lips", "bolder")]["reason"] == "not_recorded"


def test_replay_keeps_one_change_a_new_one_replaces_it():
    base = rcp.look_recipe("light", "softglam")
    keys = {"base", "lips:softer", "cheeks:bolder", "lips:shade:ruby"}
    st = _state(base, [["lips", "softer"]])
    plan = pipeline.plan_edit(st, "cheeks", "bolder", keys)
    assert plan == {"edits": [["cheeks", "bolder"]], "replaces": True}
    assert _options(st, keys)[("cheeks", "bolder")]["replaces"] is True


def test_replay_a_second_tap_on_the_same_strength_has_nothing_recorded():
    base = rcp.look_recipe("light", "softglam")
    st = _state(base, [["lips", "softer"]])
    o = _options(st, {"base", "lips:softer"})[("lips", "softer")]
    assert o["available"] is False and o["reason"] == "not_recorded"


def test_a_recorded_combination_is_kept():
    base = rcp.look_recipe("light", "softglam")
    st = _state(base, [["lips", "softer"]])
    keys = {"base", "lips:softer", "lips:softer+cheeks:bolder", "cheeks:bolder"}
    assert pipeline.plan_edit(st, "cheeks", "bolder", keys) == {
        "edits": [["lips", "softer"], ["cheeks", "bolder"]], "replaces": False}


def test_lighter_resolves_from_the_shade_on_her_face_not_the_base():
    base = rcp.look_recipe("light", "softglam")
    ladder = [s.id for s in palettes.ladder("light", "lips")]
    st = _state(base, [["lips", "shade:ruby"]])
    expected = ladder[ladder.index("ruby") - 1]
    plan = pipeline.plan_edit(st, "lips", "lighter", {"base", f"lips:shade:{expected}", "lips:shade:ruby"})
    assert plan["edits"] == [["lips", f"shade:{expected}"]]


def test_stepping_back_to_the_base_shade_is_the_base_render():
    base = rcp.look_recipe("light", "softglam")
    ladder = [s.id for s in palettes.ladder("light", "lips")]
    i = ladder.index(base["zones"]["lips"]["shade_id"])
    st = _state(base, [["lips", f"shade:{ladder[i + 1]}"]])
    assert pipeline.plan_edit(st, "lips", "lighter", {"base"}) == {"edits": [], "replaces": False}


def test_the_base_look_button_returns_to_the_sample():
    base = rcp.base_recipe(None, "light", "softglam", {"lips": "ruby"})
    st = _state(base, [["look", "evening"]])
    assert pipeline.plan_edit(st, "look", "softglam", {"base", "look:evening"}) == {"edits": [], "replaces": False}


def test_live_adds_edits_up_to_the_edge():
    base = rcp.look_recipe("light", "softglam")
    st = _state(base)
    for _ in range(50):
        plan = pipeline.plan_edit(st, "cheeks", "softer")
        if "edits" not in plan:
            break
        st = _state(base, plan["edits"])
    assert plan == {"reason": "softest"}
    assert st["recipe"]["zones"]["cheeks"]["intensity"] >= palettes.RANGES["light"]["cheeks"][0]


def test_plan_refuses_unknown_edits():
    with pytest.raises(ValueError):
        pipeline.plan_edit(_state(), "lips", "shade:nope")


# ---------------- the look on Replay ----------------
@pytest.fixture(scope="module")
def v2(tmp_path_factory):
    return make_v2_samples(tmp_path_factory.mktemp("samples"))


def _replay(sample_dir, tmp_path):
    eng = ReplayEngine(sample_dir)
    ctx = SessionCtx((sample_dir / "bride.jpg").read_bytes(), (sample_dir / "inspiration.jpg").read_bytes())
    return eng, ctx, pipeline.build_look(eng, ctx, tmp_path, order=eng.order())


@pytest.mark.parametrize(("sample", "before"), [("s0-champagne-rose", "base"), ("s3-mauve-smoky", "bride")])
def test_hero_and_after_are_the_recipe_render(v2, tmp_path, sample, before):
    _, _, st = _replay(v2 / sample, tmp_path)
    assert st["views"] == {"hero": "render", "before": before, "after": "render"}
    assert st["images"]["render"] == "render-base.png"
    assert set(st["views"].values()) <= set(st["images"]), "every view names an image of this session"


def test_an_edit_reaches_the_hero(v2, tmp_path):
    eng, ctx, st = _replay(v2 / "s3-mauve-smoky", tmp_path)
    st = pipeline.rerender(eng, ctx, tmp_path, st, [["look", "evening"]])
    assert st["images"][st["views"]["hero"]] == "render-look-evening.png"
    assert st["recipe"]["look"] == "evening"


def test_replay_session_lists_nine_shades_and_the_group(v2, tmp_path):
    _, _, st = _replay(v2 / "s3-mauve-smoky", tmp_path)
    assert len(st["shades"]) == 9 and st["recipe"]["group"] == "deep"
    assert "zone_strength" not in st


# ---------------- recording ----------------
PNG = io.BytesIO()
Image.new("RGB", (64, 64), (200, 120, 100)).save(PNG, format="PNG")


class FakeClient:
    """Answers tasks with a small PNG; counts what would be spent."""

    def __init__(self):
        self.tasks = []
        self.uploads = {}
        self.n = 0

    def upload(self, content, name, content_type="image/jpeg"):
        self.n += 1
        self.uploads[f"file-{self.n}"] = (name, content)
        return f"file-{self.n}"

    def run_task(self, name, body, version=None):
        self.tasks.append((name, body))
        return TaskResult(name, f"task-{len(self.tasks)}", "fake://x", 1.0, UNITS[name], {})

    def download(self, url):
        return PNG.getvalue()


def _copy_sample(src, dst):
    dst.mkdir(parents=True)
    (dst / "results").mkdir()
    (dst / "fixtures").mkdir()
    mf = json.loads((src / "manifest.json").read_text())
    for rec in mf["steps"].values():
        (dst / rec["image"]).write_bytes((src / rec["image"]).read_bytes())
    (dst / "manifest.json").write_text(json.dumps(mf))
    return dst


def _grid_engine(sd, max_units=100):
    client = FakeClient()
    return client, GridEngine(client, recorder=Recorder(sd), max_units=max_units)


def test_grid_engine_serves_what_is_recorded_for_free(tmp_path):
    sd = _copy_sample(SAMPLES / "s0-champagne-rose", tmp_path / "s0")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx(b"bride", b"insp")
    assert eng.hair_transfer(ctx, on="selfie").image == (sd / "results/hair_transfer.jpg").read_bytes()
    assert eng.makeup_transfer(ctx, on="base").meta.units == 0
    assert eng.even_out(ctx, "#dfa588").meta.units == 0
    assert client.tasks == [] and eng.spent == 0
    assert ctx.ids["mu_jpeg"] == (sd / "results/mu_transfer.jpg").read_bytes()


def test_grid_engine_renders_a_new_recipe_and_reuses_it_on_the_next_run(tmp_path):
    sd = _copy_sample(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx(b"bride", b"insp")
    r = rcp.look_recipe("deep", "softglam")
    assert eng.render(ctx, r, []).meta.units == 1 and eng.spent == 1
    assert eng.recorder.manifest["steps"]["render:base"]["recipe"] == r
    client2, eng2 = _grid_engine(sd)
    assert eng2.render(ctx, r, []).meta.units == 0
    assert client2.tasks == [] and eng2.spent == 0
    other = rcp.look_recipe("deep", "evening")
    assert eng2.render(ctx, other, []).meta.units == 1, "a changed recipe is rendered again"


def test_grid_engine_stops_before_the_ceiling(tmp_path):
    sd = _copy_sample(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd, max_units=1)
    ctx = SessionCtx(b"bride", b"insp")
    eng.render(ctx, rcp.look_recipe("deep", "softglam"), [])
    with pytest.raises(BudgetReached):
        eng.hair_transfer(ctx, on="render")
    assert len(client.tasks) == 1


def test_hair_runs_on_the_base_render_as_a_jpeg(tmp_path):
    client = FakeClient()
    eng = LiveEngine(client)
    ctx = SessionCtx(b"bride", b"insp")
    eng.render(ctx, rcp.look_recipe("deep", "softglam"), [])
    out = eng.hair_transfer(ctx, on="render")
    name, body = client.tasks[-1]
    assert name == "hair-transfer" and out.meta.label == hair_label(rcp.look_recipe("deep", "softglam"))
    uploaded_name, content = client.uploads[body["src_file_id"]]
    assert uploaded_name == "render.jpg" and content[:2] == b"\xff\xd8", "a PNG render, an upload declared JPEG"


def test_hair_on_a_render_needs_a_render_first():
    with pytest.raises(RuntimeError):
        LiveEngine(FakeClient()).hair_transfer(SessionCtx(b"", b""), on="render")


def test_grid_engine_redoes_hair_only_for_a_new_base(tmp_path):
    sd = _copy_sample(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx(b"bride", b"insp")
    r = rcp.look_recipe("deep", "softglam")
    eng.render(ctx, r, [])
    eng.hair_transfer(ctx, on="render")
    assert eng.spent == 1 + UNITS["hair-transfer"]
    client2, eng2 = _grid_engine(sd)
    ctx2 = SessionCtx(b"bride", b"insp")
    eng2.render(ctx2, r, [])
    eng2.hair_transfer(ctx2, on="render")
    assert client2.tasks == [], "same base render: the recorded hair stays"


def test_build_look_on_transfer_first_puts_the_hair_on_the_base_render(tmp_path):
    src = SAMPLES / "s3-mauve-smoky"
    sd = _copy_sample(src, tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx((src / "bride.jpg").read_bytes(), (src / "inspiration.jpg").read_bytes())
    st = pipeline.build_look(eng, ctx, tmp_path / "work", recorder=eng.recorder, order="transfer_first",
                             pins={"group": "deep", "look": "softglam", "shades": {}})
    assert [t[0] for t in client.tasks] == ["makeup-vto", "hair-transfer"], "render first, then hair on it"
    effects = client.tasks[0][1]["effects"]
    assert rcp.canonical(effects) == rcp.canonical(rcp.to_vto_effects(rcp.look_recipe("deep", "softglam")))
    assert st["recipe_base"]["group"] == "deep" and "hair" in st["images"]


def test_build_look_without_pins_picks_the_group_from_her_forehead(tmp_path):
    src = SAMPLES / "s3-mauve-smoky"
    sd = _copy_sample(src, tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx((src / "bride.jpg").read_bytes(), (src / "inspiration.jpg").read_bytes())
    st = pipeline.build_look(eng, ctx, tmp_path / "work", recorder=eng.recorder, order="transfer_first")
    assert st["recipe_base"]["group"] == "deep" and st["recipe_base"]["look"] == palettes.DEFAULT_LOOK


def test_pins_of_the_samples():
    for sid, group, shades in (("s0-champagne-rose", "light", {}), ("s2-classic-red", "light", {"lips": "ruby"}),
                               ("s3-mauve-smoky", "deep", {})):
        pins = json.loads((SAMPLES / sid / "sample.json").read_text())["recipe_pins"]
        assert pins == {"group": group, "look": "softglam", "shades": shades}, sid
