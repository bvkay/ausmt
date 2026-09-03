"""Where the static pages' chrome actually points (findability workflow, index pages).

The static portal pages (about, releases, add-survey, and brand since the brand-assets workflow) carry
the same header as index.html so the chrome reads identically across the site. Their LINKS did not
follow: every primary nav item pointed at bare index.html, which meant

  * Surveys and Collections both landed on the Map - four header items that silently
    mis-navigated, documented as deliberate in about.html's own source comment because no route
    existed to point them at;
  * every one of those links took a needless 301 hop (/index.html -> /), including add-survey's
    "Back to portal";
  * the guided-tour link was index.html?tour=1, whose query the alias redirect dropped, so the
    tour could not be started from its only documented entry point;
  * none of the three declared a canonical, and none was in the sitemap.

The hub pages exist now, so the destinations exist. These pins hold the chrome to them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://ausmt.auscope.org.au"

# page -> its canonical path, the URL a crawler must be told is the one true address for it.
# Brand.html joined them in the brand-assets workflow: it is substantive, linked from About and
# advertised in sitemap.xml, so it answers to the same chrome rules as the other three.
_STATIC_PAGES = {
    "about.html": f"{BASE}/about.html",
    "releases.html": f"{BASE}/releases.html",
    "add-survey.html": f"{BASE}/add-survey.html",
    "brand.html": f"{BASE}/brand.html",
}


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["about.html", "releases.html"])
def test_the_header_nav_points_at_the_real_destinations(name):
    """FAILS IF a primary nav item still points at index.html. Map is the SPA root, Surveys is the
    surveys index page and Collections is the collections index page: three destinations, three
    hrefs, no shared landing spot and no redirect hop."""
    text = _text(name)
    for nav_id, href in (("navMap", "/"), ("navSurveys", "/surveys"),
                         ("navCollections", "/collections")):
        m = re.search(rf'<a id="{nav_id}" href="([^"]+)"', text)
        assert m, f"{name}: no {nav_id} link"
        assert m.group(1) == href, f"{name}: {nav_id} must point at {href}, got {m.group(1)}"


def test_add_survey_back_link_goes_straight_to_the_portal_root():
    """FAILS IF the Back to portal control still exercises the /index.html 301."""
    m = re.search(r'<a class="back" href="([^"]+)"', _text("add-survey.html"))
    assert m and m.group(1) == "/", f"add-survey back link must be /, got {m and m.group(1)}"


def test_no_static_page_links_the_index_html_alias():
    """FAILS IF any link on the three static pages still targets index.html. The alias exists so a
    published /index.html URL keeps working; the site's own links should never spend a hop on it."""
    for name in _STATIC_PAGES:
        hrefs = re.findall(r'href="([^"]*index\.html[^"]*)"', _text(name))
        assert not hrefs, f"{name}: links still target the index.html alias: {hrefs}"


def test_the_guided_tour_link_reaches_the_tour():
    """FAILS IF About's tour link stops carrying ?tour=1 to the root. The SPA reads the flag from
    location.search, so this is the only documented way into the tour outside the intro panel; the
    box redirect now preserves the query too, which makes this belt and braces rather than the
    single point of failure it was."""
    text = _text("about.html")
    assert 'href="/?tour=1"' in text, "the About tour link must reach /?tour=1 directly"


@pytest.mark.parametrize("name,url", sorted(_STATIC_PAGES.items()))
def test_every_static_page_declares_its_canonical(name, url):
    """FAILS IF a static page ships without a canonical. All three are substantive, indexable and
    linked from the root, and all three now appear in the sitemap; a page a crawler is pointed at
    must say which URL it is."""
    assert f'<link rel="canonical" href="{url}">' in _text(name), \
        f"{name} must declare its canonical at {url}"


def test_the_404_page_recovers_to_the_surveys_index():
    """FAILS IF the 404 page's recovery link still points at the dead #/surveys hash route. It is
    the one link a reader who arrived on a stale URL is offered, and it used to leave them on the
    map with no explanation."""
    text = _text("404.html")
    assert 'href="/surveys"' in text, "the 404 recovery link must reach the surveys index"
    assert "#/surveys" not in text, "the dead hash route must be gone"


def test_the_spa_header_surveys_and_collections_are_real_links():
    """LANE-ADDENDUM-HUB-FEEDBACK.md R10, the live review of /surveys.

    The hub pages exist and are served at /surveys and /collections, so the SPA header's own Surveys
    and Collections controls stop being in-app view switches and become links to them, matching the
    chrome the three static pages already point that way. Map stays in-app: it IS the application.

    FAILS IF either control is still a <button>, if it points anywhere but its hub, or if Map stops
    being the in-app control. The two in-app views remain reachable at their #/surveys and
    #/collections hash routes, pinned separately below."""
    text = _text("index.html")
    for nav_id, href in (("navSurveys", "/surveys"), ("navCollections", "/collections")):
        m = re.search(rf'<a id="{nav_id}"[^>]*href="([^"]+)"', text)
        assert m, f"index.html: {nav_id} must be a real link now, not a button"
        assert m.group(1) == href, f"index.html: {nav_id} must point at {href}, got {m.group(1)}"
        assert f'<button id="{nav_id}"' not in text, f"index.html: {nav_id} is no longer a button"
    assert re.search(r'<button id="navMap"', text), \
        "index.html: Map stays the in-app control; it is the application, not a destination"


def test_the_spa_keeps_its_in_app_surveys_and_collections_views_on_their_hash_routes():
    """The other half of R10: making the header controls into links must not RETIRE the in-app
    views. #/surveys and #/collections are published in the wild and still switch the SPA's own
    grid views, and the header no longer wires a click handler onto controls that navigate away.

    FAILS IF the hash branches go, or if a click handler is left on a control that is now a link
    (which would run a view switch the browser is about to navigate away from)."""
    main = (ROOT / "src" / "main.js").read_text(encoding="utf-8")
    assert '"#/surveys"' in main and '"#/collections"' in main, \
        "the plural hash routes must still reach the in-app views"
    for nav_id in ("navSurveys", "navCollections"):
        assert f'getElementById("{nav_id}").onclick' not in main, \
            f"{nav_id} navigates now; a click handler would switch a view the page is leaving"
    assert 'getElementById("navMap").onclick' in main, "Map keeps its in-app handler"
