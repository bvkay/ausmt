"""C46-W2: pin _license_text.license_instrument_text against the shared vector file that the JS mirror
(portal/src/exports.js licenseInstrumentText) also consumes, so the two implementations of the licence
INSTRUMENT text cannot drift. Each vector's `expected` is this leaf's own output (the single-source
oracle); portal/tests/license_text_vectors.test.js asserts the JS mirror reproduces the SAME bytes.

NON-VACUOUS failure criteria:
  * license_instrument_text(inputs) == vector.expected for EVERY vector — the mutation target: change
    the renderer (drop the changes clause, reorder a block, change a word) or corrupt one expected value
    and exactly that vector reds (and the same corruption reds the JS side).
  * the vectors actually exercise the ga/generic/supersession/changes/none classes (else a hollow file).
  * the none-of-the-new vector is byte-identical to a fresh None-path render — the frozen-pin spine.
Stdlib only.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
import _license_text as lt   # noqa: E402

_VECTORS = HERE / "fixtures" / "license_instrument_vectors.json"


def _load():
    return json.loads(_VECTORS.read_text(encoding="utf-8"))


def _render(v):
    return lt.license_instrument_text(v["lic"], v["licensor"], v["year"], attribution=v["attribution"],
                                      sources=v["sources"], changes=v["changes"])


def test_instrument_matches_shared_vectors():
    # FAILS IF the leaf's output diverges from any committed vector — the same file the JS mirror is held
    # to, so a rendering change that this file does not also update reds here AND in the jsdom test.
    mism = [v["name"] for v in _load()["vectors"] if _render(v) != v["expected"]]
    assert not mism, f"license_instrument_text diverged from license_instrument_vectors.json: {mism}"


def test_vectors_cover_the_new_rendering_classes():
    # Non-vacuity guard: the file must exercise the classes the C46 additions exist FOR. FAILS if any is
    # missing — a file of only none/attribution vectors would be a hollow oracle.
    kinds = " ".join(v["kind"] for v in _load()["vectors"])
    for needed in ("none", "generic", "ga_derivative", "ga_attribution", "supersession", "changes",
                   "statement", "multi", "disclaimer"):
        assert needed in kinds, f"license_instrument vectors miss the {needed!r} class"


def test_expected_strings_carry_the_distinctive_wording():
    # Non-vacuity of the EXPECTED strings themselves (independent of the render): the ga-derivative
    # vector must literally carry GA's derivative wording + supersession + the §3(a) clause; the
    # ga-attribution (no-changes) vector must carry the © line and NO changes clause. So a vector file
    # of trivial cases can't masquerade as coverage.
    by = {v["name"]: v["expected"] for v in _load()["vectors"]}
    ga = by["ga_source_derivative_supersession"]
    # the GA derivative form uses the SOURCE's `retrieved` year (2016), not the release year (2025).
    assert "Based on AusLAMP SA" in ga and "by Geoscience Australia (2016)" in ga
    assert "The upstream dataset was obtained under CC-BY-3.0-AU" in ga
    assert "AusMT serves derived renditions" in ga
    att = by["ga_source_attribution_no_changes"]
    # ASCII-safe needle (avoids a non-ASCII literal in this source file); the © prefix + byte parity are
    # asserted by the byte-for-byte vector match on both mirrors. Year is the retrieved year (2016).
    assert "Commonwealth of Australia (Geoscience Australia) 2016" in att
    assert "AusMT serves derived renditions" not in att
    # C46-W3a: the GA profile's s.5 DISCLAIMER renders as the final Source-datasets paragraph — even in
    # the no-changes vector, and even when a source supplies a verbatim statement; a generic-only source
    # never carries it. This is the mutation target for the disclaimer render (flip a word and it reds).
    assert "Geoscience Australia has not evaluated the data" in att
    assert "gives no warranty regarding its accuracy" in att
    assert "has not evaluated" in by["source_verbatim_statement"]      # profile-level, survives a statement
    assert "has not evaluated" not in by["generic_source_same_licence"]  # generic profile: no disclaimer
    # a verbatim custodian statement wins over the profile rendering
    assert "verbatim required attribution" in by["source_verbatim_statement"]


def test_none_path_vector_is_byte_stable():
    # The frozen-pin spine: the none-of-the-new vector equals a fresh None-path render (no sources, no
    # changes) — i.e. the pre-C46 instrument bytes. FAILS if the None-path ever shifts.
    v = next(x for x in _load()["vectors"] if x["kind"] == "none")
    assert v["expected"] == lt.license_instrument_text(v["lic"], v["licensor"], v["year"])
