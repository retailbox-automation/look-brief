"""The look as data: what the hero shows, which buttons work and why, and how a sample's grid is recorded."""

import io
import json

import pytest
from helpers import SAMPLES, SKIN, make_v2_samples
from PIL import Image

from lookbrief import palettes, pipeline
from lookbrief import recipe as rcp
from lookbrief.engine import BudgetReached, GridEngine, LiveEngine, Recorder, ReplayEngine, SessionCtx, hair_label
from lookbrief.youcam import UNITS, TaskResult


def _look(group="light", look="softglam", shades=None):
    return rcp.look_recipe(group, look, SKIN[group], shades)


def _state(base=None, edits=None, quiet=()):
    base = base or _look()
    edits = edits or []
    return {"recipe_base": base, "edits": edits, "recipe": rcp.apply_edits(base, edits), "quiet_edits": list(quiet)}


def _options(state, keys=None):
    return {(o["zone"], o["op"]): o for o in pipeline.edit_options(state, keys)}


# ---------------- buttons ----------------
def test_a_zone_with_no_step_that_shows_offers_no_button_and_says_why():
    both = ["brows:shade:soft", "brows:shade:defined"]
    assert pipeline.no_choice_zones(_state(quiet=both)) == ["brows"]
    assert not [o for o in pipeline.edit_options(_state(quiet=both)) if o["zone"] == "brows"]
    assert pipeline.no_choice_zones(_state(quiet=both, base=_look(look="fresh"))) == ["brows"], "whatever the look"


def test_one_step_left_keeps_the_choice():
    st = _state(quiet=["brows:shade:soft"])
    assert pipeline.no_choice_zones(st) == [] and ("brows", "shade:defined") in _options(st)


def test_a_zone_without_circles_is_not_a_zone_without_a_choice():
    assert pipeline.no_choice_zones(_state()) == [] and "bronzer" not in pipeline.no_choice_zones(_state(quiet=["x"]))


def test_options_cover_looks_steps_and_every_circle():
    opts = _options(_state())
    assert {("look", k) for k in palettes.LOOK_IDS} <= set(opts)
    for z in palettes.ZONES:
        assert {(z, f"shade:{s.id}") for s in palettes.circles("light", z)} <= set(opts), z
        steps = {(z, op) for op in rcp.EDIT_OPS}
        assert (steps <= set(opts)) is (z in palettes.STEP_ZONES), z
    assert len(opts) == 3 + 6 + 34
    assert not [k for k in opts if k[0] == "bronzer"], "bronzer is no choice"


def test_no_finish_buttons_are_left():
    assert not [o for o in pipeline.edit_options(_state()) if o["op"].startswith("finish:")]


def test_lighter_and_deeper_are_not_offered():
    assert not {o["op"] for o in pipeline.edit_options(_state())} & {"lighter", "deeper"}


def test_a_circle_carries_what_the_sheet_draws():
    base = _look()
    opts = _options(_state(base))
    ruby = opts[("lips", "shade:ruby")]
    assert ruby["hex"] == "#B0102E" and ruby["name"] == "Ruby" and ruby["texture"] == "matte"
    assert ruby["selected"] is False and ruby["available"] is True
    now = opts[("lips", f"shade:{base['zones']['lips']['shade_id']}")]
    assert now["selected"] is True and now["available"] is False and now["reason"] == "current"
    eyes = opts[("eyes", f"shade:{base['zones']['eyes']['shade_id']}")]
    assert eyes["colors"] == ["#B9745F", "#5C342A"] and eyes["hex"] == "#B9745F"


def test_the_none_choice_has_no_colour():
    o = _options(_state(_look("deep")))[("highlight", "shade:none")]
    assert o["hex"] is None and o["colors"] == [] and o["name"] == "None" and o["available"] is True


def test_a_button_on_the_end_of_the_order_is_off_and_says_why():
    base = _look()
    nearest = palettes.skin_order("light", "lips", SKIN["light"])[0].id
    opts = _options(_state(base, [["lips", f"shade:{nearest}"]]))
    o = opts[("lips", "softer")]
    assert o["available"] is False and o["reason"] == "softest" and o["note"]
    assert opts[("lips", "bolder")]["available"] is True
    assert all(o.get("reason") != "light" for o in opts.values()), "the old reason is gone"


def test_the_softer_gate_of_the_old_rule_is_gone():
    assert not hasattr(pipeline, "softer_blocked")


def test_a_quiet_button_is_not_offered_and_the_server_refuses_it():
    base = _look()
    key = rcp.quiet_key(base, "lips", "softer")
    st = _state(base, quiet=[key, "lips:shade:ruby", "lashes:shade:volume"])
    opts = _options(st)
    assert ("lips", "softer") not in opts and ("lips", "bolder") in opts
    assert ("lips", "shade:ruby") not in opts and ("lips", "shade:nude-rose") in opts
    assert ("lashes", "shade:volume") not in opts and ("lashes", "shade:fluttery") in opts
    assert pipeline.plan_edit(st, "lips", "softer") == {"reason": "quiet"}
    assert pipeline.plan_edit(st, "lips", "shade:ruby") == {"reason": "quiet"}


def test_quiet_softer_depends_on_the_shade_she_wears():
    base = _look()
    key = rcp.quiet_key(base, "lips", "softer")
    st = _state(base, [["lips", "shade:ruby"]], quiet=[key])
    assert ("lips", "softer") in _options(st), "from another shade it is another step"


def test_replay_offers_only_what_is_recorded():
    base = _look()
    _, softer = rcp.resolve_edit(base, "lips", "softer")
    keys = {"base", f"lips:{softer}", "look:evening", "lips:shade:ruby"}
    opts = _options(_state(base), keys)
    assert opts[("lips", "softer")]["available"] and opts[("look", "evening")]["available"]
    assert opts[("lips", "shade:ruby")]["available"]
    assert not opts[("lips", "bolder")]["available"] and opts[("lips", "bolder")]["reason"] == "not_recorded"


def test_replay_keeps_every_zone_a_new_one_lands_on_top():
    base = _look()
    keys = {"base", "lips:shade:ruby", "cheeks:shade:peach"}
    st = _state(base, [["lips", "shade:ruby"]])
    plan = pipeline.plan_edit(st, "cheeks", "shade:peach", keys)
    assert plan == {"edits": [["lips", "shade:ruby"], ["cheeks", "shade:peach"]], "notice": ""}
    assert _options(st, keys)[("cheeks", "shade:peach")]["available"]


def test_a_choice_with_no_source_stays_not_recorded():
    base = _look()
    st = _state(base, [["lips", "shade:ruby"]])
    keys = {"base", "lips:shade:ruby"}
    assert pipeline.plan_edit(st, "cheeks", "shade:peach", keys) == {"reason": "not_recorded"}
    assert _options(st, keys)[("cheeks", "shade:peach")]["reason"] == "not_recorded"


def test_a_recorded_combination_is_kept():
    base = _look()
    st = _state(base, [["lips", "shade:ruby"]])
    keys = {"base", "lips:shade:ruby", "lips:shade:ruby+cheeks:shade:peach", "cheeks:shade:peach"}
    assert pipeline.plan_edit(st, "cheeks", "shade:peach", keys) == {
        "edits": [["lips", "shade:ruby"], ["cheeks", "shade:peach"]], "notice": ""}


def test_softer_is_stored_as_the_shade_and_needs_no_render_of_its_own():
    base = _look()
    _, softer = rcp.resolve_edit(base, "lips", "softer")
    plan = pipeline.plan_edit(_state(base), "lips", "softer", {"base", f"lips:{softer}"})
    assert plan == {"edits": [["lips", softer]], "notice": ""}


def test_softer_starts_from_the_shade_on_her_face_not_the_base():
    base = _look()
    st = _state(base, [["lips", "shade:ruby"]])
    expected = palettes.step_from("light", "lips", SKIN["light"], "ruby", "softer")
    assert expected != palettes.step_from("light", "lips", SKIN["light"], "dusty-rose", "softer")
    plan = pipeline.plan_edit(st, "lips", "softer", {"base", f"lips:shade:{expected}", "lips:shade:ruby"})
    assert plan["edits"] == [["lips", f"shade:{expected}"]]


def test_stepping_back_to_the_base_shade_is_the_base_render():
    base = _look()
    start = base["zones"]["lips"]["shade_id"]
    softer = palettes.step_from("light", "lips", SKIN["light"], start, "softer")
    assert palettes.step_from("light", "lips", SKIN["light"], softer, "bolder") == start
    st = _state(base, [["lips", f"shade:{softer}"]])
    assert pipeline.plan_edit(st, "lips", "bolder", {"base"}) == {"edits": [], "notice": ""}


def test_the_base_look_button_returns_to_the_sample():
    base = rcp.base_recipe(None, "light", SKIN["light"], "softglam", {"lips": "ruby"})
    st = _state(base, [["look", "evening"]])
    plan = pipeline.plan_edit(st, "look", "softglam", {"base", "look:evening"})
    assert plan == {"edits": [], "notice": ""}


EVENING = [["look", "evening"]]


def test_a_circle_on_another_look_stays_on_that_look():
    keys = {"base", "look:evening", "look:evening+eyes:shade:champagne", "eyes:shade:champagne"}
    plan = pipeline.plan_edit(_state(edits=EVENING), "eyes", "shade:champagne", keys)
    assert plan == {"edits": [*EVENING, ["eyes", "shade:champagne"]], "notice": ""}


def test_softer_on_another_look_stays_on_that_look():
    st = _state(edits=EVENING)
    op = rcp.resolve_edit(st["recipe"], "lips", "softer")[1]
    plan = pipeline.plan_edit(st, "lips", "softer", {"base", "look:evening", f"look:evening+lips:{op}"})
    assert plan == {"edits": [*EVENING, ["lips", op]], "notice": ""}


def test_a_second_zone_on_a_look_stacks_and_keeps_the_look():
    keys = {"base", "look:evening", "look:evening+eyes:shade:champagne", "look:evening+cheeks:shade:peach"}
    st = _state(edits=[*EVENING, ["eyes", "shade:champagne"]])
    assert pipeline.plan_edit(st, "cheeks", "shade:peach", keys) == {
        "edits": [*EVENING, ["eyes", "shade:champagne"], ["cheeks", "shade:peach"]], "notice": ""}


def test_a_style_on_another_look_stays_on_that_look():
    keys = {"base", "look:evening", "liner:shade:flick"}
    plan = pipeline.plan_edit(_state(edits=EVENING), "liner", "shade:flick", keys)
    assert plan == {"edits": [*EVENING, ["liner", "shade:flick"]], "notice": ""}


def test_a_look_over_a_zone_change_says_it_replaced_it():
    st = _state(edits=[["lips", "shade:ruby"]])
    plan = pipeline.plan_edit(st, "look", "evening", {"base", "look:evening", "lips:shade:ruby"})
    assert plan == {"edits": EVENING, "notice": "look"}


def test_a_quiet_circle_is_quiet_on_its_own_look_only():
    quiet = ["look:evening+lips:shade:warm-rose"]
    assert ("lips", "shade:warm-rose") not in _options(_state(edits=EVENING, quiet=quiet))
    assert ("lips", "shade:warm-rose") in _options(_state(quiet=quiet))


def test_a_quiet_step_names_its_look():
    st = _state(edits=EVENING, quiet=["look:evening+lips:softer@ruby"])
    assert ("lips", "softer") not in _options(st)
    assert ("lips", "softer") in _options(_state(edits=[["look", "fresh"]], quiet=["look:evening+lips:softer@ruby"]))


def test_a_style_quiet_on_the_base_look_is_quiet_everywhere():
    assert ("lashes", "shade:fluttery") not in _options(_state(edits=EVENING, quiet=["lashes:shade:fluttery"]))


def test_live_walks_softer_to_the_end_of_the_order():
    base = _look()
    st = _state(base)
    for _ in range(50):
        plan = pipeline.plan_edit(st, "cheeks", "softer")
        if "edits" not in plan:
            break
        st = _state(base, plan["edits"])
    assert plan == {"reason": "softest"}
    assert st["recipe"]["zones"]["cheeks"]["shade_id"] in {s.id for s in palettes.ladder("light", "cheeks")}


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


def test_replay_session_reads_the_quiet_list_of_the_sample(v2, tmp_path):
    sd = v2 / "s3-mauve-smoky"
    mf = json.loads((sd / "manifest.json").read_text())
    (sd / "manifest.json").write_text(json.dumps({**mf, "quiet_edits": ["lips:shade:plum"]}))
    try:
        _, _, st = _replay(sd, tmp_path)
    finally:
        (sd / "manifest.json").write_text(json.dumps(mf))
    assert st["quiet_edits"] == ["lips:shade:plum"]


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


def _before_the_grid(src, dst):
    """A copy of the sample with no render on the current recipe: the real one may be recorded by now."""
    sd = _copy_sample(src, dst)
    mf = json.loads((sd / "manifest.json").read_text())
    mf["steps"] = {k: v for k, v in mf["steps"].items() if not k.startswith("render:")}
    mf["steps"]["hair_transfer"]["label"] = ""
    (sd / "manifest.json").write_text(json.dumps(mf))
    return sd


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
    sd = _before_the_grid(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx(b"bride", b"insp")
    r = _look("deep")
    assert eng.render(ctx, r, []).meta.units == 1 and eng.spent == 1
    assert eng.recorder.manifest["steps"]["render:base"]["recipe"] == r
    client2, eng2 = _grid_engine(sd)
    assert eng2.render(ctx, r, []).meta.units == 0
    assert client2.tasks == [] and eng2.spent == 0
    other = _look("deep", "evening")
    assert eng2.render(ctx, other, []).meta.units == 1, "a changed recipe is rendered again"


def test_grid_engine_stops_before_the_ceiling(tmp_path):
    sd = _before_the_grid(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd, max_units=1)
    ctx = SessionCtx(b"bride", b"insp")
    eng.render(ctx, _look("deep"), [])
    with pytest.raises(BudgetReached):
        eng.hair_transfer(ctx, on="render")
    assert len(client.tasks) == 1


def test_hair_runs_on_the_base_render_as_a_jpeg(tmp_path):
    client = FakeClient()
    eng = LiveEngine(client)
    ctx = SessionCtx(b"bride", b"insp")
    eng.render(ctx, _look("deep"), [])
    out = eng.hair_transfer(ctx, on="render")
    name, body = client.tasks[-1]
    assert name == "hair-transfer" and out.meta.label == hair_label(_look("deep"))
    uploaded_name, content = client.uploads[body["src_file_id"]]
    assert uploaded_name == "render.jpg" and content[:2] == b"\xff\xd8", "a PNG render, an upload declared JPEG"


def test_hair_on_a_render_needs_a_render_first():
    with pytest.raises(RuntimeError):
        LiveEngine(FakeClient()).hair_transfer(SessionCtx(b"", b""), on="render")


def test_grid_engine_redoes_hair_only_for_a_new_base(tmp_path):
    sd = _before_the_grid(SAMPLES / "s3-mauve-smoky", tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx(b"bride", b"insp")
    r = _look("deep")
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
    sd = _before_the_grid(src, tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx((src / "bride.jpg").read_bytes(), (src / "inspiration.jpg").read_bytes())
    st = pipeline.build_look(eng, ctx, tmp_path / "work", recorder=eng.recorder, order="transfer_first",
                             pins={"group": "deep", "look": "softglam", "shades": {}, "skin_hex": SKIN["deep"]})
    assert [t[0] for t in client.tasks] == ["makeup-vto", "hair-transfer"], "render first, then hair on it"
    effects = client.tasks[0][1]["effects"]
    assert rcp.canonical(effects) == rcp.canonical(rcp.to_vto_effects(_look("deep")))
    assert st["recipe_base"]["group"] == "deep" and "hair" in st["images"]


def test_pins_can_fix_her_skin_so_a_dry_run_and_a_real_run_plan_one_recipe(tmp_path):
    src = SAMPLES / "s3-mauve-smoky"
    sd = _copy_sample(src, tmp_path / "s3")
    _, eng = _grid_engine(sd)
    ctx = SessionCtx((src / "bride.jpg").read_bytes(), (src / "inspiration.jpg").read_bytes())
    st = pipeline.build_look(eng, ctx, tmp_path / "work", recorder=eng.recorder, order="transfer_first",
                             pins={"group": "deep", "look": "softglam", "shades": {}, "skin_hex": "#bb8866"})
    assert st["recipe_base"]["skin_hex"] == "#bb8866"


def test_build_look_without_pins_picks_the_group_from_her_forehead(tmp_path):
    src = SAMPLES / "s3-mauve-smoky"
    sd = _copy_sample(src, tmp_path / "s3")
    client, eng = _grid_engine(sd)
    ctx = SessionCtx((src / "bride.jpg").read_bytes(), (src / "inspiration.jpg").read_bytes())
    st = pipeline.build_look(eng, ctx, tmp_path / "work", recorder=eng.recorder, order="transfer_first")
    assert st["recipe_base"]["group"] == "deep" and st["recipe_base"]["look"] == palettes.DEFAULT_LOOK
    assert st["recipe_base"]["skin_hex"] == st["recipe"]["skin_hex"] == "#be8567", "the forehead of the photo"


def test_pins_of_the_samples():
    for sid, group, shades in (("s0-champagne-rose", "light", {}), ("s2-classic-red", "medium", {}),
                               ("s3-mauve-smoky", "deep", {})):
        pins = json.loads((SAMPLES / sid / "sample.json").read_text())["recipe_pins"]
        assert pins == {"group": group, "look": "softglam", "shades": shades}, sid
