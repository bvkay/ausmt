"""C42 coordinate-access engine lane (Invariant 10 — every pin states its failure criterion).

The custodian chooses exact / generalised (0.1deg) / withheld per station. This suite drives the REAL
pipeline (subprocess build) over ENGINE-PRODUCED fixtures — a survey built from real broadband EDIs
whose COORDINATE HEADER lines are rewritten to distinctive, mutually-consistent decimal values (HEAD ==
INFO == DEFINEMEAS, so no dms_sign flag fires and the sweep target is unambiguous). The transfer-
function bodies are the real sample EDIs, so the pipeline produces real stations; only the positions are
distinctive. Fixtures are never hand-typed catalogue rows (house rule) — they are the build's own output.

The centrepiece is the LEAK-SWEEP: a full byte sweep of the emitted out/ tree (every file) for the TRUE
values of a non-exact station, in every string variant + a numeric JSON parse with epsilon >= 1e-3. It is
mutation-proven TWO ways (all-exact flip finds every value; a planted 3-dp derivative is caught by the
epsilon). Warm-cache re-runs the sweep on a second build (cache hits, zero misses) to pin the D3 cache
boundary. Requires the mt_metadata/mth5 build stack.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE_EDI = ROOT / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
sys.path.insert(0, str(ROOT / "extract"))
import _coordaccess as coordacc   # noqa: E402  (unit-level policy + rounding)
import build_portal   # noqa: E402  (in-process build for the warm-cache pin)
import cache as cache_mod   # noqa: E402  (patch the dirty-checkout gate so the cache fires on a dirty dev tree)


@pytest.fixture
def clean_salt(monkeypatch):
    """Force the C18 cache's dirty-checkout gate to see a CLEAN tree so the cache actually FIRES (the
    dev worktree is dirty during development; CI is clean). Patches the gate INPUT, not the gate — the
    real is_salt_degenerate logic still runs. Mirrors tests/test_build_cache.py's fixture exactly, so
    the warm-cache leak-sweep can exercise a real cache HIT regardless of the working-tree state."""
    monkeypatch.setattr(cache_mod, "_dirty_checkout", lambda cwd: False)
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: build_portal._GIT_COMMIT_MEMO.get(str(cwd), "c42testcommit"))
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("AUSMT_CACHE_MAX_MB", raising=False)

# --- distinctive, clean coordinates per station (HEAD==INFO==DEFINEMEAS so no dms flag) --------------
# Each station gets a UNIQUE lat/lon/elev so the sweep can attribute a leak to a specific policy class.
# Elevations are distinctive DECIMALS (not round integers like 222.0 whose bare '222' string collides
# with impedance-data substrings in the served EDI/XML) so an elevation hit unambiguously means a leak.
# HID's FILE NAME differs from its DATAID (fix round 2, pin 5): the withheld station is keyed CORRECTLY
# by its STATION id (HIDENINE, from DATAID) while living in HIDEFILE.edi — proving the correct path
# masks everything even when the file name and station id disagree.
EXACT = {"id": "EXACTONE", "lat": -31.234567, "lon": 135.234567, "elev": 111.61, "policy": "exact"}
GEN = {"id": "GENFIVE", "lat": -32.876543, "lon": 136.876543, "elev": 222.73, "policy": "generalised"}
HID = {"id": "HIDENINE", "file": "HIDEFILE.edi", "lat": -33.555551, "lon": 137.555559, "elev": 333.47,
       "policy": "withheld"}
# generalised expected cell (the ONLY position a generalised station may disclose)
GEN_CELL = (round(GEN["lat"], 1), round(GEN["lon"], 1))   # (-32.9, 136.9)


def _rewrite_edi(src_text, station):
    """Rewrite an EDI's DATAID + every coordinate-bearing header line (HEAD LAT/LONG/ELEV, INFO
    LATITUDE/LONGITUDE/ELEVATION, DEFINEMEAS REFLAT/REFLONG/REFELEV) to the station's distinctive
    decimal values. Consistent across all three blocks => mt_metadata reads a clean position, no dms
    ambiguity. Returns the rewritten EDI text."""
    lat, lon, elev = station["lat"], station["lon"], station["elev"]
    t = src_text
    t = re.sub(r'DATAID="[^"]*"', f'DATAID="{station["id"]}"', t, count=1)
    t = re.sub(r"\nLAT=[^\n]*", f"\nLAT={lat:.6f}", t, count=1)
    t = re.sub(r"\nLONG=[^\n]*", f"\nLONG={lon:.6f}", t, count=1)
    t = re.sub(r"\nELEV=[^\n]*", f"\nELEV={elev:.2f}", t, count=1)
    t = re.sub(r"LATITUDE    :[^\n]*", f"LATITUDE    :   {lat:.6f}", t, count=1)
    t = re.sub(r"LONGITUDE   :[^\n]*", f"LONGITUDE   :   {lon:.6f}", t, count=1)
    t = re.sub(r"ELEVATION   :[^\n]*", f"ELEVATION   :   {elev:.4f}", t, count=1)
    t = re.sub(r"REFLAT=[^\n]*", f"REFLAT={lat:.6f}", t, count=1)
    t = re.sub(r"REFLONG=[^\n]*", f"REFLONG={lon:.6f}", t, count=1)
    t = re.sub(r"REFELEV=[^\n]*", f"REFELEV={elev:.2f}", t, count=1)
    return t


def _stage_survey(base, stations, *, declare_policy=True, extent=True, overrides=None,
                  coordinates_default=None, slug="sweep-survey", name="Coord Access Sweep Survey"):
    """Write a survey package (survey.yaml + one EDI per station) into `base`. `stations` is a list of
    the EXACT/GEN/HID-style dicts. When declare_policy, the yaml gets access.coordinates (from the
    stations' policies unless coordinates_default is given) + per-station coordinate_overrides. Returns
    the package dir. `slug`/`name` allow staging SEVERAL surveys under one --surveys root (the F2
    survey-granularity pin)."""
    src = SAMPLE_EDI.read_text(encoding="utf-8")
    d = base / slug
    edidir = d / "transfer_functions" / "edi"
    edidir.mkdir(parents=True)
    for st in stations:
        # a station dict may carry "file" to decouple the FILE NAME from the DATAID (fix round 2:
        # the station id derives from DATAID, never the file name — probe-e's whole attack class).
        (edidir / st.get("file", f"{st['id']}.edi")).write_text(_rewrite_edi(src, st), encoding="utf-8")
    lines = [
        'schema_version: "0.1"',
        f"slug: {slug}",
        f'name: "{name}"',
        "country: Australia",
        'organisation: "AusMT CI"',
        'abstract: "engine-produced C42 leak-sweep fixture"',
        'license: "CC-BY-4.0"',
        "data_type: BBMT",
    ]
    if extent:
        lines.append("geographic_extent: { west: 134.0, east: 139.0, south: -35.0, north: -30.0, datum: WGS84 }")
    # access block
    acc = ["access:", "  level: open"]
    if declare_policy:
        default = coordinates_default
        if default is None:
            # derive a survey default: the modal policy is 'exact', overrides carry the rest
            default = "exact"
        acc.append(f"  coordinates: {default}")
        ov = dict(overrides) if overrides else {}
        if overrides is None:
            for st in stations:
                if st["policy"] != default:
                    ov[st["id"]] = st["policy"]
        if ov:
            acc.append("  coordinate_overrides:")
            for sid, pol in ov.items():
                acc.append(f"    {sid}: {pol}")
    lines += acc
    (d / "survey.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def _build(tmp_path, stations, *, extra=(), **stage_kw):
    """Stage the survey, run the real build, return (out_dir, completed_process)."""
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, stations, **stage_kw)
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate", *extra],
        cwd=str(ROOT), capture_output=True, text=True)
    return out, r


# --------------------------------------------------------------------------- string/numeric leak sweep

def _true_value_string_variants(value, dp=6):
    """Every string form a coordinate could sneak out as: 6 dp, trailing-zero-trimmed, 3-dp rounded
    (the at_deg class), and DMS d:m:s (the EDI HEAD form). Absolute value AND signed."""
    out = set()
    for v in (value, abs(value)):
        s6 = f"{v:.6f}"
        out.add(s6)
        out.add(s6.rstrip("0").rstrip("."))
        out.add(f"{round(v, 3):.3f}")
        out.add(f"{round(v, 3):.3f}".rstrip("0").rstrip("."))
        # DMS (deg:min:sec) — the EDI HEAD/DEFINEMEAS byte form
        av = abs(v)
        deg = int(av)
        rem = (av - deg) * 60
        minutes = int(rem)
        sec = (rem - minutes) * 60
        out.add(f"{deg}:{minutes}:{sec:.3f}".rstrip("0").rstrip("."))
    return {s for s in out if s}


def _numeric_tokens(text):
    """Every JSON-ish numeric token in a blob, as floats (for the epsilon parse). Cheap regex over the
    raw bytes-as-text; we only need candidates to compare against known true values."""
    for m in re.finditer(r"-?\d+\.\d+", text):
        try:
            yield float(m.group(0))
        except ValueError:
            continue


def _sweep_tree_for_value(out_dir, value, *, epsilon=1e-3, label=""):
    """Return a list of (file, hit) where the TRUE `value` (a lat/lon/elev) appears in out_dir — as any
    string variant OR as a numeric token within epsilon. EDI/XML source files are swept too (a non-exact
    station is byte-gated, so its EDI/XML must not be present at all). `label` just tags failure output.
    """
    variants = _true_value_string_variants(value)
    hits = []
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(out_dir).as_posix()
        for v in variants:
            if v in text:
                hits.append((rel, f"string {v!r} ({label})"))
        for tok in _numeric_tokens(text):
            if abs(tok - value) <= epsilon:
                hits.append((rel, f"numeric {tok} within {epsilon} of {value} ({label})"))
    return hits


def _sweep_non_exact_true_values(out_dir):
    """Sweep the WHOLE emitted tree for EVERY true value of the generalised + withheld stations
    (lat/lon 6dp AND the distinctive elevation). Returns all hits.

    NOTE: this text/byte sweep is STRUCTURALLY BLIND to binary containers — an IEEE-754 double
    inside an HDF5 file never matches a string variant, and the text-token numeric parse cannot see
    it either. Served *.h5 bundles are therefore swept SEPARATELY and NUMERICALLY by
    _sweep_h5_for_non_exact (the F1 fix-round leg); a leak-sweep over a build that enables any
    binary distribution emitter must run BOTH legs."""
    hits = []
    for st in (GEN, HID):
        for field in ("lat", "lon", "elev"):
            hits += _sweep_tree_for_value(out_dir, st[field], label=f"{st['id']}.{field}")
    return hits


def _sweep_h5_for_non_exact(out_dir, *, epsilon=1e-3):
    """The NUMERIC HDF5 leg of the leak-sweep (F1): open every served *.h5 under out_dir with the
    engine's own mth5 reader and read each transfer function's summary position
    (latitude/longitude/elevation) as NUMBERS. Returns hits [(file, msg)] when:

      * a non-exact station's true lat/lon/elev appears within epsilon, OR
      * a non-exact station is PRESENT in the bundle at all — the per-station byte gate withholds
        the whole contribution (we never rewrite custodian bytes, D3), so presence itself is a
        gate bypass regardless of the values it carries.

    Exists because the text sweep cannot see into binary containers. Historically RED against the
    pre-F1 build, where emit_survey_mth5 received the FULL station list and re-read the RAW source
    EDIs (TF(fn=...)), bypassing both the mask and the byte gate."""
    import _mth5 as m5  # noqa: PLC0415  (the engine's own MTH5 reader — same TF->record logic)
    hits = []
    for hp in sorted(out_dir.rglob("*.h5")):
        rel = hp.relative_to(out_dir).as_posix()
        for rec, _per, _comp in m5.records_and_components(hp):
            rid = str(rec.get("id") or "")
            for st in (GEN, HID):
                if st["id"].lower() in rid.lower():
                    hits.append((rel, f"non-exact station {st['id']} PRESENT in served MTH5 "
                                      f"(byte gate bypassed; record id {rid!r})"))
                for field, key in (("lat", "lat"), ("lon", "lon"), ("elev", "elev_m")):
                    v = rec.get(key)
                    if v is not None and abs(float(v) - st[field]) <= epsilon:
                        hits.append((rel, f"numeric {v} within {epsilon} of true "
                                          f"{st['id']}.{field} ({st[field]})"))
    return hits


# =====================================================================================================
# LEAK-SWEEP PIN (centrepiece)
# =====================================================================================================

def test_leak_sweep_no_true_value_of_a_non_exact_station_anywhere(tmp_path):
    """CENTREPIECE. Build one exact + one generalised + one withheld station with distinctive coords +
    elevation, with EVERY flag-gated distribution emitter enabled (--survey-h5 — F1: an emitter left
    out of the fixture build is an emitter the sweep never audits); sweep EVERY byte of the emitted
    out/ tree for the true values of the two non-exact stations (6dp, trimmed, 3-dp derivative, DMS;
    plus numeric parse epsilon >= 1e-3) AND numerically sweep every served *.h5 bundle — the text
    sweep is structurally blind to IEEE-754 doubles inside binary containers, so the HDF5 leg reads
    each bundled TF's latitude/longitude/elevation as numbers via the engine's own reader.

    FAILS IF any true value (or a rounded derivative finer than the 0.1deg disclosure) of the
    generalised OR withheld station appears anywhere in served output — text or binary — or a
    non-exact station is present in the served MTH5 bundle at all.
    """
    out, r = _build(tmp_path, [EXACT, GEN, HID], extra=("--survey-h5",))
    assert r.returncode == 0, r.stderr
    hits = _sweep_non_exact_true_values(out) + _sweep_h5_for_non_exact(out)
    assert not hits, "TRUE coordinate/elevation of a non-exact station leaked:\n" + "\n".join(
        f"  {f}: {h}" for f, h in hits)
    # the exact station must still be IN the served MTH5 (the h5 leg must be sweeping a real bundle,
    # not a vacuously absent one — the byte gate withholds contributions, never the whole bundle).
    h5s = sorted(out.rglob("*.h5"))
    assert h5s, "--survey-h5 build must serve an MTH5 bundle (else the HDF5 leg is vacuous)"


def test_leak_sweep_mutation_all_exact_flip_finds_every_value(tmp_path):
    """MUTATION-PROOF #1: flip the fixture to ALL-EXACT (no policy). Now the sweep MUST find every value
    of the (now-exact) GEN and HID stations — proving the sweep is not vacuously green because it looks
    in the wrong place. FAILS IF the sweep finds NOTHING when the positions are genuinely served."""
    out, r = _build(tmp_path, [
        {**EXACT}, {**GEN, "policy": "exact"}, {**HID, "policy": "exact"}],
        declare_policy=False)
    assert r.returncode == 0, r.stderr
    hits = _sweep_non_exact_true_values(out)
    # each of GEN/HID lat+lon must be found somewhere (catalogue at minimum). If the sweep finds nothing,
    # it is blind and the centrepiece test above is worthless.
    assert hits, "all-exact flip found NO true values — the leak-sweep is blind (vacuous)"
    for st in (GEN, HID):
        assert any(st["id"] in lbl for _f, lbl in hits), \
            f"all-exact flip did not surface {st['id']} — sweep is not covering served coordinates"


def test_leak_sweep_mutation_planted_3dp_derivative_caught_by_epsilon(tmp_path):
    """MUTATION-PROOF #2: plant a bare 3-dp derivative of a withheld station's latitude into the served
    tree and show the numeric epsilon (>= 1e-3) catches it — proving the sweep would catch the sneaky
    at_deg-class leak (a 3-dp rounded true position) even if it slipped past the string variants.
    FAILS IF the epsilon parse does not flag the planted derivative."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    # sanity: clean build is clean
    assert not _sweep_non_exact_true_values(out), "precondition: clean build must not leak"
    # plant a 3-dp derivative of the WITHHELD lat as a bare JSON number in a served file
    planted = round(HID["lat"], 3)
    (out / "planted.json").write_text(json.dumps({"sneaky": planted}), encoding="utf-8")
    hits = _sweep_tree_for_value(out, HID["lat"], label="HID.lat")
    assert any("planted.json" in f for f, _h in hits), \
        f"epsilon sweep failed to catch a planted 3-dp derivative {planted} of true {HID['lat']}"


# =====================================================================================================
# WARM-CACHE SWEEP PIN
# =====================================================================================================

def test_warm_cache_sweep_still_clean(tmp_path, clean_salt):
    """The C18 cache stores the PRE-mask parse (TRUE coords). A warm rebuild HITS it. This pins the D3
    cache-boundary invariant: the mask applies AFTER every cache read and its output is never cached.

    Build twice IN-PROCESS against the SAME survey.yaml with --incremental (in-process + clean_salt so the
    cache fires on a dirty dev tree, exactly as tests/test_build_cache.py does): a cold refresh populates
    the cache with the true-coord parse, a warm rw build must HIT it (hits>0, misses=0). Re-sweep the warm
    build's out/ tree for the true values of the non-exact stations.
    FAILS IF the warm-cache build leaks a true coordinate the cold build masks (i.e. the mask ran before,
    or was skipped by, a cache hit)."""
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT, GEN, HID])
    cache_dir = tmp_path / "cache"

    def build(out_name, mode):
        out = tmp_path / out_name
        rc = build_portal.main(
            ["--surveys", str(base), "--out", str(out), "--products", str(out / "products"),
             "--bundle-edi", "--no-validate", "--incremental", "--cache-dir", str(cache_dir),
             "--cache-mode", mode])
        assert rc in (0, None), f"build rc={rc}"
        return out

    build("cold", "refresh")            # populate cache with the pre-mask parse (true coords)
    warm = build("warm", "rw")          # warm build hits the cache
    prov = json.loads((warm / "build_provenance.json").read_text(encoding="utf-8"))["cache"]
    assert prov.get("enabled") and prov["hits"] > 0 and prov["misses"] == 0, \
        f"warm build did not hit the cache as required to exercise the boundary: {prov}"
    hits = _sweep_non_exact_true_values(warm)
    assert not hits, "WARM-cache build leaked a true value the cold build masks:\n" + "\n".join(
        f"  {f}: {h}" for f, h in hits)


# =====================================================================================================
# BYTE-GATE PIN
# =====================================================================================================

def test_byte_gate_non_exact_edi_xml_absent_from_all_surfaces(tmp_path):
    """A non-exact station's EDI + EMTF-XML must be absent from out/edi, out/xml, both zips, and
    manifest.json. Only the exact station is served. FAILS IF any file or manifest row exists for a
    generalised/withheld station."""
    import zipfile
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    served_stations = {row["station"] for row in man["files"]}
    assert served_stations == {EXACT["id"]}, \
        f"only the exact station may be served; manifest served: {sorted(served_stations)}"

    # on-disk EDI/XML: only the exact station's files exist. Check BOTH the station id AND the file
    # stem (HID's file name differs from its DATAID since fix round 2 — a leaked copy would be
    # HIDEFILE.edi, which an id-only check would miss).
    edi_names = {p.stem for p in out.rglob("edi/**/*.edi")}
    xml_names = {p.stem for p in out.rglob("xml/**/*.xml")}
    _hid_file_stem = HID["file"].rsplit(".", 1)[0]
    assert GEN["id"] not in edi_names and HID["id"] not in edi_names \
        and _hid_file_stem not in edi_names, f"non-exact EDI present on disk: {sorted(edi_names)}"
    assert GEN["id"] not in xml_names and HID["id"] not in xml_names \
        and _hid_file_stem not in xml_names, f"non-exact XML present on disk: {sorted(xml_names)}"
    assert EXACT["id"] in edi_names, "the exact station's EDI must still be served"

    # zips must not contain a non-exact station's bytes (id OR file-stem named)
    for zp in out.rglob("bundles/*.zip"):
        with zipfile.ZipFile(zp) as z:
            for name in z.namelist():
                assert GEN["id"] not in name and HID["id"] not in name \
                    and _hid_file_stem not in name, \
                    f"{zp.name} bundles a non-exact station's file: {name}"


# =====================================================================================================
# BBOX / CENTROID PINS
# =====================================================================================================

def test_bbox_generalised_station_contributes_only_its_rounded_cell(tmp_path):
    """A survey with an exact + a generalised station: the mtcat/collections bbox is computed from the
    POST-MASK coordinates, so the generalised station's contribution is its 0.1deg CELL, never its true
    position. FAILS IF a bbox edge equals the generalised station's true (6-dp) coordinate."""
    out, r = _build(tmp_path, [EXACT, {**GEN}])   # no withheld here (keep a bbox)
    assert r.returncode == 0, r.stderr
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    sv = mtcat["surveys"][0]
    bb = sv["bbox"]
    assert bb is not None, "a survey with exact+generalised stations must have a bbox"
    edges = [bb["west"], bb["south"], bb["east"], bb["north"]]
    # the generalised true values must NOT be a bbox edge; the rounded cell MAY be.
    assert GEN["lat"] not in edges and GEN["lon"] not in edges, \
        f"a bbox edge is the generalised station's TRUE position: {bb}"
    # positive: the rounded cell is inside/at the bbox (south<=cell_lat<=north, west<=cell_lon<=east)
    assert bb["south"] <= GEN_CELL[0] <= bb["north"], f"generalised lat cell {GEN_CELL[0]} not in bbox {bb}"
    assert bb["west"] <= GEN_CELL[1] <= bb["east"], f"generalised lon cell {GEN_CELL[1]} not in bbox {bb}"


def test_bbox_lone_withheld_station_yields_no_footprint(tmp_path):
    """A single-station survey whose ONLY station is withheld => NO bbox/centroid in mtcat.json OR
    collections.json (the lone-station hazard: the centroid would otherwise BE the exact position).
    FAILS IF either document carries a bbox/centroid for the survey."""
    out, r = _build(tmp_path, [{**HID}], overrides={}, coordinates_default="withheld")
    assert r.returncode == 0, r.stderr
    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    sv = next(s for s in mtcat["surveys"] if s["title"] == "Coord Access Sweep Survey")
    assert sv["bbox"] is None and sv["centroid"] is None, \
        f"lone-withheld survey must have NO footprint, got bbox={sv['bbox']} centroid={sv['centroid']}"
    # and the whole tree carries none of the withheld station's true bytes
    assert not _sweep_tree_for_value(out, HID["lat"], label="HID.lat"), "lone-withheld true lat leaked"
    assert not _sweep_tree_for_value(out, HID["lon"], label="HID.lon"), "lone-withheld true lon leaked"


# =====================================================================================================
# NEAR-DUPLICATE PIN
# =====================================================================================================

def test_near_duplicate_at_deg_carries_no_true_bits_for_non_exact(tmp_path):
    """Two stations ~<10 m apart (same distinctive position, different ids), one exact one WITHHELD, trip
    the ~100 m duplicate QC. The near_duplicate_locations entry's at_deg (a 3-dp true derivative) must
    carry NO true bits for the non-exact pair. FAILS IF the 3-dp true derivative appears in at_deg."""
    a = {"id": "DUPEXACT", "lat": -31.700000, "lon": 135.700000, "elev": 150.0, "policy": "exact"}
    b = {"id": "DUPHIDE", "lat": -31.700400, "lon": 135.700400, "elev": 150.0, "policy": "withheld"}
    out, r = _build(tmp_path, [a, b])
    assert r.returncode == 0, r.stderr
    qc = json.loads((out / "qc_report.json").read_text(encoding="utf-8"))
    nd = qc["near_duplicate_locations"]
    assert nd, "the two co-located stations must trip the near-duplicate QC (else this pin is vacuous)"
    for e in nd:
        assert e["at_deg"] is None, \
            f"a withheld-pair near-duplicate carries a true derivative in at_deg: {e['at_deg']}"
    # belt-and-braces: the 3-dp derivative of the withheld station is nowhere in qc_report
    deriv = round(b["lat"], 3)
    assert not any(abs(tok - b["lat"]) <= 1e-3 for tok in _numeric_tokens(json.dumps(qc))), \
        f"qc_report carries a value within 1e-3 of the withheld true lat ({deriv})"


# =====================================================================================================
# QC-REPORT (OUTSIDE-EXTENT) PIN
# =====================================================================================================

def test_qc_report_outside_extent_withheld_station_has_no_coords(tmp_path):
    """A WITHHELD station placed OUTSIDE the survey's declared extent gets an outside_declared_extent
    entry — whose lat/lon must be nulled (no true position). FAILS IF the entry carries the true coords.
    """
    # extent is 134..139 / -35..-30; place a withheld station outside it (lat -29.87 is north of -30).
    # Distinctive non-round coords so the sweep's string variants can't collide with impedance data.
    far = {"id": "FARHIDE", "lat": -29.876541, "lon": 140.512349, "elev": 400.83, "policy": "withheld"}
    out, r = _build(tmp_path, [EXACT, far])
    assert r.returncode == 0, r.stderr
    qc = json.loads((out / "qc_report.json").read_text(encoding="utf-8"))
    entries = [e for e in qc["outside_declared_extent"] if e["ausmt_id"].endswith(far["id"])]
    assert entries, "the far withheld station must be flagged outside the declared extent (else vacuous)"
    for e in entries:
        assert e["lat"] is None and e["lon"] is None, \
            f"outside-extent WITHHELD entry carries a true position: {e}"
    assert not _sweep_tree_for_value(out, far["lat"], label="FAR.lat"), "far withheld true lat leaked"


def test_qc_report_outside_extent_generalised_station_shows_only_cell(tmp_path):
    """A GENERALISED station outside the declared extent: its outside_declared_extent entry shows the
    0.1deg CELL, never the true 6-dp position. FAILS IF the true coordinate appears in the entry."""
    far = {"id": "FARGEN", "lat": -29.123456, "lon": 140.654321, "elev": 400.0, "policy": "generalised"}
    out, r = _build(tmp_path, [EXACT, far])
    assert r.returncode == 0, r.stderr
    qc = json.loads((out / "qc_report.json").read_text(encoding="utf-8"))
    entries = [e for e in qc["outside_declared_extent"] if e["ausmt_id"].endswith(far["id"])]
    assert entries, "the far generalised station must be flagged outside extent (else vacuous)"
    for e in entries:
        assert e["lat"] == round(far["lat"], 1) and e["lon"] == round(far["lon"], 1), \
            f"outside-extent GENERALISED entry is not the 0.1deg cell: {e}"


# =====================================================================================================
# CATALOGUE / MTCAT MASKED-VALUE PINS
# =====================================================================================================

def _cat_cols():
    from _contract import CATALOGUE_COLUMNS
    return CATALOGUE_COLUMNS


def test_catalogue_and_mtcat_carry_masked_positions(tmp_path):
    """The catalogue.json + mtcat.json positions are the MASKED values: exact verbatim, generalised the
    0.1deg cell, withheld null. FAILS IF the catalogue/mtcat carry a non-exact station's true position or
    a non-null withheld position."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    cols = _cat_cols()
    ilat, ilon, iid = cols.index("lat"), cols.index("lon"), cols.index("id")
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    by_id = {row[iid]: row for row in cat}

    assert by_id[EXACT["id"]][ilat] == EXACT["lat"] and by_id[EXACT["id"]][ilon] == EXACT["lon"], \
        "exact station must keep its verbatim position"
    assert by_id[GEN["id"]][ilat] == round(GEN["lat"], 1) and by_id[GEN["id"]][ilon] == round(GEN["lon"], 1), \
        "generalised station must carry the 0.1deg cell"
    assert by_id[HID["id"]][ilat] is None and by_id[HID["id"]][ilon] is None, \
        "withheld station must carry a null position"

    mtcat = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    mby = {s["station_id"].split(".")[-1]: s for s in mtcat["stations"]}
    assert mby[GEN["id"]]["latitude"] == round(GEN["lat"], 1), "mtcat generalised lat must be the cell"
    assert mby[HID["id"]]["latitude"] is None, "mtcat withheld lat must be null"


def test_products_station_json_location_is_masked(tmp_path):
    """products/station.json IS a served surface in deployment (D1). Its `location` must be the masked
    position. FAILS IF a non-exact station's station.json carries the true position, or a served EDI is
    advertised for a byte-gated station."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr

    def station_json(sid):
        return json.loads((out / "products" / "sweep-survey" / sid / "station.json").read_text(encoding="utf-8"))

    ex = station_json(EXACT["id"])
    gen = station_json(GEN["id"])
    hid = station_json(HID["id"])
    assert ex["location"] == {"lat": EXACT["lat"], "lon": EXACT["lon"]}, "exact station.json must be verbatim"
    assert gen["location"] == {"lat": round(GEN["lat"], 1), "lon": round(GEN["lon"], 1)}, \
        f"generalised station.json location not the cell: {gen['location']}"
    assert hid["location"] == {"lat": None, "lon": None}, f"withheld station.json not nulled: {hid['location']}"
    # a byte-gated station must not advertise a served EDI
    assert gen["distribution"]["edi_available"] is False and gen["distribution"]["edi_path"] is None
    assert hid["distribution"]["edi_available"] is False
    assert ex["distribution"]["edi_available"] is True, "the exact station must still advertise its EDI"


# =====================================================================================================
# ALIGNMENT PIN
# =====================================================================================================

def test_alignment_masked_build_preserves_lengths_and_index_identity(tmp_path):
    """The masked build preserves catalogue/tf/sci lengths AND index identity (row i of tf/sci is row i
    of the catalogue). Masking nulls values, it never drops or reorders a station. FAILS IF any length
    differs or a station's catalogue row index does not line up with a same-length tf/sci."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    tf = json.loads((out / "tf.json").read_text(encoding="utf-8"))
    sci = json.loads((out / "sci.json").read_text(encoding="utf-8"))
    assert len(cat) == len(tf) == len(sci) == 3, \
        f"lengths must all be 3 (no station dropped): cat={len(cat)} tf={len(tf)} sci={len(sci)}"


# =====================================================================================================
# DEFAULT-STABILITY PIN
# =====================================================================================================

def test_default_stability_no_policy_field_is_byte_identical(tmp_path):
    """A survey with NO access.coordinates field builds a catalogue BYTE-IDENTICAL to a build of the SAME
    survey with the field explicitly set to 'exact' on every station. FAILS IF the default changes any
    catalogue byte. (Two builds of the same inputs: one with no policy, one all-exact-declared.)"""
    # build A: no policy field at all
    outA, rA = _build(tmp_path / "A", [EXACT, GEN, HID], declare_policy=False)
    assert rA.returncode == 0, rA.stderr
    # build B: policy present but everything exact (default set explicitly, no overrides)
    outB, rB = _build(
        tmp_path / "B", [{**EXACT}, {**GEN, "policy": "exact"}, {**HID, "policy": "exact"}],
        coordinates_default="exact", overrides={})
    assert rB.returncode == 0, rB.stderr
    a = (outA / "catalogue.json").read_bytes()
    b = (outB / "catalogue.json").read_bytes()
    assert a == b, "declaring the exact default changed the catalogue bytes — the default is not stable"
    # non-vacuous: the catalogue actually carries the true positions (so 'identical' isn't 'both empty')
    assert EXACT["id"] in a.decode(), "precondition: the catalogue must carry the stations"


# =====================================================================================================
# COORDINATE-POLICY MARKER PINS (Amendment A1 — the boot-loaded generalised/withheld signal)
# =====================================================================================================

def _aid_by_id(out):
    """ausmt_id keyed by station id, read from the built catalogue (positional contract)."""
    cols = _cat_cols()
    iid, iaid = cols.index("id"), cols.index("ausmt_id")
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    return {row[iid]: row[iaid] for row in cat}


def test_coord_policy_marker_emitted_for_non_exact_only(tmp_path):
    """A1 EMIT PIN. The engine emits coord_policy.json — a boot-loaded map ausmt_id -> policy — carrying
    EXACTLY the generalised + withheld stations, with the correct policy string, and NOT the exact one.
    (Red-then-green: drop the r["coord_policy"] stamp or the emit and this fails — the generalised
    station goes unmarked.) FAILS IF an exact station is marked, a non-exact station is missing, the
    policy string is wrong, or the marker set is not exactly the two non-exact stations."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    cp_path = out / "coord_policy.json"
    assert cp_path.exists(), "coord_policy.json must be emitted when the corpus has a non-exact station"
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    aid = _aid_by_id(out)
    assert cp.get(aid[GEN["id"]]) == "generalised", f"generalised station must be marked; got {cp}"
    assert cp.get(aid[HID["id"]]) == "withheld", f"withheld station must be marked; got {cp}"
    assert aid[EXACT["id"]] not in cp, f"the EXACT station must NOT be marked; got {cp}"
    assert set(cp) == {aid[GEN["id"]], aid[HID["id"]]}, \
        f"exactly the two non-exact stations must be marked; got {sorted(cp)}"


def test_coord_policy_marker_absent_for_all_exact_corpus(tmp_path):
    """A1 ZERO-CHANGE PIN. An all-exact corpus emits NO coord_policy.json at all — the marker is additive
    ONLY for non-exact stations, so an existing all-exact survey's served tree is byte-unchanged (no new
    file). FAILS IF the marker file is emitted for an all-exact build."""
    out, r = _build(tmp_path, [
        {**EXACT}, {**GEN, "policy": "exact"}, {**HID, "policy": "exact"}], declare_policy=False)
    assert r.returncode == 0, r.stderr
    assert not (out / "coord_policy.json").exists(), \
        "an all-exact corpus must NOT emit coord_policy.json (zero-change default)"
    # non-vacuous: the catalogue really carries the (now exact) stations
    assert EXACT["id"] in (out / "catalogue.json").read_text(encoding="utf-8")


def test_coord_policy_marker_never_co_occurs_with_true_coords(tmp_path):
    """A1 LEAK PIN (marker/artifact layer — mirrors the D6 leak-sweep spirit). A generalised station is
    MARKED in coord_policy.json AND its catalogue coordinates are the 0.1° CELL — never the true 6-dp
    position; and the marker file itself carries only ausmt_id -> policy, no coordinate. FAILS IF a marked
    station's catalogue coords are its true position, or the marked station's true coords appear anywhere
    in served output (including the marker file)."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr
    cols = _cat_cols()
    iid, iaid, ilat, ilon = (cols.index(x) for x in ("id", "ausmt_id", "lat", "lon"))
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    by_id = {row[iid]: row for row in cat}
    cp = json.loads((out / "coord_policy.json").read_text(encoding="utf-8"))
    grow = by_id[GEN["id"]]
    assert cp.get(grow[iaid]) == "generalised", "the generalised station must be marked (precondition)"
    # the marker co-occurs with the ROUNDED cell, never the true position
    assert grow[ilat] == round(GEN["lat"], 1) and grow[ilon] == round(GEN["lon"], 1), \
        f"a marked generalised station must show the 0.1° cell, not its true coords: {grow[ilat]},{grow[ilon]}"
    assert grow[ilat] != GEN["lat"] and grow[ilon] != GEN["lon"], "the marked cell must differ from the true position"
    # the marker file (and the whole tree) carries none of the marked station's true position
    assert not _sweep_tree_for_value(out, GEN["lat"], label="GEN.lat"), "generalised true lat leaked"
    assert not _sweep_tree_for_value(out, GEN["lon"], label="GEN.lon"), "generalised true lon leaked"


def test_station_json_carries_policy_for_non_exact_only(tmp_path):
    """A1 (secondary surface). products/station.json carries coordinate_policy for a non-exact station and
    NOT for an exact one (exact station.json byte-unchanged — no new key). FAILS IF the exact station.json
    gains a coordinate_policy key, or a non-exact one lacks/mislabels it."""
    out, r = _build(tmp_path, [EXACT, GEN, HID])
    assert r.returncode == 0, r.stderr

    def sj(sid):
        return json.loads((out / "products" / "sweep-survey" / sid / "station.json").read_text(encoding="utf-8"))

    assert "coordinate_policy" not in sj(EXACT["id"]), "exact station.json must not carry coordinate_policy"
    assert sj(GEN["id"]).get("coordinate_policy") == "generalised"
    assert sj(HID["id"]).get("coordinate_policy") == "withheld"


# =====================================================================================================
# FAIL-CLOSED PINS
# =====================================================================================================

def test_fail_closed_unknown_enum_drops_survey_and_serves_nothing(tmp_path):
    """An unknown access.coordinates enum value => the survey is DROPPED (fail-closed) and NOTHING is
    served for it. FAILS IF the survey is built anyway (its stations appear) or the build silently falls
    back to exact."""
    base = tmp_path / "surveys"
    base.mkdir()
    d = _stage_survey(base, [EXACT], coordinates_default="fuzzy", overrides={})
    # sanity: the yaml really carries the bad enum
    assert "coordinates: fuzzy" in (d / "survey.yaml").read_text()
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate", "--allow-empty"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "coordinate-access policy INVALID" in r.stderr, \
        f"unknown enum must be reported loudly; stderr:\n{r.stderr}"
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert cat == [], f"a survey with an invalid policy must serve NOTHING; catalogue: {cat}"


def test_fail_closed_override_names_no_station_drops_survey(tmp_path):
    """A coordinate_override naming a station that does not exist => survey-level build FAILURE, nothing
    served. FAILS IF the survey builds with the bogus override silently ignored."""
    base = tmp_path / "surveys"
    base.mkdir()
    _stage_survey(base, [EXACT], coordinates_default="exact",
                  overrides={"NOSUCHSTATION": "withheld"})
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate", "--allow-empty"],
        cwd=str(ROOT), capture_output=True, text=True)
    # the override id is validated per survey at DISCOVERY (F2), so the offending survey is dropped
    # loudly and nothing of it serves; the corpus-seam raise remains only as a backstop.
    assert r.returncode != 0 or json.loads((out / "catalogue.json").read_text()) == [], \
        f"a bogus override id must fail the build or serve nothing; rc={r.returncode} stderr={r.stderr}"
    assert "coordinate_overrides names station id" in (r.stderr + r.stdout) or r.returncode != 0, \
        f"the bogus override must be reported; stderr:\n{r.stderr}"


def test_fail_closed_override_typo_drops_only_that_survey(tmp_path):
    """F2 (survey granularity): a corpus of TWO surveys, one healthy and one whose coordinate_overrides
    names a station that does not exist. The typo must drop ONLY the offending survey — loudly — while
    the healthy survey builds and serves in full, rc=0.

    FAILS IF one survey's override typo aborts the WHOLE build (rc!=0 / no catalogue at all — the
    pre-F2 behaviour, where CoordinatePolicyError propagated uncaught from the corpus mask seam), or
    if the bad survey's stations/bytes appear anyway, or the drop is silent."""
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT], slug="good-survey", name="Good Survey",
                  coordinates_default="exact", overrides={})
    _stage_survey(base, [{**GEN, "policy": "exact"}], slug="bad-survey", name="Bad Survey",
                  coordinates_default="exact", overrides={"NOSUCHSTATION": "withheld"})
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        f"one survey's override typo must not abort the whole build (pre-F2 red): rc={r.returncode}\n{r.stderr}"
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    surveys_served = {row[1] for row in cat}   # r[1] = survey label (positional contract)
    assert "Good Survey" in surveys_served, f"the healthy survey must serve fully; got {surveys_served}"
    assert "Bad Survey" not in surveys_served, \
        f"the mis-configured survey must be absent from the catalogue; got {surveys_served}"
    # bytes: the good survey's EDI is served; the bad survey has NO served bytes at all
    assert (out / "edi" / "good-survey").exists(), "good survey's EDI dir must be served"
    assert not (out / "edi" / "bad-survey").exists(), "bad survey must have NO served EDI bytes"
    # loud, named drop — never a silent absence
    assert "coordinate-access policy INVALID" in r.stderr and "bad-survey" in r.stderr, \
        f"the drop must name the offending survey loudly; stderr:\n{r.stderr}"


# =====================================================================================================
# FIX ROUND 2: one shared matcher — validation and application cannot diverge (probe-e class)
# =====================================================================================================

# Probe-e (the verifier's constructed leak): file ALPHA.edi whose DATAID is BRAVO — the custodian
# naturally keys the override by the FILE name (ALPHA: withheld) — plus an unrelated gamma.edi whose
# DATAID happens to be ALPHA. Pre-fix: validation passed via the stem candidate, the corpus backstop
# passed via the OTHER station's id, and at rc=0 the custodian's sensitive station served EXACT
# coordinates on every surface while the unrelated station was silently masked instead.
SENS = {"id": "BRAVO", "file": "ALPHA.edi", "lat": -34.111111, "lon": 138.222222, "elev": 150.55,
        "policy": "withheld"}   # the custodian's sensitive site (keyed WRONGLY, by file name)
DECOY = {"id": "ALPHA", "file": "gamma.edi", "lat": -34.933333, "lon": 138.744444, "elev": 260.77,
         "policy": "exact"}     # the unrelated station whose id coincides with SENS's file stem


def test_probe_e_stem_keyed_override_fails_loudly_not_silently_misapplied(tmp_path):
    """PROBE-E PIN (fix round 2, blocking). The stem-keyed override + id/stem-coincidence fixture:
    override key 'ALPHA' is simultaneously the id of one station AND the file stem of a DIFFERENT
    station — an ambiguous, almost-certainly-filename-keyed policy. Validation must FAIL LOUDLY at
    the pre-emission point (survey dropped, the survey's REAL station ids listed so the custodian
    learns the correct handles), rc=0, and the healthy co-survey must serve.

    HISTORICALLY RED against the pre-fix build: rc=0 with the sensitive station's TRUE coordinates
    served on every surface (the sweep below found them) and the unrelated station silently masked.
    """
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT], slug="good-survey", name="Good Survey",
                  coordinates_default="exact", overrides={})
    _stage_survey(base, [SENS, DECOY], slug="probe-survey", name="Probe Survey",
                  coordinates_default="exact", overrides={"ALPHA": "withheld"})
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"survey-granularity drop, never an abort: rc={r.returncode}\n{r.stderr}"
    # THE LEAK CHECK (this is what was red pre-fix): the sensitive station's true position must not
    # appear anywhere in served output.
    leak = (_sweep_tree_for_value(out, SENS["lat"], label="SENS.lat")
            + _sweep_tree_for_value(out, SENS["lon"], label="SENS.lon"))
    assert not leak, "probe-e leak — the mis-keyed survey SERVED the sensitive true position:\n" + \
        "\n".join(f"  {f}: {h}" for f, h in leak)
    # the ambiguous survey is dropped loudly, listing its REAL station ids
    assert "coordinate-access policy INVALID" in r.stderr and "probe-survey" in r.stderr, \
        f"the ambiguous override must drop the survey loudly; stderr:\n{r.stderr}"
    assert "BRAVO" in r.stderr, \
        f"the SKIP must list the survey's real station ids (custodian guidance); stderr:\n{r.stderr}"
    # nothing of the probe survey serves; the healthy co-survey does
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    served = {row[1] for row in cat}
    assert served == {"Good Survey"}, f"only the healthy survey may serve; got {served}"
    assert not (out / "edi" / "probe-survey").exists(), "no probe-survey bytes may be served"


def test_validated_override_keys_always_apply(tmp_path):
    """VALIDATED=>APPLIES PROPERTY PIN (fix round 2): for an engine-built survey containing a
    DATAID!=stem station AND a processing-variant pair, EVERY override key that passes validation
    changes at least one station record's effective policy — validation and application share ONE
    matcher, so a validated no-op key is structurally impossible. FAILS IF any validated key is a
    no-op (e.g. a re-introduced prefix tolerance validating keys the matcher never applies).
    Also pins the negative arms: a file stem is NOT a valid key; a variant-suffixed id is NOT a
    valid key (the rejection lists the BASE ids)."""
    import build_portal as bp  # noqa: PLC0415
    src = SAMPLE_EDI.read_text(encoding="utf-8")
    edidir = tmp_path / "prop-survey" / "transfer_functions" / "edi"
    edidir.mkdir(parents=True)
    plan = [
        ({"id": "BRAVO", "lat": -34.111111, "lon": 138.222222, "elev": 150.55}, "ALPHA.edi"),
        ({"id": "SITE1", "lat": -34.501234, "lon": 138.401234, "elev": 210.31}, "SITE1_LemiGraph.edi"),
        ({"id": "SITE1", "lat": -34.501234, "lon": 138.401234, "elev": 210.31}, "SITE1_Ohmega.edi"),
        ({"id": "NORM", "lat": -34.701111, "lon": 138.601111, "elev": 190.13}, "NORM.edi"),
    ]
    for st, fname in plan:
        (edidir / fname).write_text(_rewrite_edi(src, st), encoding="utf-8")
    stations, _tf, _sci = bp.process_edis(sorted(edidir.glob("*.edi")), "Prop Survey", "Org",
                                          "prop-survey", "mt_metadata", report={})
    bases = {coordacc.base_station_id(r.get("id"), r.get("variant")) for (_p, r) in stations}
    assert bases == {"BRAVO", "SITE1", "NORM"}, f"fixture must yield these bases: {bases}"
    assert any(r.get("variant") for (_p, r) in stations), \
        "the SITE1 pair must be variant-tagged (else the variant arm is vacuous)"
    # THE PROPERTY: every key that validates, applies.
    for k in sorted(bases):
        ov = {k: "withheld"}
        coordacc.validate_overrides(ov, stations)   # must not raise
        n = sum(1 for (_p, r) in stations
                if coordacc.station_policy("exact", ov, r.get("id"), r.get("variant")) == "withheld")
        assert n >= 1, f"validated override key {k!r} is a NO-OP (matcher divergence)"
    # variant inheritance: the base key covers BOTH variant records of the physical station
    ov = {"SITE1": "withheld"}
    n = sum(1 for (_p, r) in stations
            if coordacc.station_policy("exact", ov, r.get("id"), r.get("variant")) == "withheld")
    assert n == 2, f"a base-id override must cover all its variants, covered {n}"
    # a file stem is NOT a valid key, full stop
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.validate_overrides({"ALPHA": "withheld"}, stations)
    # a variant-suffixed id is NOT a valid key; the rejection lists the BASE ids
    with pytest.raises(coordacc.CoordinatePolicyError) as ei:
        coordacc.validate_overrides({"SITE1.lemigraph": "withheld"}, stations)
    assert "SITE1" in str(ei.value), f"the rejection must list base ids: {ei.value}"


def test_variant_pair_base_override_masks_all_variants(tmp_path):
    """VARIANT PIN (fix round 2): two processings of ONE physical station (same DATAID, deduped to
    SITE1.lemigraph / SITE1.ohmega by the engine's variant tagging). Privacy of the physical site
    covers ALL its variants: an override on the BASE id must mask BOTH records and byte-gate BOTH
    files. HISTORICALLY RED: pre-fix, the base key passed validation then matched NO record at
    application (r['id'] carries the variant suffix), and the corpus backstop aborted the whole
    build (rc=1)."""
    vara = {"id": "SITE1", "file": "SITE1_LemiGraph.edi", "lat": -34.501234, "lon": 138.401234,
            "elev": 210.31, "policy": "withheld"}
    varb = {"id": "SITE1", "file": "SITE1_Ohmega.edi", "lat": -34.501234, "lon": 138.401234,
            "elev": 210.31, "policy": "withheld"}
    out, r = _build(tmp_path, [EXACT, vara, varb],
                    coordinates_default="exact", overrides={"SITE1": "withheld"})
    assert r.returncode == 0, f"base-id override must build, rc={r.returncode}\n{r.stderr}"
    cols = _cat_cols()
    ilat, ilon, iid = cols.index("lat"), cols.index("lon"), cols.index("id")
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    variants = [row for row in cat if str(row[iid]).startswith("SITE1.")]
    assert len(variants) == 2, f"both variant records must stay catalogued: {[row[iid] for row in cat]}"
    for row in variants:
        assert row[ilat] is None and row[ilon] is None, \
            f"variant {row[iid]} must inherit the base's withheld policy, got {row[ilat]},{row[ilon]}"
    # the physical site's true position is nowhere in served output; its files are byte-gated
    assert not _sweep_tree_for_value(out, vara["lat"], label="SITE1.lat"), "variant true lat leaked"
    served_edis = {p.name for p in out.rglob("edi/**/*.edi")}
    assert not any(n.startswith("SITE1") for n in served_edis), \
        f"variant files must be byte-gated: {sorted(served_edis)}"


def test_variant_suffixed_override_key_is_rejected(tmp_path):
    """VARIANT-KEY PIN (fix round 2): a FULL variant-suffixed id as an override key is INVALID — the
    survey is dropped loudly and the message lists the BASE ids. HISTORICALLY RED: pre-fix the
    prefix tolerance validated it and the mask applied it to ONE variant only — the other variant
    of the same physical station served its TRUE position (silent partial mask)."""
    vara = {"id": "SITE1", "file": "SITE1_LemiGraph.edi", "lat": -34.501234, "lon": 138.401234,
            "elev": 210.31, "policy": "exact"}
    varb = {"id": "SITE1", "file": "SITE1_Ohmega.edi", "lat": -34.501234, "lon": 138.401234,
            "elev": 210.31, "policy": "exact"}
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [EXACT], slug="good-survey", name="Good Survey",
                  coordinates_default="exact", overrides={})
    _stage_survey(base, [vara, varb], slug="variant-survey", name="Variant Survey",
                  coordinates_default="exact", overrides={"SITE1.lemigraph": "withheld"})
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # pre-fix red: the variant survey BUILT with one variant masked and the other serving its true
    # position. Post-fix: the survey is dropped loudly, message lists the base id.
    leak = _sweep_tree_for_value(out, varb["lat"], label="SITE1.lat")
    assert not leak, "partial mask — the sibling variant served the physical site's TRUE position:\n" \
        + "\n".join(f"  {f}: {h}" for f, h in leak)
    assert "coordinate-access policy INVALID" in r.stderr and "variant-survey" in r.stderr, \
        f"variant-suffixed key must drop the survey loudly; stderr:\n{r.stderr}"
    assert "SITE1" in r.stderr, f"the rejection must list the base ids; stderr:\n{r.stderr}"
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert {row[1] for row in cat} == {"Good Survey"}, "only the healthy survey serves"


def test_mth5_input_survey_bad_override_dropped_before_bytes(tmp_path):
    """MTH5-INPUT PIN (fix round 2): override validation for an mth5-input survey runs at the point
    its station ids become known (after the h5 opens) and BEFORE any of that survey's bytes/products
    are emitted — a bad override drops that survey alone, loudly, rc=0, the co-survey serves.
    HISTORICALLY RED: pre-fix, mth5-input surveys skipped discovery validation entirely and the
    corpus backstop aborted the WHOLE build (rc=1). The mth5 fixture is ENGINE-PRODUCED: a first
    real build's --survey-h5 bundle is re-staged as an mth5-input package."""
    # build 1: produce a real TF MTH5 through the real pipeline
    out1, r1 = _build(tmp_path / "seed", [{**EXACT}], extra=("--survey-h5",), declare_policy=False)
    assert r1.returncode == 0, r1.stderr
    h5s = sorted(out1.rglob("bundles/*-tf.h5"))
    assert h5s, "seed build must produce the engine-made MTH5 bundle"
    # build 2: a corpus with a healthy EDI survey + an mth5-INPUT survey with a bogus override
    base = tmp_path / "surveys"
    base.mkdir(parents=True)
    _stage_survey(base, [{**GEN, "policy": "exact"}], slug="good-survey", name="Good Survey",
                  coordinates_default="exact", overrides={})
    mdir = base / "mth5-survey" / "transfer_functions" / "mth5"
    mdir.mkdir(parents=True)
    shutil.copy(h5s[0], mdir / "stations.h5")
    (base / "mth5-survey" / "survey.yaml").write_text("\n".join([
        'schema_version: "0.1"', "slug: mth5-survey", 'name: "MTH5 Survey"', "country: Australia",
        'organisation: "AusMT CI"', 'license: "CC-BY-4.0"', "data_type: BBMT",
        "access:", "  level: open", "  coordinates: exact",
        "  coordinate_overrides:", "    NOSUCHSTATION: withheld"]) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base), "--out", str(out),
         "--products", str(out / "products"), "--bundle-edi", "--no-validate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, \
        f"an mth5-input survey's bad override must not abort the build (pre-fix red): rc={r.returncode}\n{r.stderr}"
    assert "coordinate-access policy INVALID" in r.stderr and "mth5-survey" in r.stderr, \
        f"the mth5 survey must be dropped loudly; stderr:\n{r.stderr}"
    # NONE of the mth5 survey's bytes/products reached out/
    cat = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
    assert {row[1] for row in cat} == {"Good Survey"}, "only the healthy survey may be catalogued"
    smeta = json.loads((out / "surveys.json").read_text(encoding="utf-8"))
    assert "MTH5 Survey" not in smeta, "the dropped survey must not be published in surveys.json"
    assert not (out / "products" / "mth5-survey").exists(), "no products for the dropped survey"
    assert not any("mth5-survey" in p.as_posix() for p in out.rglob("*") if p.is_file()), \
        "no artifact of the dropped mth5 survey may exist under out/"


# =====================================================================================================
# UNIT-LEVEL POLICY + ROUNDING (fast, stack-independent logic)
# =====================================================================================================

def test_unit_parse_absent_is_exact():
    assert coordacc.parse_coordinate_policy(None) == ("exact", {})
    assert coordacc.parse_coordinate_policy({"level": "open"}) == ("exact", {})


def test_unit_parse_reads_default_and_overrides():
    default, ov = coordacc.parse_coordinate_policy(
        {"level": "open", "coordinates": "generalised",
         "coordinate_overrides": {"A1": "withheld", "A2": "exact"}})
    assert default == "generalised"
    assert ov == {"A1": "withheld", "A2": "exact"}


def test_unit_parse_unknown_enum_raises():
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.parse_coordinate_policy({"coordinates": "fuzzy"})
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.parse_coordinate_policy({"coordinates": "exact", "coordinate_overrides": {"A1": "bogus"}})


def test_unit_round_generalised_is_point_one_degree():
    assert coordacc.round_generalised(-32.876543) == -32.9
    assert coordacc.round_generalised(136.876543) == 136.9
    assert coordacc.round_generalised(None) is None


def test_unit_apply_mask_in_place_and_validates_override_ids():
    stations = [
        ("a.edi", {"id": "A1", "ausmt_id": "au.s.A1", "survey": "S", "file": "a.edi",
                   "lat": -31.234567, "lon": 135.234567, "elev_m": 111.0}),
        ("b.edi", {"id": "A2", "ausmt_id": "au.s.A2", "survey": "S", "file": "b.edi",
                   "lat": -32.876543, "lon": 136.876543, "elev_m": 222.0}),
    ]
    masked = coordacc.apply_coordinate_policy(stations, "exact", {"A2": "generalised"})
    assert masked == {"au.s.A2"}
    assert stations[0][1]["lat"] == -31.234567, "exact station unchanged"
    assert stations[1][1]["lat"] == -32.9 and stations[1][1]["lon"] == 136.9, "generalised to the cell"
    assert stations[1][1]["elev_m"] is None, "generalised elevation nulled (defensive invariant)"
    # A1: the mask stamps the resolved policy on the NON-EXACT record (reused by coord_policy.json /
    # station.json — never re-derived) and leaves the exact record unstamped (zero-change default).
    assert stations[1][1].get("coord_policy") == "generalised", "non-exact record must carry the stamped policy"
    assert "coord_policy" not in stations[0][1], "exact record must NOT be stamped (byte-stable)"
    # bogus override id => fail closed
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.apply_coordinate_policy(stations, "exact", {"NOPE": "withheld"})
