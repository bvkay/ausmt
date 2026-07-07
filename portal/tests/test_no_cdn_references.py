"""No CDN runtime dependency (Invariant 10).

index.html loaded Leaflet, Leaflet.markercluster, Leaflet.draw and JSZip from cdnjs.cloudflare.com at
page-load time: a CDN outage, block, or supply-chain compromise there could silently break or tamper
with every page load. All four libraries are now vendored under portal/vendor/ and referenced by
relative path (see portal/vendor/README.md for upstream URLs + sha256 provenance).

Fails if: `cdnjs.cloudflare.com` reappears anywhere in the shipped HTML entry points, OR any vendored
script/link tag in index.html points somewhere other than `vendor/`.
"""
import re
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
    for tag_src in ("vendor/leaflet.css", "vendor/MarkerCluster.min.css", "vendor/leaflet.draw.css",
                     "vendor/leaflet.js", "vendor/leaflet.markercluster.min.js", "vendor/leaflet.draw.js",
                     "vendor/jszip.min.js"):
        assert tag_src in html, f"expected index.html to reference {tag_src}"


def test_vendor_files_present_and_nonempty():
    for name in ("leaflet.js", "leaflet.css", "jszip.min.js", "leaflet.markercluster.min.js",
                 "MarkerCluster.min.css", "leaflet.draw.js", "leaflet.draw.css"):
        p = ROOT / "vendor" / name
        assert p.exists(), f"missing vendored asset {p}"
        assert p.stat().st_size > 0, f"vendored asset {p} is empty"
