"""No CDN runtime dependency (Invariant 10).

index.html loaded Leaflet, Leaflet.markercluster, Leaflet.draw and JSZip from cdnjs.cloudflare.com at
page-load time: a CDN outage, block, or supply-chain compromise there could silently break or tamper
with every page load. The libraries are now vendored under portal/vendor/ and referenced by relative
path (see portal/vendor/README.md for upstream URLs + sha256 provenance).

Change 6 RETIRED Leaflet.markercluster: proximity clustering was replaced by
per-survey badges, which the brief then removed in turn (site locations only). The plugin,
its stylesheet and both vendored files are gone, so the vendored set below is the THREE remaining
libraries. tests/test_map_dots.py owns the assertion that no markercluster or badge asset comes back.

Fails if: `cdnjs.cloudflare.com` reappears anywhere in the shipped HTML entry points, OR any vendored
script/link tag in index.html points somewhere other than `vendor/`.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/


def test_no_cdnjs_reference_in_html():
    hits = []
    for name in ("index.html", "about.html", "add-survey.html"):
        f = ROOT / name
        if not f.exists():
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            if "cdnjs.cloudflare.com" in line:
                hits.append(f"{name}:{lineno}: {line.strip()}")
    assert not hits, "found a cdnjs.cloudflare.com reference (should be vendored under portal/vendor/):\n" + "\n".join(hits)


def test_leaflet_and_jszip_assets_are_vendored():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for tag_src in ("vendor/leaflet.css", "vendor/leaflet.draw.css",
                     "vendor/leaflet.js", "vendor/leaflet.draw.js",
                     "vendor/jszip.min.js"):
        assert tag_src in html, f"expected index.html to reference {tag_src}"


def test_vendor_files_present_and_nonempty():
    # The libraries, then the brand assets the site's own surfaces fetch: the AusMT identity mark's
    # source, the parent organisation's white icon (the docs sidebar copy, the collection figure and
    # the social card composite it), the AuScope-NCRIS lockup every footer carries, and the colour
    # icon the SPA map draws as its watermark. The bytes of the last one are held in
    # tests/test_map_watermark.py; what this inventory says is that the portal ships it at all.
    for name in ("leaflet.js", "leaflet.css", "jszip.min.js",
                 "leaflet.draw.js", "leaflet.draw.css",
                 "auscope-icon-white.png", "auscope-ncris-white.png", "auscope-icon-colour.png"):
        p = ROOT / "vendor" / name
        assert p.exists(), f"missing vendored asset {p}"
        assert p.stat().st_size > 0, f"vendored asset {p} is empty"
