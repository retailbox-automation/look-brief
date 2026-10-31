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

    page.get_by_role("button", name="Cheeks", exact=True).click()  # open the Cheeks zone in the sheet
    page.get_by_role("button", name=re.compile("Cheeks: softer", re.I)).click()
    expect(page.locator("#edit-msg")).to_have_text("Updated.", timeout=20_000)
    expect(page.locator("#cap-render")).to_contain_text("Makeup VTO re-render")

    page.get_by_role("button", name="Send brief to my makeup artist").click()
    expect(page.get_by_test_id("artist-link")).to_have_attribute("href", re.compile(r"^/b/"))
    artist_url = page.get_by_test_id("artist-link").get_attribute("href")
    bride_url = page.get_by_test_id("bride-link").get_attribute("href")
    assert artist_url and bride_url and artist_url != bride_url

    artist = browser_ctx.new_page()
    artist.goto(base_url + artist_url)
    expect(artist.get_by_text("For your makeup artist · no account needed")).to_be_visible()
    reviews = artist.locator("fieldset.review")
    expect(reviews).to_have_count(4)  # eyelids, cheeks, lips, hair
    for i in range(reviews.count()):
        fs = reviews.nth(i)
        fs.get_by_label("I'll swap the product" if i == 1 else "I'll do this").check()
    artist.locator("input[name=note-cheeks]").fill("I'll use a cooler pink")
    artist.locator("input[name=note-cheeks]").press("Tab")
    check_a11y(artist, "artist brief")
    expect(artist.get_by_role("button", name="Agree to this look")).to_be_enabled(timeout=10_000)
    artist.get_by_role("button", name="Agree to this look").click()
    expect(artist.locator("#agree-help")).to_contain_text("Waiting for the bride")

    bride = browser_ctx.new_page()
    bride.goto(base_url + bride_url)
    expect(bride.locator("#agree-help")).to_contain_text("The artist agreed")
    bride.get_by_role("button", name="Agree to this look").click()
    expect(bride.locator("#agree-help")).to_contain_text("signed by the server")
    bride.locator("#card-a").click()
    expect(bride.get_by_role("heading", name="Server-attested agreement")).to_be_visible()
    expect(bride.get_by_text("I'll use a cooler pink")).to_be_visible()
    check_a11y(bride, "agreed-look card")
    assert time.monotonic() - t0 < 90, "the guided path must fit in 90 seconds"
