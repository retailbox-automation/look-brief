"""Browser smoke of the whole guided path on Replay: bride -> edit -> brief -> artist -> agreement card.
Mobile viewport; axe-core WCAG 2 A/AA on every screen. Optional: LOOKBRIEF_RECORD_DIR records one video
per page (used for the demo footage)."""

import os
import re
import time

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.e2e
AXE = Axe()
REPLACED = "Updated. Samples hold one recorded change at a time — this replaced your previous change."
UP_TO_DATE = "Your brief is already up to date — no new edits."
HERO_ON_SCREEN_JS = "() => { const r = document.getElementById('img-hero').getBoundingClientRect(); " \
    "return r.height > 0 && r.bottom > 0 && r.top < innerHeight; }"
WCAG = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}}


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


def test_guided_path_both_roles(base_url, browser_ctx):
    t0 = time.monotonic()
    page = browser_ctx.new_page()
    page.goto(base_url + "/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("before you pay for the trial")
    check_a11y(page, "home")

    page.locator("[data-testid^=sample-]").first.click()
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("mode-badge")).to_have_text("Replay · recorded real YouCam API results")
    expect(page.locator("#cap-after")).to_contain_text("Recorded real YouCam API result")
    expect(page.locator(".zone")).to_have_count(3)
    expect(page.locator("#gaps tbody tr")).to_have_count(3)
    check_a11y(page, "your look")
    even = page.get_by_role("button", name="Even out redness")
    hair_first = bool(even.count() and even.is_visible())  # the heroine sample (first on the home page)
    if hair_first:
        even.click()
        expect(page.get_by_test_id("hero-caption")).to_contain_text("foundation in her shade over the transfer")
        page.get_by_role("button", name="Transfer").click()

    page.get_by_role("button", name="Cheeks", exact=True).click()  # open the Cheeks zone in the sheet
    page.get_by_role("button", name=re.compile("Cheeks: a shade deeper", re.I)).click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.get_by_role("button", name=re.compile("Cheeks: softer", re.I)).click()  # a second change replaces the first
    expect(page.locator("#edit-msg")).to_have_text(REPLACED, timeout=20_000)
    expect(page.locator("#cap-render")).to_contain_text("Makeup VTO re-render")

    page.get_by_role("button", name="Send brief to my makeup artist").click()
    expect(page.get_by_test_id("artist-link")).to_have_attribute("href", re.compile(r"^/b/"))
    artist_url = page.get_by_test_id("artist-link").get_attribute("href")
    bride_url = page.get_by_test_id("bride-link").get_attribute("href")
    assert artist_url and bride_url and artist_url != bride_url

    # the bride opens her link before the artist answered: she is told what she is waiting for, and she sees
    # her adjusted look (not the raw transfer) as the agreed target, with visible captions
    bride = browser_ctx.new_page()
    bride.goto(base_url + bride_url)
    expect(bride.locator("#agree-help")).to_have_text("Waiting for your makeup artist to answer every zone.")
    expect(bride.locator("#b-after")).to_have_attribute("src", re.compile(r"render-cheeks-softer"))
    expect(bride.locator("#b-after-cap")).to_contain_text("Agreed look: your adjusted look")
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
    expect(reviews).to_have_count(5 if hair_first else 4)  # eyelids, cheeks, lips, hair (+ skin: even out redness)
    snap = artist.request.get(base_url + artist_url.replace("/b/", "/api/briefs/")).json()["snapshot"]
    cheeks_hex = next(z["product_hex"] for z in snap["zones"] if z["zone"] == "cheeks")
    expect(artist.get_by_test_id("review-cheeks")).to_contain_text(cheeks_hex)  # not only in the shades list below
    if hair_first:
        expect(artist.get_by_test_id("review-skin")).to_be_visible()
        expect(artist.locator("#shades")).to_contain_text("foundation in her shade · intensity 30")
        expect(artist.locator("#shades")).not_to_contain_text("foundation in her shade · coverage")
    for i in range(reviews.count()):
        fs = reviews.nth(i)
        cheeks = fs.get_attribute("data-testid") == "review-cheeks"
        fs.get_by_label("I'll swap the product" if cheeks else "I'll do this").check()
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


def test_hair_first_sample_by_link_with_even_out(base_url, browser_ctx):
    """The heroine sample: hair first, then makeup, then 'Even out redness' (foundation in her shade)."""
    import json
    import urllib.request
    from pathlib import Path

    samples = Path(__file__).resolve().parents[2] / "samples"
    hair_first = [p.name for p in sorted(samples.glob("s*")) if (p / "manifest.json").exists()
                  and json.loads((p / "manifest.json").read_text()).get("order") == "hair_first"]
    if not hair_first:
        pytest.skip("no hair_first sample recorded")
    assert hair_first[0] in json.load(urllib.request.urlopen(base_url + "/healthz"))["samples"], "on the home page"
    page = browser_ctx.new_page()
    page.goto(base_url + "/")
    page.get_by_test_id(f"sample-{hair_first[0]}").click()  # the way a visitor opens it: from the home page
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    # her look opens on "Even out redness" (foundation in her shade over the transfer)
    expect(page.get_by_role("button", name="Even out redness")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("hero-caption")).to_contain_text("foundation in her shade over the transfer")
    expect(page.get_by_test_id("hero-caption")).to_contain_text("Recorded real YouCam API result")
    page.get_by_role("button", name="Transfer", exact=True).click()
    expect(page.get_by_test_id("hero-caption")).to_contain_text("Hair Transfer + Makeup Transfer")
    # an edit is shown over her even tone, never on the raw transfer
    page.get_by_role("button", name="Cheeks", exact=True).click()
    page.get_by_role("button", name="Cheeks: softer").click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.wait_for_function(HERO_ON_SCREEN_JS, timeout=5_000)  # 390x844: the change itself is on screen
    expect(page.locator("#reset")).to_have_text("Back to my look")
    expect(page.locator("#zone-extra")).to_have_text("")  # 1% of the nose area is not a warning
    # the caption names a part of the task id that differs between re-renders; the full id is in the title
    sid = page.url.rsplit("/", 1)[1]
    steps = page.evaluate(f"async () => (await (await fetch('/api/sessions/{sid}')).json()).steps")
    softer, base = steps["render:cheeks:softer"]["task_id"], steps["render:base"]["task_id"]
    assert task_fragment(softer) != task_fragment(base), (softer, base)
    expect(page.get_by_test_id("hero-caption")).to_contain_text(f"task {task_fragment(softer)}")
    expect(page.get_by_test_id("hero-caption")).to_have_attribute("title", f"YouCam task {softer}")
    expect(page.get_by_role("button", name="Even out redness")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("hero-caption")).to_contain_text("same foundation in her shade")
    expect(page.locator("#img-hero")).to_have_attribute("src", re.compile(r"render-cheeks-softer"))
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
    send.click()
    expect(link).not_to_have_attribute("href", first)
    expect(copy).to_have_text("Copy")
    # hair first has no "hair" image: the Hair Transfer on her selfie is shown as the hair, here and in the brief
    page.get_by_text("Inspiration, hair and the measured map").click()
    assert page.evaluate("document.getElementById('img-hair').naturalWidth") > 0
    expect(page.locator("#cap-hair")).to_contain_text("Hair (YouCam Hair Transfer on your selfie)")
    bride = browser_ctx.new_page()
    bride.goto(base_url + page.get_by_test_id("bride-link").get_attribute("href"))
    expect(bride.get_by_test_id("review-hair")).to_contain_text(
        "Hair as in the agreed look photo above (YouCam Hair Transfer)")
    bride.get_by_text("Inspiration photo and hair preview").click()
    expect(bride.locator("#b-hair-cap")).to_have_text("Hair (YouCam Hair Transfer on her selfie)")
    bride.wait_for_function("document.getElementById('b-hair').naturalWidth > 0", timeout=5_000)
    expect(bride.locator("#b-hair")).to_be_visible()
    # back to her look after a change
    page.get_by_role("button", name="Cheeks: softer").click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.get_by_role("button", name="Back to my look").click()
    expect(page.locator("#edit-msg")).to_have_text("Back to your look.", timeout=20_000)


def task_fragment(task_id: str) -> str:
    """The part of a YouCam task id the captions show (session.js taskFragment)."""
    return f"{task_id[:4]}…{task_id[-30:-22]}" if len(task_id) >= 40 else f"{task_id[:10]}…"


def test_transfer_first_sample_keeps_the_nose_note_and_reset_text(base_url, browser_ctx):
    page = browser_ctx.new_page()
    page.goto(base_url + "/try/s2-classic-red")  # the transfer changed 12% of her nose area
    expect(page.locator("#look")).to_be_visible(timeout=30_000)
    expect(page.locator("#zone-extra")).to_contain_text("Also changed: nose & contour")
    page.get_by_role("button", name="Cheeks", exact=True).click()
    page.get_by_role("button", name="Cheeks: softer").click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    page.get_by_role("button", name="Back to the transferred look").click()
    expect(page.locator("#edit-msg")).to_have_text("Back to the transferred look.", timeout=20_000)


CAPTION_LAYOUT_JS = """() => {
  const box = (el) => el && !el.hidden ? el.getBoundingClientRect() : null;
  const cap = document.getElementById("hero-cap");
  const range = document.createRange(); range.selectNodeContents(cap);
  const text = range.getBoundingClientRect();
  const over = ["hero-toggle", "hero-check"].map((id) => box(document.getElementById(id))).filter(Boolean);
  const [tg, ck] = over.length === 2 ? over : [null, null];
  const clash = !!(tg && ck && ck.left < tg.right && tg.left < ck.right && ck.top < tg.bottom && tg.top < ck.bottom);
  return {clash, textTop: text.top, textBottom: text.bottom, overBottom: Math.max(0, ...over.map((b) => b.bottom)),
          sheetTop: document.querySelector(".sheet").getBoundingClientRect().top};
}"""


def assert_caption_clear(page, width: int) -> None:
    """The Replay label under the photo must be fully readable: nothing on the photo overlaps it and the
    makeup-map sheet (which overlaps the hero by 18px) does not cover its last line."""
    page.evaluate("window.scrollTo(0, 0)")
    m = page.evaluate(CAPTION_LAYOUT_JS)
    assert not m["clash"], f"{width}px: the photo-check pill and the preview toggle overlap {m}"
    assert m["textTop"] >= m["overBottom"], f"{width}px: photo controls overlap the caption {m}"
    assert m["textBottom"] <= m["sheetTop"], f"{width}px: the sheet covers the caption {m}"
