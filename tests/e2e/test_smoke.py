"""Browser smoke of the whole guided path on Replay: bride -> look -> edit -> brief -> artist -> agreement card.
Mobile viewport; axe-core WCAG 2 A/AA on every screen. Optional: LOOKBRIEF_RECORD_DIR records one video
per page (used for the demo footage). Buttons are read from the session's edit_options: a sample's quiet list decides
which ones exist."""

import json
import os
import re
import time
from pathlib import Path

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import expect, sync_playwright

from lookbrief import palettes

SAMPLES = Path(os.environ.get("LOOKBRIEF_SAMPLES", Path(__file__).resolve().parents[2] / "samples"))


def recorded(sample: str) -> bool:
    """The sample holds its grid on the current recipe (two-colour lids on 2colors279)."""
    steps = json.loads((SAMPLES / sample / "manifest.json").read_text())["steps"]
    eyes = steps["render:base"]["recipe"].get("zones", {}).get("eyes", {})
    return "render:look:evening" in steps and eyes.get("pattern") == "2colors279"


def needs(sample: str):
    return pytest.mark.skipif(not recorded(sample), reason=f"{sample} waits for re-recording")


pytestmark = pytest.mark.e2e
AXE = Axe()
REPLACED = "Updated. Samples hold one recorded change at a time — this replaced your previous change."
UP_TO_DATE = "Your brief is already up to date — no new edits."
HERO_ON_SCREEN_JS = "() => { const r = document.getElementById('img-hero').getBoundingClientRect(); " \
    "return r.height > 0 && r.bottom > 0 && r.top < innerHeight; }"
WCAG = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}}
LABEL = {"eyes": "Eyelids", "lips": "Lips", "cheeks": "Cheeks", "brows": "Brows"}


def check_a11y(page, where: str):
    res = AXE.run(page, options=WCAG)
    assert res.violations_count == 0, f"{where}: {res.generate_report()}"


@pytest.fixture
def browser_ctx():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        kw = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}
        if os.environ.get("LOOKBRIEF_RECORD_DIR"):
            kw["record_video_dir"] = os.environ["LOOKBRIEF_RECORD_DIR"]
            kw["record_video_size"] = {"width": 780, "height": 1688}
        ctx = browser.new_context(**kw)
        yield ctx
        ctx.close()
        browser.close()


def state_of(page) -> dict:
    sid = page.url.rsplit("/", 1)[1]
    return page.evaluate(f"async () => (await fetch('/api/sessions/{sid}')).json()")


def circles(page, zone: str) -> list[dict]:
    """The circles of a zone she can tap now, the most different from the base last in the ladder order."""
    return [o for o in state_of(page)["edit_options"] if o["zone"] == zone and o["op"].startswith("shade:")
            and o["available"] and o["colors"]]


def open_zone(page, zone: str) -> None:
    page.get_by_role("button", name=LABEL[zone], exact=True).click()


def tap_circle(page, opt: dict) -> None:
    page.get_by_role("button", name=f"{LABEL[opt['zone']]}: {opt['name']}", exact=True).click()


def render_name(opt: dict) -> str:
    return f"render-{opt['zone']}-{opt['op'].replace(':', '-')}"


@needs("s0-champagne-rose")
def test_guided_path_both_roles(base_url, browser_ctx):
    t0 = time.monotonic()
    page = browser_ctx.new_page()
    page.goto(base_url + "/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("before you pay for the trial")
    check_a11y(page, "home")

    page.locator("[data-testid^=sample-]").first.click()
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("mode-badge")).to_have_text("Replay · recorded real YouCam API results")
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-base"))
    expect(page.locator("#img-after")).to_have_attribute("src", re.compile(r"render-base"))
    expect(page.locator("#cap-after")).to_contain_text("Recorded real YouCam API result")
    expect(page.locator(".zone")).to_have_count(9)
    expect(page.locator("#gaps tbody tr")).to_have_count(3)
    check_a11y(page, "your look")

    # another look: the whole recipe changes, and the first look is one tap back
    page.get_by_role("button", name="Evening", exact=True).click()
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-look-evening"), timeout=20_000)
    expect(page.get_by_role("button", name="Evening", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("hero-caption")).to_contain_text("Your look, rendered by Makeup VTO")
    page.get_by_role("button", name="Soft glam", exact=True).click()
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-base"), timeout=20_000)

    open_zone(page, "lips")
    first = circles(page, "lips")[0]
    tap_circle(page, first)
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(render_name(first)))
    expect(page.get_by_test_id("shade-lips")).to_contain_text(first["name"])
    open_zone(page, "eyes")
    second = circles(page, "eyes")[0]
    tap_circle(page, second)  # a change in another zone replaces the first: one recorded change at a time
    expect(page.locator("#edit-msg")).to_have_text(REPLACED, timeout=20_000)
    expect(page.locator("#img-after")).to_have_attribute("src", re.compile(render_name(second)))

    page.get_by_role("button", name="Send brief to my makeup artist").click()
    expect(page.get_by_test_id("artist-link")).to_have_attribute("href", re.compile(r"^/b/"))
    artist_url = page.get_by_test_id("artist-link").get_attribute("href")
    bride_url = page.get_by_test_id("bride-link").get_attribute("href")
    assert artist_url and bride_url and artist_url != bride_url

    # the bride opens her link before the artist answered: she is told what she is waiting for, and she sees
    # her look as the agreed target, with visible captions
    bride = browser_ctx.new_page()
    bride.goto(base_url + bride_url)
    expect(bride.locator("#agree-help")).to_have_text("Waiting for your makeup artist to answer every zone.")
    expect(bride.locator("#b-after")).to_have_attribute("src", re.compile(render_name(second)))
    expect(bride.locator("#b-after-cap")).to_contain_text("Agreed look: your recipe")
    for cap in bride.locator(".pair-photos figcaption").all():  # on screen, not screen-reader-only (1px)
        box = cap.bounding_box()
        assert box and box["width"] > 40 and box["height"] > 8, f"caption not visible: {box}"
    bride.get_by_role("button", name="Update the brief from my latest edits").click()
    waiting = "Waiting for your makeup artist to answer every zone."
    expect(bride.locator("#agree-help")).to_have_text(f"{waiting} {UP_TO_DATE}")
    expect(bride.locator("#b-status")).to_contain_text("Version 1")

    artist = browser_ctx.new_page()
    artist.goto(base_url + artist_url)
    expect(artist.get_by_text("For your makeup artist · no account needed")).to_be_visible()
    reviews = artist.locator("fieldset.review")
    expect(reviews).to_have_count(10)  # eight zones of the recipe (no highlighter in the base), the hair, the skin
    snap = artist.request.get(base_url + artist_url.replace("/b/", "/api/briefs/")).json()["snapshot"]
    cheeks = next(z for z in snap["zones"] if z["zone"] == "cheeks")
    expect(artist.get_by_test_id("review-cheeks")).to_contain_text(cheeks["product_hex"])
    expect(artist.get_by_test_id("review-cheeks")).to_contain_text(cheeks["shade_name"])
    expect(artist.get_by_test_id("review-skin")).to_contain_text("Concealer in her own shade")
    for i in range(reviews.count()):
        fs = reviews.nth(i)
        is_cheeks = fs.get_attribute("data-testid") == "review-cheeks"
        fs.get_by_label("I'll swap the product" if is_cheeks else "I'll do this").check()
    artist.locator("input[name=note-cheeks]").fill("I'll use a cooler pink")
    artist.locator("input[name=note-cheeks]").press("Tab")
    check_a11y(artist, "artist brief")
    expect(artist.get_by_role("button", name="Agree to this look")).to_be_enabled(timeout=10_000)
    artist.get_by_role("button", name="Agree to this look").click()
    expect(artist.locator("#agree-help")).to_contain_text("Waiting for the bride")

    bride.clock.install()  # to run the 8 s poll on demand
    bride.goto(base_url + bride_url)
    expect(bride.locator("#agree-help")).to_contain_text("The artist agreed")
    bride.clock.run_for(7_500)
    bride.get_by_role("button", name="Update the brief from my latest edits").click()
    help_text = re.compile(r"The artist agreed ✓ · waiting for you\. " + re.escape(UP_TO_DATE))
    expect(bride.locator("#agree-help")).to_have_text(help_text)
    with bride.expect_response(lambda r: "/api/briefs/" in r.url and r.request.method == "GET"):
        bride.clock.run_for(1_000)  # the poll fires within a second of the click
    bride.wait_for_timeout(300)
    expect(bride.locator("#agree-help")).to_have_text(help_text)
    bride.get_by_role("button", name="Agree to this look").click()
    expect(bride.locator("#agree-help")).to_contain_text("signed by the server")
    bride.locator("#card-a").click()
    expect(bride.get_by_role("heading", name="Server-attested agreement")).to_be_visible()
    expect(bride.get_by_text("I'll use a cooler pink")).to_be_visible()
    check_a11y(bride, "agreed-look card")
    assert time.monotonic() - t0 < 90, "the guided path must fit in 90 seconds"


@needs("s0-champagne-rose")
def test_hair_first_sample_by_link(base_url, browser_ctx):
    """The heroine sample: the render of her recipe wears the new hair, so no hair toggle is needed."""
    import urllib.request

    assert "s0-champagne-rose" in json.load(urllib.request.urlopen(base_url + "/healthz"))["samples"]
    page = browser_ctx.new_page()
    page.goto(base_url + "/")
    page.get_by_test_id("sample-s0-champagne-rose").click()  # the way a visitor opens it: from the home page
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    expect(page.locator("#hero-toggle")).to_be_hidden()
    expect(page.get_by_test_id("hero-caption")).to_contain_text("Your look, rendered by Makeup VTO")
    expect(page.get_by_test_id("hero-caption")).to_contain_text("Recorded real YouCam API result")
    expect(page.locator("#img-before")).to_have_attribute("src", re.compile(r"/base\."))
    body = page.locator("body").inner_text()
    assert "Even out" not in body and "transferred look" not in body, "the recipe is the main path"
    assert "foundation" not in body.lower(), "no render carries one"
    # an iPhone status bar: the page keeps a safe-area padding at the top (Chromium has none, so fake one)
    page.evaluate("document.body.style.paddingTop = '47px'")
    open_zone(page, "eyes")
    opt = circles(page, "eyes")[-1]
    btn = page.get_by_role("button", name=f"Eyelids: {opt['name']}", exact=True)
    # on a phone she scrolls down to the circles to press a change: the photo leaves the screen
    btn.evaluate("el => el.scrollIntoView({block: 'start'})")
    assert not page.evaluate(HERO_ON_SCREEN_JS), "precondition: the photo is above the viewport"
    btn.click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.wait_for_function(HERO_ON_SCREEN_JS, timeout=5_000)  # 390x844: the change itself is on screen
    # scrolled to the top of the look, so the pills on the photo are on screen (not to the photo's top edge, which
    # iPhone Safari puts under the status bar)
    page.wait_for_function("scrollY < 1 && document.getElementById('look').getBoundingClientRect().top >= 46",
                           timeout=5_000)  # nothing of the look under the 47 px "status bar"
    page.evaluate("document.body.style.paddingTop = ''")
    expect(page.locator("#reset")).to_have_text("Back to my look")
    # the caption names a part of the task id that differs between renders; the full id is in the title
    steps = state_of(page)["steps"]
    edited, base = steps[f"render:eyes:{opt['op']}"]["task_id"], steps["render:base"]["task_id"]
    assert task_fragment(edited) != task_fragment(base), (edited, base)
    expect(page.get_by_test_id("hero-caption")).to_contain_text(f"task {task_fragment(edited)}")
    expect(page.get_by_test_id("hero-caption")).to_have_attribute("title", f"YouCam task {edited}")
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(render_name(opt)))
    for width, height in ((390, 844), (1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        assert_caption_clear(page, width)
    check_a11y(page, "hair-first look")
    # sending the same look twice keeps the links; a changed look gets new links and a fresh Copy button
    send, copy, link = (page.get_by_role("button", name="Send brief to my makeup artist"),
                        page.locator('[data-copy="artist-link"]'), page.get_by_test_id("artist-link"))
    send.click()
    expect(link).to_have_attribute("href", re.compile(r"^/b/"))
    first = link.get_attribute("href")
    copy.click()
    expect(copy).to_have_text("Copied")
    send.click()
    page.wait_for_load_state("networkidle")
    assert link.get_attribute("href") == first
    page.get_by_role("button", name="Undo last change").click()
    expect(page.locator("#edit-msg")).to_have_text("Undone.", timeout=20_000)
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-base"))
    send.click()
    expect(link).not_to_have_attribute("href", first)
    expect(copy).to_have_text("Copy")
    # hair first has no "hair" image: the Hair Transfer on her selfie is shown as the hair, here and in the brief
    page.get_by_text("How we read your inspiration").click()
    assert page.evaluate("document.getElementById('img-hair').naturalWidth") > 0
    expect(page.locator("#cap-hair")).to_contain_text("Hair (YouCam Hair Transfer on your selfie)")
    expect(page.locator("#cap-look")).to_contain_text("Inspiration read by Makeup Transfer")
    bride = browser_ctx.new_page()
    bride.goto(base_url + page.get_by_test_id("bride-link").get_attribute("href"))
    expect(bride.get_by_test_id("review-hair")).to_contain_text(
        "Hair as in the agreed look photo above (YouCam Hair Transfer)")
    bride.get_by_text("Inspiration photo and hair preview").click()
    expect(bride.locator("#b-hair-cap")).to_have_text("Hair (YouCam Hair Transfer on her selfie)")
    bride.wait_for_function("document.getElementById('b-hair').naturalWidth > 0", timeout=5_000)
    expect(bride.locator("#b-hair")).to_be_visible()
    # back to her look after a change
    open_zone(page, "eyes")
    tap_circle(page, opt)
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.get_by_role("button", name="Back to my look").click()
    expect(page.locator("#edit-msg")).to_have_text("Back to your look.", timeout=20_000)


def task_fragment(task_id: str) -> str:
    """The part of a YouCam task id the captions show (session.js taskFragment)."""
    return f"{task_id[:4]}…{task_id[-30:-22]}" if len(task_id) >= 40 else f"{task_id[:10]}…"


TOUCH_JS = """() => {
  const small = [...document.querySelectorAll('.look-btn, .tab, .circle, .chip')]
    .filter((b) => { const r = b.getBoundingClientRect(); return r.width > 0 && (r.height < 44 || r.width < 44); })
    .map((b) => [b.textContent, b.getBoundingClientRect().width, b.getBoundingClientRect().height]);
  const cut = [...document.querySelectorAll('.look-btn, .tab, .chip, .circle-name')]
    .filter((b) => b.getClientRects().length && b.scrollWidth > b.clientWidth + 1).map((b) => b.textContent);
  return {small, cut, overflow: document.documentElement.scrollWidth - innerWidth};
}"""


@needs("s0-champagne-rose")
@pytest.mark.parametrize(("width", "height"), [(320, 640), (390, 844)])
def test_every_zone_fits_a_phone_with_targets_of_44_px(base_url, browser_ctx, width, height):
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    tabs = page.locator(".tab")
    expect(tabs).to_have_count(9)
    for i in range(tabs.count()):
        tabs.nth(i).click()  # the row scrolls sideways: every tab is reachable and stays in view when chosen
        box = tabs.nth(i).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, (i, box)
        m = page.evaluate(TOUCH_JS)
        assert not m["small"] and not m["cut"] and m["overflow"] <= 0, (tabs.nth(i).text_content(), m)


@needs("s0-champagne-rose")
def test_a_button_at_the_end_of_its_way_is_off_says_why_and_sends_nothing(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    nearest = palettes.skin_order("light", "lips", "#dfa588")[0]  # the start of her way: nothing softer in this family
    open_zone(page, "lips")
    page.get_by_role("button", name=f"Lips: {nearest.name}", exact=True).click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    opt = next(o for o in state_of(page)["edit_options"] if (o["zone"], o["op"]) == ("lips", "softer"))
    assert opt["reason"] == "softest"
    btn = page.get_by_role("button", name="Lips: softer", exact=True)
    expect(btn).to_be_disabled()
    expect(page.get_by_test_id("note-lips")).to_have_text(opt["note"])
    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    btn.click(force=True)
    page.wait_for_timeout(300)
    assert not [u for u in sent if "/edits" in u], sent


ZOOM_JS = """() => {
  const img = document.getElementById("hero-img"), frame = document.querySelector(".hero-frame");
  const m = new DOMMatrix(getComputedStyle(img).transform);
  const a = img.getBoundingClientRect(), f = frame.getBoundingClientRect();
  return {scale: m.a, covers: a.left <= f.left + 0.5 && a.top <= f.top + 0.5 && a.right >= f.right - 0.5
          && a.bottom >= f.bottom - 0.5, clipped: getComputedStyle(frame).overflow === "hidden",
          whole: !document.getElementById("whole-btn").hidden};
}"""


def eye_span(page) -> tuple[float, float]:
    """Left and right of the eye outlines, in shares of the photo's width."""
    xs = [p[0] for poly in state_of(page)["outlines"]["eyes"] for p in poly]
    return min(xs), max(xs)


def fitted(page) -> float:
    left, right = eye_span(page)
    return min(2.3, 1 / ((right - left) * 1.15))


def zoom_settled(page, scale: float) -> dict:
    page.wait_for_function(f"Math.abs(new DOMMatrix(getComputedStyle(document.getElementById('hero-img')).transform).a"
                           f" - {scale}) < 0.01", timeout=3_000)
    return page.evaluate(ZOOM_JS)


@needs("s0-champagne-rose")
@pytest.mark.parametrize(("width", "height"), [(390, 844), (1440, 900)])
def test_a_zone_brings_the_photo_close_and_whole_face_takes_it_back(base_url, browser_ctx, width, height):
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    assert page.evaluate(ZOOM_JS)["scale"] == 1 and not page.evaluate(ZOOM_JS)["whole"], "the whole face first"
    sheet_top = page.locator(".sheet").bounding_box()["y"]
    eyes = fitted(page)
    for label, scale in (("Eyelids", eyes), ("Eyeliner", eyes), ("Lashes", eyes), ("Brows", eyes), ("Lips", 2.3),
                         ("Lip liner", 2.3), ("Cheeks", 1.5), ("Bronzer", 1.5), ("Highlighter", 1.5)):
        page.get_by_role("button", name=label, exact=True).click()
        m = zoom_settled(page, scale)
        assert m["covers"] and m["clipped"] and m["whole"], (label, m)
    assert page.locator(".sheet").bounding_box()["y"] == sheet_top, "what is under the photo stays in place"
    page.get_by_role("button", name="Whole face", exact=True).click()
    assert zoom_settled(page, 1)["whole"] is False
    # a look shows on the whole face, wherever she was
    page.get_by_role("button", name="Lips", exact=True).click()
    zoom_settled(page, 2.3)
    page.get_by_role("button", name="Evening", exact=True).click()
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-look-evening"), timeout=20_000)
    assert zoom_settled(page, 1)["whole"] is False
    # an edit keeps the zone close: that is where the change is
    page.get_by_role("button", name="Soft glam", exact=True).click()
    page.get_by_role("button", name="Lips", exact=True).click()
    tap_circle(page, circles(page, "lips")[0])
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    zoom_settled(page, 2.3)
    transform = page.locator("#img-after").evaluate("el => getComputedStyle(el.parentElement).transform")
    assert transform == "none", "before and after stays the whole face"


@pytest.mark.parametrize("sample", ["s0-champagne-rose", "s2-classic-red", "s3-mauve-smoky"])
def test_the_close_up_of_the_eyes_keeps_both_outer_corners_in_the_frame(base_url, browser_ctx, sample):
    page = browser_ctx.new_page()
    page.goto(f"{base_url}/try/{sample}")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    scale = fitted(page)
    page.get_by_role("button", name="Eyelids", exact=True).click()
    zoom_settled(page, scale)
    shift = page.evaluate("""() => new DOMMatrix(getComputedStyle(document.getElementById("hero-img")).transform).e
                                   / document.querySelector(".hero-frame").clientWidth""")
    left, right = (x * scale + shift for x in eye_span(page))
    assert scale <= 2.3 and 0 <= left < right <= 1, (sample, scale, left, right)
    page.close()


@needs("s0-champagne-rose")
def test_a_circle_on_evening_stays_on_evening_and_undo_keeps_it(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    hero, evening = page.locator("#img-hero"), page.get_by_role("button", name="Evening", exact=True)
    evening.click()
    expect(hero).to_have_attribute("src", re.compile(r"render-look-evening\."), timeout=20_000)
    open_zone(page, "eyes")
    tap_circle(page, circles(page, "eyes")[0])
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    expect(hero).to_have_attribute("src", re.compile(r"render-look-evening_eyes-shade-"))
    expect(evening).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Undo last change").click()
    expect(page.locator("#edit-msg")).to_have_text("Undone.", timeout=20_000)
    expect(hero).to_have_attribute("src", re.compile(r"render-look-evening\."))
    expect(evening).to_have_attribute("aria-pressed", "true")
    page.close()


@needs("s0-champagne-rose")
def test_a_style_on_evening_moves_to_soft_glam_says_so_and_undo_comes_back(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    evening = page.get_by_role("button", name="Evening", exact=True)
    evening.click()
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-look-evening\."), timeout=20_000)
    page.get_by_role("button", name="Eyeliner", exact=True).click()
    page.get_by_role("button", name="Eyeliner: Flick", exact=True).click()
    expect(page.locator("#edit-msg")).to_have_text("Styles are recorded on Soft glam, so your look moved to Soft glam.",
                                                   timeout=20_000)
    expect(page.get_by_role("button", name="Soft glam", exact=True)).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Undo last change").click()
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-look-evening\."), timeout=20_000)
    expect(evening).to_have_attribute("aria-pressed", "true")
    page.close()


@needs("s0-champagne-rose")
def test_a_look_over_a_zone_change_says_it_replaced_it(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    open_zone(page, "lips")
    tap_circle(page, circles(page, "lips")[0])
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.get_by_role("button", name="Classic", exact=True).click()
    expect(page.locator("#edit-msg")).to_have_text("This look replaces your earlier change.", timeout=20_000)
    page.close()


@needs("s0-champagne-rose")
def test_a_change_made_low_on_the_page_brings_the_close_up_back_on_screen(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": 390, "height": 664})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Eyelids", exact=True).click()
    page.evaluate("window.scrollTo(0, 300)")
    seen = page.evaluate("""() => { const f = document.querySelector(".hero-frame").getBoundingClientRect();
                                    return [f.bottom, f.height]; }""")
    assert seen[0] < seen[1] / 2, "less than half of the frame is on screen, whatever the scaled photo measures"
    page.get_by_role("button", name="Eyelids: bolder", exact=True).click()
    page.wait_for_function("scrollY === 0", timeout=5_000)
    page.close()


@needs("s0-champagne-rose")
def test_undo_low_on_the_page_brings_the_photo_back_on_screen(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": 390, "height": 664})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Evening", exact=True).click()
    expect(page.locator("#edit-msg")).not_to_have_text("One moment…", timeout=20_000)
    undo = page.locator("#undo")
    undo.scroll_into_view_if_needed()
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    undo.scroll_into_view_if_needed()
    assert page.evaluate("scrollY") > 300, "the setup puts the photo off the screen"
    undo.click()
    page.wait_for_function("scrollY === 0", timeout=5_000)
    page.close()


@needs("s0-champagne-rose")
def test_a_step_that_takes_its_own_button_away_keeps_the_photo_where_it_was(base_url, browser_ctx):
    """Focus falls to Undo, below the fold, when the pressed button goes: that used to scroll the photo away."""
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    open_zone(page, "lips")
    softer = page.get_by_role("button", name="Lips: softer", exact=True)
    softer.evaluate("b => window.scrollTo(0, b.getBoundingClientRect().bottom + scrollY - innerHeight + 4)")
    before = page.evaluate("scrollY")
    seen = """(() => { const f = document.querySelector('.hero-frame').getBoundingClientRect();
                       return Math.min(f.bottom, innerHeight) - Math.max(f.top, 0); })()"""
    height = page.evaluate("document.querySelector('.hero-frame').offsetHeight")
    assert page.evaluate(seen) > height / 2, "the photo starts on screen"
    softer.click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.wait_for_timeout(400)
    opt = [o for o in state_of(page)["edit_options"] if (o["zone"], o["op"]) == ("lips", "softer") and o["available"]]
    assert not opt, "the setup: this tap leaves no softer step"
    assert page.evaluate("scrollY") <= before and page.evaluate(seen) > 0
    page.close()


NO_NETWORK = "We could not reach the server. Check your connection and try again."


@needs("s0-champagne-rose")
def test_a_lost_connection_says_so_and_the_buttons_work_again(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    open_zone(page, "lips")
    first = circles(page, "lips")[0]
    page.route("**/edits", lambda route: route.abort())
    tap_circle(page, first)
    expect(page.locator("#edit-msg")).to_have_text(NO_NETWORK, timeout=5_000)
    page.unroute("**/edits")
    tap_circle(page, first)
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(render_name(first)))
    page.close()


@needs("s0-champagne-rose")
def test_the_first_load_keeps_trying_after_a_lost_connection(base_url, browser_ctx):
    dropped = []

    def flaky(route):
        if route.request.method == "GET" and len(dropped) < 2:
            dropped.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    page = browser_ctx.new_page()
    page.route(re.compile(r"/api/sessions/[^/]+$"), flaky)
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    assert len(dropped) == 2
    page.close()


@needs("s0-champagne-rose")
def test_zoom_is_a_jump_for_those_who_ask_for_less_motion(base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base_url + "/try/s0-champagne-rose")
        expect(page.locator("#look")).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Lips", exact=True).click()
        scale = page.evaluate("new DOMMatrix(getComputedStyle(document.getElementById('hero-img')).transform).a")
        assert scale == pytest.approx(2.3, abs=0.01)
        browser.close()


@needs("s0-champagne-rose")
def test_named_styles_are_chips_in_thin_zones(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Eyeliner", exact=True).click()
    zone = page.get_by_test_id("zone-liner")
    expect(zone.locator(".styles .chip").first).to_be_visible()
    assert zone.locator(".circle").count() == 0 and zone.locator(".chips").count() == 0, "no circles, no Softer"
    expect(zone.get_by_role("button", name="Eyeliner: Classic", exact=True)).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Bronzer", exact=True).click()
    expect(page.get_by_test_id("note-bronzer")).to_have_text("A light warm layer is part of this look.")
    assert page.get_by_test_id("zone-bronzer").locator("button").count() == 0, "bronzer is part of the look"


@needs("s0-champagne-rose")
@pytest.mark.parametrize(("width", "height"), [(320, 568), (320, 460), (390, 844), (390, 664)])
def test_the_three_looks_are_on_the_first_screen(base_url, browser_ctx, width, height):
    page = browser_ctx.new_page()
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    buttons = page.locator(".look-btn")
    expect(buttons).to_have_text(["Classic", "Soft glam", "Evening"])
    expect(page.get_by_role("button", name="Soft glam", exact=True)).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("scrollY") == 0
    for box in (buttons.nth(i).bounding_box() for i in range(3)):
        assert box["x"] >= 0 and box["x"] + box["width"] <= width and box["y"] + box["height"] <= height, box
    page.close()


def test_details_keep_the_numbers_out_of_the_sheet(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s0-champagne-rose")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    sheet = page.locator(".sheet").inner_text()
    assert "ΔE" not in sheet and "Coverage" not in sheet and not re.search(r"#[0-9A-Fa-f]{6}", sheet), sheet
    page.get_by_text("The numbers behind your look").click()
    expect(page.locator("#zone-numbers tbody tr")).to_have_count(len(state_of(page)["shades"]))
    page.get_by_text("How far is the recipe from your inspiration?").click()
    expect(page.locator("#gaps tbody tr")).to_have_count(3)
    assert re.search(r"\d\.\d", page.locator("#gaps tbody").inner_text()), "the numbers stay on the page"


CAPTION_LAYOUT_JS = """() => {
  const box = (el) => el && !el.hidden ? el.getBoundingClientRect() : null;
  const cap = document.getElementById("hero-cap");
  const range = document.createRange(); range.selectNodeContents(cap);
  const text = range.getBoundingClientRect();
  const over = ["hero-toggle", "hero-check", "zones-btn"].map((id) => box(document.getElementById(id))).filter(Boolean);
  const hit = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const clash = over.some((a, i) => over.some((b, j) => j > i && hit(a, b)));
  return {clash, textTop: text.top, textBottom: text.bottom, overBottom: Math.max(0, ...over.map((b) => b.bottom)),
          sheetTop: document.querySelector(".sheet").getBoundingClientRect().top};
}"""


def assert_caption_clear(page, width: int) -> None:
    """The Replay label lives in the sheet, so the looks stay on the first screen; the sheet overlaps the hero by
    18px and must not cover the controls on the photo."""
    page.evaluate("window.scrollTo(0, 0)")
    m = page.evaluate(CAPTION_LAYOUT_JS)
    assert not m["clash"], f"{width}px: the photo-check pill, the zones pill and the preview toggle overlap {m}"
    assert m["overBottom"] <= m["sheetTop"], f"{width}px: the sheet covers the photo controls {m}"
    assert m["textTop"] >= m["sheetTop"], f"{width}px: the caption left the sheet {m}"


# The strongest channel: pink to peach moves blue alone, and a mean over the three channels hides that.
IMG_DIFF_JS = """async ([a, b, zone]) => {  // mean absolute difference (0..255) inside the zone's outline box
  const load = (u) => new Promise((ok, no) => {
    const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; });
  const [x, y] = await Promise.all([load(a), load(b)]);
  // outline points (0..1) from the path data: getBBox() is empty while the outlines are hidden
  const nums = [...document.querySelectorAll(`#outlines path[data-zone="${zone}"]`)]
    .flatMap((p) => p.getAttribute("d").match(/[0-9.]+/g).map(Number));
  const xs = nums.filter((_, i) => i % 2 === 0), ys = nums.filter((_, i) => i % 2 === 1);
  const x0 = Math.min(...xs), y0 = Math.min(...ys), x1 = Math.max(...xs), y1 = Math.max(...ys);
  const w = 200, h = Math.max(1, Math.round(200 * (y1 - y0) * x.naturalHeight / ((x1 - x0) * x.naturalWidth)));
  const px = (img) => {
    const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
    g.drawImage(img, x0 * img.naturalWidth, y0 * img.naturalHeight, (x1 - x0) * img.naturalWidth,
                (y1 - y0) * img.naturalHeight, 0, 0, w, h); return g.getImageData(0, 0, w, h).data; };
  const p = px(x), q = px(y), s = [0, 0, 0];
  for (let i = 0; i < p.length; i += 4)
    for (let c = 0; c < 3; c++) s[c] += Math.abs(p[i + c] - q[i + c]);
  return Math.max(...s) / (p.length / 4);
}"""


@needs("s2-classic-red")
def test_edits_show_on_the_photo_in_every_view_and_zones_step_aside(base_url, browser_ctx):
    """Nadya on an iPhone (31.10): in "Makeup + hair" an edit only changed the text; the zone outlines covered the
    face; the top pills went under the status bar. An edit must change the photo itself, whatever view is on."""
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s2-classic-red")
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    hero = page.locator("#img-hero")
    # outlines are shown once, with a pill to hide them; only the zones that have polygons
    expect(page.locator("#outlines .zone-outline").first).to_be_visible()
    assert {e.get_attribute("data-zone") for e in page.locator("#outlines .zone-outline").all()} == \
        {"eyes", "cheeks", "lips"}
    expect(page.locator("#zones-btn")).to_have_text("Hide zones")
    page.get_by_role("button", name="Makeup + hair").click()
    expect(hero).to_have_attribute("src", re.compile(r"hair"))
    before = hero.get_attribute("src")
    # she starts choosing: the outlines step aside so the face shows
    open_zone(page, "lips")
    expect(page.locator("#outlines .zone-outline").first).to_be_hidden()
    expect(page.locator("#pins .pin").first).to_be_hidden()
    expect(page.locator("#zones-btn")).to_have_text("Show zones")
    first, second = circles(page, "lips")[:2]
    tap_circle(page, first)
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    expect(hero).to_have_attribute("src", re.compile(render_name(first)))  # not the hair preview any more
    expect(page.get_by_role("button", name="Makeup", exact=True)).to_have_attribute("aria-pressed", "true")
    d1 = page.evaluate(IMG_DIFF_JS, [before, hero.get_attribute("src"), "lips"])
    assert d1 > 4.0, f"the photo itself changed on the lips: {d1}"
    # switching to another circle of the zone changes the photo again
    src1 = hero.get_attribute("src")
    tap_circle(page, second)
    expect(hero).to_have_attribute("src", re.compile(render_name(second)))
    d2 = page.evaluate(IMG_DIFF_JS, [src1, hero.get_attribute("src"), "lips"])
    same = page.evaluate(IMG_DIFF_JS, [src1, src1, "lips"])
    away = page.evaluate(IMG_DIFF_JS, [src1, hero.get_attribute("src"), "eyes"])
    assert same == 0 and away < 4.0 < d2, f"switching circles changes the lips: {d2} (same photo {same}, eyes {away})"
    # no step of the brows shows on this photo: the zone names her shade and says why, with no button
    open_zone(page, "brows")
    expect(page.get_by_test_id("shade-brows")).to_have_text("Natural")
    expect(page.get_by_test_id("note-brows")).to_have_text("This shade stays close to your own brows on this photo.")
    expect(page.get_by_test_id("zone-brows").locator("button")).to_have_count(0)
    open_zone(page, "lips")
    # the hair preview says it is the look before her changes
    page.get_by_role("button", name="Makeup + hair").click()
    expect(page.get_by_test_id("hero-caption")).to_contain_text("before your changes")
    page.get_by_role("button", name="Makeup", exact=True).click()
    # a close-up has no zone pill: "Whole face" comes first, then "Show zones" brings them back until the next choice
    expect(page.locator("#zones-btn")).to_be_hidden()
    page.locator("#whole-btn").click()
    page.locator("#zones-btn").click()
    expect(page.locator("#outlines .zone-outline").first).to_be_visible()
    expect(page.locator("#zones-btn")).to_have_text("Hide zones")
    open_zone(page, "eyes")
    expect(page.locator("#outlines .zone-outline").first).to_be_hidden()
    assert_caption_clear(page, 390)
