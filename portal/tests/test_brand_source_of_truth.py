"""contract/brand.json is the ONE source of truth for the AusMT mark, and the tool is the only author.

The brief asks for a canonical dot-grid Australia used at every size and on both backgrounds, in one
declared palette. The failure mode that ruling exists to prevent is the ordinary one: a second geometry
appears for the favicon, a third for the app icon, someone nudges a hex in an SVG, and six months later
no two AusMT marks are the same shape. So the geometry, the palette and the colour mapping are computed
ONCE by portal/tools/gen_brand.py, written to contract/brand.json, and every export is a rendering of
that file. These pins hold that arrangement:

  * the dot lattice in brand.json is REDERIVED here from the engine's own coastline truth
    (engine/extract/_au_outline.py, the same COAST rings and EXTENT the survey minimap draws), so the
    committed geometry cannot drift from the outline it claims to come from. This is the non-vacuity
    that matters: a hand-typed dots[] would fail even if it looked plausible. EVERY ring is
    rasterised, not the first two: the coastline carries islands as well as the mainland and
    Tasmania, and a ring this pin skipped would be land the mark could omit without failing.
  * Tasmania survives the rasterisation. It is three dots at this pitch, close enough to the count a
    coarser lattice would round away, and an Australia without Tasmania is a defect the owner would
    see before anyone else.
  * the palette is FOUR declared hex stops with their derivation recorded, and every dot colour is the
    ramp evaluated at that dot's own column. No dot may carry a colour off the ramp.
  * the radius is a declared function of output size (the favicon sheet's size-adaptive rule), stated
    as ordered bands, so the 16 px render can be fuller than the presentation render without a second
    geometry existing anywhere.
  * the typography block records the ruling itself: the web/SVG wordmark renders in the site's system
    UI stack, and the bundled face is a DETERMINISTIC RASTER SUBSTITUTE, never the AusMT typeface.
  * the bundled face ships its OFL text and a provenance note whose recorded digests are CHECKED
    against the bytes beside them, so the note's own replacement procedure enforces itself.
  * gen_brand.py --check is green on the committed tree (the drift gate, mirroring gen_config).
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # portal/
REPO = ROOT.parent
BRAND = REPO / "contract" / "brand.json"
TOOL = ROOT / "tools" / "gen_brand.py"
FONT_DIR = ROOT / "tools" / "brand_font"

sys.path.insert(0, str(REPO / "engine" / "extract"))
from _au_outline import COAST, EXTENT  # noqa: E402  (sibling engine module; stdlib-only, no deps)


def _doc():
    return json.loads(BRAND.read_text(encoding="utf-8"))


def _inside(ring, x, y):
    """Even-odd point-in-polygon, restated here so the pin does not lean on the tool it checks."""
    hit = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < xi + (y - yi) * (xj - xi) / (yj - yi):
            hit = not hit
        j = i
    return hit


def test_the_dot_lattice_is_the_engine_coastline_rasterised():
    """FAILS IF brand.json's dots are not exactly the cells of the declared grid whose centres fall
    inside the engine's COAST rings. The mark claims to be Australia; this is the only assertion that
    makes the claim checkable rather than decorative."""
    doc = _doc()
    geom = doc["geometry"]
    assert geom["extent"] == {k: EXTENT[k] for k in ("w", "e", "s", "n")}, (
        "brand.json must rasterise the engine's own drawing extent, not a private one")
    cols, rows = geom["grid"]["cols"], geom["grid"]["rows"]
    w, e = EXTENT["w"], EXTENT["e"]
    s, n = EXTENT["s"], EXTENT["n"]
    want = set()
    for j in range(rows):
        lat = n - (j + 0.5) * (n - s) / rows
        for i in range(cols):
            lon = w + (i + 0.5) * (e - w) / cols
            if any(_inside(ring, lon, lat) for ring in COAST):
                want.add((i, j))
    got = {(d["col"], d["row"]) for d in geom["dots"]}
    assert got == want, (
        "the committed dot lattice is not the coastline rasterisation: "
        f"{len(got - want)} dot(s) off the coast, {len(want - got)} missing")
    assert geom["dot_count"] == len(want) == len(geom["dots"]), "the declared dot count must be the truth"


def test_tasmania_survives_the_rasterisation():
    """FAILS IF the lattice coarsens until Tasmania rounds away. The brief names Tasmania explicitly;
    at this pitch it is three dots, so any loss of resolution shrinks it towards nothing rather than
    merely coarsening it.

    The mainland comparison spans every NON-Tasmanian ring, so an island ring cannot sit below
    Tasmania unnoticed: the dots below the continent must be Tasmania and nothing else."""
    tas = [d for d in _doc()["geometry"]["dots"] if d["ring"] == "tasmania"]
    assert len(tas) >= 2, f"Tasmania must survive as its own dot cluster, got {len(tas)}"
    mainland_rows = max(d["row"] for d in _doc()["geometry"]["dots"] if d["ring"] != "tasmania")
    assert min(d["row"] for d in tas) > mainland_rows, "Tasmania must sit clear of the mainland rows"


def test_the_palette_is_four_declared_stops_and_every_dot_rides_the_ramp():
    """FAILS IF a stop stops being a literal hex, if the ramp loses its derivation note, or if any dot
    carries a colour that is not the ramp evaluated at that dot's own column. One colour mapping, stated
    once: a per-variant tint is exactly what the brief forbids."""
    pal = _doc()["palette"]
    stops = pal["stops"]
    assert [s["name"] for s in stops] == ["blue", "purple", "pink", "coral"], \
        "the four stops are blue, purple, pink, coral, in that order (the brief's colour language)"
    for s in stops:
        assert re.fullmatch(r"#[0-9A-F]{6}", s["hex"]), f"stop {s['name']} must be a literal hex: {s['hex']!r}"
    assert [s["position"] for s in stops] == sorted(s["position"] for s in stops), "stops must ascend"
    assert stops[0]["position"] == 0.0 and stops[-1]["position"] == 1.0, "the ramp spans the mark"
    assert "social-card" in pal["derivation"], \
        "the palette must record that it was sampled from the established artwork"

    def ramp(t):
        for a, b in zip(stops, stops[1:]):
            if t <= b["position"] or b is stops[-1]:
                span = b["position"] - a["position"]
                u = 0.0 if span == 0 else min(1.0, max(0.0, (t - a["position"]) / span))
                ca = [int(a["hex"][k:k + 2], 16) for k in (1, 3, 5)]
                cb = [int(b["hex"][k:k + 2], 16) for k in (1, 3, 5)]
                return "#%02X%02X%02X" % tuple(round(x + (y - x) * u) for x, y in zip(ca, cb))
        raise AssertionError("unreachable")

    geom = _doc()["geometry"]
    lo = geom["bbox"]["col_min"]
    hi = geom["bbox"]["col_max"]
    for d in geom["dots"]:
        t = (d["col"] - lo) / (hi - lo)
        assert abs(d["t"] - t) < 1e-6, f"dot {d['col']},{d['row']}: t must be its column position"
        assert d["hex"] == ramp(d["t"]), f"dot {d['col']},{d['row']}: {d['hex']} is off the declared ramp"


def test_the_dot_radius_is_a_declared_function_of_output_size():
    """The favicon sheet's size-adaptive rule, made machine-readable. FAILS IF the bands stop ascending,
    if the ratios stop shrinking as the output grows (the whole point is that SMALL renders get FULLER
    dots), or if the 16 px band is not the fullest one."""
    r = _doc()["geometry"]["radius_ratio_by_output_size"]
    bands = r["bands"]
    assert [b["max_px"] for b in bands] == sorted(b["max_px"] for b in bands), "bands must ascend by size"
    ratios = [b["ratio"] for b in bands] + [r["above"]]
    assert ratios == sorted(ratios, reverse=True), \
        f"the radius ratio must shrink as the output grows (small renders get fuller dots), got {ratios}"
    assert bands[0]["max_px"] == 16, "the 16 px band is the one the favicon acceptance rests on"
    assert bands[0]["ratio"] > r["above"], "the 16 px dots must be enlarged against the presentation dots"


def test_the_typography_block_states_the_ruling_not_just_the_font():
    """FAILS IF brand.json stops recording that the web/SVG wordmark is the SITE's system UI stack and
    that the bundled face is only a deterministic raster substitute. The ruling is binding on how the
    brand is described, so the machine-readable truth has to carry it, not just a comment in a tool."""
    typo = _doc()["typography"]
    assert typo["web_font_stack"] == "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif", \
        "the SVG wordmark must declare the site header's own stack, character for character"
    assert typo["web_font_weight"] == 800, "the SVG wordmark matches the header wordmark's weight"
    assert "monospace" not in json.dumps(typo).lower(), \
        "a monospaced face never renders the wordmark (monospace belongs to identifiers elsewhere)"
    assert typo["raster_substitute"]["is_the_ausmt_typeface"] is False, \
        "the bundled face is a rendering substitute and must say so where a consumer will read it"
    assert isinstance(typo["letter_spacing_em"], float), "the chosen tracking is a declared constant"


def test_the_bundled_face_ships_its_licence_and_provenance_and_no_page_fetches_it():
    """FAILS IF the OFL text or the provenance note goes missing from beside the font file, or if any
    served page grows a reference to it. The face is build tooling: it renders PNGs offline and is never
    a web font."""
    faces = sorted(FONT_DIR.glob("*.ttf"))
    assert len(faces) == 1, f"exactly one bundled face, got {[f.name for f in faces]}"
    assert (FONT_DIR / "OFL.txt").is_file(), "the SIL OFL text ships beside the font file"
    prov = (FONT_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    for needle in ("sha256", faces[0].name, "github.com/rsms/inter"):
        assert needle in prov, f"the provenance note must record {needle}"
    stem = faces[0].stem.lower()
    for page in sorted(ROOT.glob("*.html")):
        text = page.read_text(encoding="utf-8").lower()
        assert stem not in text and "brand_font" not in text, \
            f"{page.name} references the generator-only face; it is never served to a browser"


def test_the_recorded_digests_are_the_digests_of_the_bundled_bytes():
    """The provenance note is only worth its ink if the numbers in it describe the files beside it.
    The pin above checks the note SAYS sha256; this one checks it says the RIGHT one, for the face
    and for the licence text, plus the recorded byte count.

    FAILS IF a face is swapped without updating the table, or the table is updated without swapping
    the face. Either way the recorded provenance would be describing bytes that are not there, which
    is the one thing a provenance note must never do. It also makes the note's own "Replacing it"
    procedure self-enforcing rather than a request."""
    face = sorted(FONT_DIR.glob("*.ttf"))[0]
    prov = (FONT_DIR / "PROVENANCE.md").read_text(encoding="utf-8")

    def recorded(label):
        m = re.search(rf"^\|\s*{label}\s*\|(.*)$", prov, flags=re.M)
        assert m, f"the provenance table must carry a {label!r} row"
        return m.group(1)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    bundled = re.search(r"`([0-9a-f]{64})`", recorded("Bundled sha256"))
    assert bundled and bundled.group(1) == digest(face), (
        f"PROVENANCE.md records a bundled sha256 that is not {face.name}'s: recorded "
        f"{bundled and bundled.group(1)}, actual {digest(face)}")
    licence = re.search(r"`([0-9a-f]{64})`", recorded("Licence file"))
    assert licence and licence.group(1) == digest(FONT_DIR / "OFL.txt"), (
        f"PROVENANCE.md records a licence sha256 that is not OFL.txt's: recorded "
        f"{licence and licence.group(1)}, actual {digest(FONT_DIR / 'OFL.txt')}")
    size = re.search(r"([\d,]+) bytes", recorded("Bundled size"))
    assert size and int(size.group(1).replace(",", "")) == face.stat().st_size, (
        f"PROVENANCE.md records {size and size.group(1)} bytes for {face.name}, which is "
        f"{face.stat().st_size} bytes on disk")


def test_gen_brand_check_is_green_on_the_committed_tree():
    """The drift gate, mirroring gen_config --check. FAILS IF any generated artefact in the tree differs
    from what the tool would produce now: a hand-edited export, a stale brand.json, a constant changed
    without regeneration."""
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True,
                       text=True, encoding="utf-8", cwd=str(REPO))
    assert r.returncode == 0, f"gen_brand.py --check must be green:\n{r.stdout}\n{r.stderr}"
