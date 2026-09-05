"""brand.html: where the logo files actually live for anyone who needs one.

A brand kit that exists only in a repository is a brand kit nobody uses. Someone writing a talk, a
paper or a poster needs the right file, on the right background, at a size that will not fall apart
in a projector, and they need to be told the two rules that matter (use the variant that suits the
background, keep the proportions and the clear space). That is the whole job of this page.

What these pins hold:

  * THE USAGE NOTE IS VERBATIM from the brief. It is permission language: paraphrasing it is
    quietly rewriting what people are allowed to do with the marks.
  * EVERY GENERATED VARIANT IS OFFERED, in both formats, and every link resolves to a file this
    portal actually ships. A brand page with a dead download is worse than no brand page.
  * EACH VARIANT SITS ON ITS INTENDED BACKGROUND. The dark-background lockups are previewed on the
    navy brand.json declares, the light ones on white. Showing a white wordmark on white is exactly
    how a reader concludes the file is broken and gives up.
  * THE PALETTE ON THE PAGE IS BRAND.JSON'S PALETTE, hex for hex and in order. The page states the
    colours because a brand page that does not is useless; the pin is what stops the statement
    becoming a second, drifting source of truth.
  * THE FULL PIXELATED ARTWORK IS OFFERED SEPARATELY, as the presentation hero graphic. The
    relationship doctrine is that the simplified dot mark is the identity and the full artwork is the
    hero image; the page has to keep those apart or the doctrine dies on first contact with a reader.
  * PORTAL CHROME, and the header geometry with it: this is a portal page, not an orphan.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # portal/
REPO = ROOT.parent
PAGE = ROOT / "brand.html"
BRAND_JSON = REPO / "contract" / "brand.json"

USAGE_NOTE = (
    "AusMT logos and graphics are available for use in presentations, publications and other "
    "material referring to AusMT. Use the dark-background version on dark colours and the "
    "light-background version on light colours. Please retain the proportions, colours and clear "
    "space of the AusMT mark."
)
VARIANTS = ("ausmt-logo-dark", "ausmt-logo-light",
            "ausmt-logo-dark-extended", "ausmt-logo-light-extended", "ausmt-mark")


def _text():
    return PAGE.read_text(encoding="utf-8")


def test_the_usage_note_is_the_owners_words_unaltered():
    """FAILS IF the usage note is paraphrased, trimmed or restyled into different words. It states
    what people may do with the marks, so its wording is the custodian's to set, not this page's."""
    flat = re.sub(r"\s+", " ", _text())
    assert USAGE_NOTE in flat, "the usage note must appear verbatim, exactly as the brief states it"


def test_every_generated_variant_is_offered_in_both_formats_and_every_file_exists():
    """FAILS IF a variant is missing from the page, offered in only one format, or linked at a path
    the portal does not ship. Checked against the filesystem, so a rename anywhere breaks this rather
    than shipping a dead download."""
    hrefs = set(re.findall(r'href="(vendor/[^"]+)"', _text()))
    for stem in VARIANTS:
        for ext in ("svg", "png"):
            rel = f"vendor/brand/{stem}.{ext}"
            assert rel in hrefs, f"brand.html must offer {rel}"
    for rel in hrefs:
        assert (ROOT / rel).is_file(), f"brand.html links {rel}, which the portal does not ship"


def test_each_variant_is_previewed_on_the_background_it_is_drawn_for():
    """FAILS IF a dark-background lockup is previewed on the light panel or the reverse. The panel
    colours come from brand.json, so the previews cannot drift from the declared backgrounds."""
    bg = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["palette"]["backgrounds"]
    text = _text()
    assert f"--preview-dark:{bg['dark']}" in text, \
        f"the dark preview panel must be brand.json's dark background {bg['dark']}"
    assert f"--preview-light:{bg['light']}" in text, \
        f"the light preview panel must be brand.json's light background {bg['light']}"
    panels = re.findall(r'<figure class="panel (dark|light)[^"]*">.*?src="vendor/brand/([a-z-]+)\.svg"',
                        text, re.S)
    assert panels, "the previews must be figures naming their panel and their file"
    for panel, stem in panels:
        if stem == "ausmt-mark":
            continue          # the mark is one object and is shown on BOTH panels on purpose
        assert panel in stem, f"{stem}.svg is previewed on the {panel} panel, which is the wrong one"
    assert sum(1 for p, s in panels if s == "ausmt-mark") == 2, \
        "the standalone mark is shown on both panels, because it is identical on both"


def test_the_palette_on_the_page_is_brand_jsons_palette():
    """FAILS IF the page states a colour brand.json does not declare, or states them out of order.
    The page has to name the colours to be useful; this is what stops it becoming a second source of
    truth that quietly drifts from the generator."""
    stops = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["palette"]["stops"]
    swatches = re.findall(r'<li class="swatch" style="--swatch:(#[0-9A-F]{6})">\s*<code>(#[0-9A-F]{6})</code>',
                          _text())
    assert [s[0] for s in swatches] == [s["hex"] for s in stops], (
        f"the page's swatches must be brand.json's stops in order, got {[s[0] for s in swatches]}")
    for fill, label in swatches:
        assert fill == label, f"a swatch shows {fill} and labels it {label}"


def test_the_clear_space_the_page_states_is_the_declared_one():
    """The page told readers a rule the shipped lockups do not follow: it said a quarter of the mark
    height while PROPORTIONS declares 0.20, tightened and left stranded here. It was also
    the only number on the page not held against brand.json, which is exactly the drifting second
    source of truth the palette pin exists to prevent.

    FAILS IF the stated clear space stops being brand.json's clear_space. The lockup files are drawn
    with it, so a reader following the page's number would leave less room than the file already
    reserves."""
    cs = json.loads(BRAND_JSON.read_text(encoding="utf-8"))["proportions"]["clear_space"]
    flat = re.sub(r"\s+", " ", _text())
    assert f"at least {cs:.0%} of the mark's height" in flat, (
        f"brand.html must state the declared clear space ({cs:.0%} of the mark height); a second "
        "number here is a second source of truth")


def test_the_full_artwork_is_offered_separately_from_the_mark():
    """The relationship doctrine, on the one page a reader chooses a file. FAILS IF the pixelated
    artwork is not offered, or is presented as a logo rather than as the presentation hero graphic."""
    text = _text()
    assert 'href="vendor/social-card.png"' in text, "the full artwork must be offered for download"
    assert (ROOT / "vendor" / "social-card.png").is_file()
    hero = re.search(r'<section id="artwork".*?</section>', text, re.S)
    assert hero, "the full artwork needs its own section, apart from the logo variants"
    assert "presentation" in hero.group(0).lower(), \
        "the artwork section must say what the artwork is FOR (presentations and hero use)"
    assert "vendor/brand/" not in hero.group(0), \
        "the artwork section must not mix the logo files in with the hero graphic"


def test_the_page_wears_the_portal_chrome_and_the_c9_header_geometry():
    """FAILS IF brand.html is an orphan page. It carries the same three-zone header (with the zero
    basis sides), the AusMT mark as its identity, and the standard footer."""
    text = _text()
    for zone, rule in ((".hleft", "flex:1 1 0"), (".hcenter", "flex:0 1 auto"), (".hright", "flex:1 1 0")):
        m = re.search(re.escape(zone) + r"\{([^}]*)\}", text)
        assert m and rule in m.group(1), f"brand.html: {zone} must carry {rule}"
    assert '<img class="brandmark" src="/vendor/brand/ausmt-mark.svg" alt="AusMT" width="30" height="30">' \
        in text, "brand.html must carry the site's identity mark, like every other surface"
    for nav_id, href in (("navMap", "/"), ("navSurveys", "/surveys"), ("navCollections", "/collections")):
        assert re.search(rf'<a id="{nav_id}" href="{re.escape(href)}"', text), \
            f"brand.html: {nav_id} must point at {href}"
    assert '<link rel="canonical" href="https://ausmt.auscope.org.au/brand.html">' in text, \
        "a page the sitemap advertises must declare its canonical"
    # The site's ONE footer. Its strings, targets and geometry are held for all six documents at once
    # in tests/test_footer_regions.py; what is asserted here is that this page carries it at all,
    # named by the region the one-footer rule put in its right zone.
    assert "<footer>" in text and 'class="orglogo"' in text, \
        "brand.html must carry the standard footer, lockup and all"


def test_about_links_the_brand_page():
    """FAILS IF About stops pointing at the brand page. It is the only navigation into it: the page
    is deliberately not a sixth header item."""
    about = (ROOT / "about.html").read_text(encoding="utf-8")
    assert 'href="brand.html"' in about, "about.html must link the brand page"
    assert "Brand" in about, "the About link must name the brand page in words a reader can find"
    for name in ("index.html", "releases.html", "add-survey.html"):
        page = (ROOT / name).read_text(encoding="utf-8")
        header = page.split("</header>", 1)[0]
        assert 'href="brand.html"' not in header, \
            f"{name}: the brand page is not a sixth header item; the header carries five"
