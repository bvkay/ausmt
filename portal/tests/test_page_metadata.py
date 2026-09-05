"""What the static portal pages tell a search engine and a link-preview crawler about themselves.

index.html has carried a full head since the head-hygiene workflow. The other four had a title and a
canonical and nothing else: no description, so a result row for About showed whatever Google could
scrape off the page, and no Open Graph tags at all, so a link to any of them previewed as a bare URL.

Two rules hold the descriptions honest, and both are pinned here rather than left to review:

  * THE DESCRIPTION IS THE PAGE'S OWN LEDE, word for word. An invented summary is a second wording
    of the page that nobody maintains and that drifts the first time the page is edited.
  * og:title IS THE PAGE'S OWN <title>. Two titles for one document is the same problem in the tag
    a preview card actually prints.

brand.html is the exception in the other direction: it is an asset shelf, reached from About by
anyone who needs a logo file, and it declares itself unindexable. The engine holds the other half of
that rule by keeping it out of sitemap.xml (engine/tests/test_sitemap_pathurls.py).
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # portal/
SITE = "https://ausmt.auscope.org.au"
CARD = f"{SITE}/vendor/social-card.png"

# page -> (canonical path, the selector its lede is written in)
PAGES = {
    "about.html": ("about.html", "sub"),
    "releases.html": ("releases.html", "sub"),
    "add-survey.html": ("add-survey.html", "lede"),
}


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _meta(text, attr, name):
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)">', text)
    return m.group(1) if m else None


def _lede(text, cls):
    """The page's own lede, as a reader sees it: tags stripped, entities resolved, spaces collapsed."""
    m = re.search(rf'<p class="{cls}">(.*?)</p>', text, re.S)
    assert m, f"the page must carry a <p class={cls}> lede"
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).split())


def test_every_static_page_describes_itself_in_its_own_words():
    """FAILS IF a description goes missing, or stops being a prefix of the page's own opening
    paragraph. A prefix, not equality: add-survey's lede runs on past what a description should
    carry, so the first sentences of it are taken and the cut falls on a sentence boundary."""
    for name, (_canon, cls) in PAGES.items():
        text = _text(name)
        desc = _meta(text, "name", "description")
        assert desc, f"{name}: must ship a meta description"
        lede = _lede(text, cls)
        assert lede.startswith(desc), \
            f"{name}: the description must be the page's own lede, got {desc!r} against {lede!r}"
        assert desc.endswith("."), f"{name}: the description must end on a sentence, got {desc!r}"


def test_every_static_page_previews_as_itself():
    """The six tags a preview crawler reads, plus the size hints and the card type index.html
    already declares. FAILS IF a page loses one, or names a different document in one of them."""
    for name, (canon, _cls) in PAGES.items():
        text = _text(name)
        title = re.search(r"<title>(.*?)</title>", text).group(1)
        desc = _meta(text, "name", "description")
        assert _meta(text, "property", "og:type") == "website", name
        assert _meta(text, "property", "og:site_name") == "AusMT", \
            f"{name}: the preview must name the site, not its publisher"
        assert _meta(text, "property", "og:title") == title, \
            f"{name}: one document, one title"
        assert _meta(text, "property", "og:description") == desc, \
            f"{name}: one document, one description"
        assert _meta(text, "property", "og:url") == f"{SITE}/{canon}", name
        assert f'<link rel="canonical" href="{SITE}/{canon}">' in text, \
            f"{name}: og:url and the canonical must be the same address"
        assert _meta(text, "property", "og:image") == CARD, name
        assert _meta(text, "property", "og:image:width") == "1200", name
        assert _meta(text, "property", "og:image:height") == "630", name
        assert _meta(text, "name", "twitter:card") == "summary_large_image", name
        assert (ROOT / "vendor" / "social-card.png").is_file(), \
            "the card every page previews with must be a file this portal ships"


def test_the_root_page_names_the_site_and_not_only_its_publisher():
    """index.html carried one JSON-LD node, a DataCatalog whose only named organisation was the
    publisher, so search results labelled the site AuScope. The WebSite node is the fix, and the
    catalogue node stays alongside it and stays first."""
    import json
    text = _text("index.html")
    blocks = re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', text)
    assert len(blocks) == 2, f"index.html must carry two JSON-LD blocks, got {len(blocks)}"
    nodes = [json.loads(b) for b in blocks]
    assert nodes[0]["@type"] == "DataCatalog", "the catalogue node stays first"
    site = nodes[1]
    assert site["@type"] == "WebSite", nodes
    assert site["name"] == "AusMT"
    assert site["alternateName"] == "Australia's Magnetotelluric Data Portal"
    assert site["url"] == f"{SITE}/"
    assert site["publisher"]["name"] == "AuScope"
    assert _meta(text, "property", "og:site_name") == "AusMT"


def test_the_brand_page_keeps_itself_out_of_the_index():
    """FAILS IF brand.html loses its noindex, or if a robots.txt Disallow is added for it: blocking
    the crawl would stop the crawler ever reading the noindex, which is the opposite of the rule.
    Its canonical stays, because a page with no declared address is worse than an unindexed one."""
    text = _text("brand.html")
    assert '<meta name="robots" content="noindex">' in text, \
        "brand.html is an asset shelf and must stay out of the search index"
    assert f'<link rel="canonical" href="{SITE}/brand.html">' in text, \
        "an unindexed page still declares which address it is served at"
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    assert "brand" not in robots, \
        "a Disallow would stop the crawler ever reading brand.html's noindex"
