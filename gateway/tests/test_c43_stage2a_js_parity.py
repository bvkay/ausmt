"""C43-S2a fix round F3: EXECUTABLE JS↔Python parity pins for the Stations-tab classification and
URL construction (modelled on portal/tests/test_interactions.py's node-driver pattern).

WHY EXECUTABLE: the fix round's F1 (JS truncated `%` vs Python floored `%` on negatives — 362 trueYx
mismatches and a verdict flip at stored≈−0.05) SHIPPED PAST the source-string parity pin, which only
asserted the JS *contains* certain substrings. These pins EXECUTE the extracted JS functions in Node
and compare against gateway.phaseqc (the authoritative spec) over a boundary-heavy vector set, so a
semantics divergence — not just a missing substring — goes red.

Node dependency posture (stated for the gate): pure `node` only — NO jsdom, NO npm install, no new
deps (the extracted functions are DOM-free). Local dev box: node v22 present. Gateway CI
(gateway-ci.yml, ubuntu-latest): node is preinstalled on GitHub-hosted runners, so these pins RUN in
CI. If node were ever absent, the pytest.skip reason below is deliberately NOT on the gateway lane's
skip-tripwire allow-list (engine/tests/ci_check_skips.py --allow "real engine stack / ..."), so the
lane would fail LOUDLY rather than silently hollowing these pins out — the house tripwire posture.

Vector-set note: the sweep uses 0.5°-step values plus 2dp seam values (0, ±0.05, ±90, ±180, …).
Exact x.25-style binary-representable decimal halves are deliberately excluded — Python round() is
round-half-even while JS Math.round is half-up, and the pin exists to catch MODULO/BAND semantics
divergence, not decimal-rounding-convention differences on inputs the 1dp tf.json data cannot carry.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from gateway import curatorpage, phaseqc, publish

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason="node not present — executable JS parity pins need the node binary "
           "(deliberately NOT on the gateway skip-tripwire allow-list: absent node in CI must red the lane)")


# --------------------------------------------------------------------------------------------------
# JS extraction helpers (brace-balanced, so multi-line functions extract whole)
# --------------------------------------------------------------------------------------------------
def _extract_js_function(js: str, name: str) -> str:
    marker = f"function {name}("
    i = js.find(marker)
    assert i >= 0, f"function {name} not found in STATIONS_JS"
    j = js.find("{", i)
    depth = 0
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i:k + 1]
    raise AssertionError(f"unbalanced braces extracting {name} from STATIONS_JS")


def _extract_constants(js: str) -> str:
    m = re.search(r"var YX_SHIFT[^;]*;", js)
    assert m, "the phase-constant declaration (var YX_SHIFT = ...) not found in STATIONS_JS"
    return m.group(0)


def _run_node(tmp_path, driver_js: str, payload) -> dict:
    drv = tmp_path / "parity_driver.mjs"
    vec = tmp_path / "vectors.json"
    drv.write_text(driver_js, encoding="utf-8")
    vec.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run([NODE, str(drv), str(vec)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"node driver failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


def _sweep_vectors() -> list:
    """Full ±360 sweep at 0.5° steps plus the seam values the fix round names (0, −0.05, ±90, ±180)
    and their near-boundary neighbours (band edges ± slack edges)."""
    vals = [x / 2.0 for x in range(-720, 721)]                       # -360.0 .. 360.0 step 0.5
    vals += [0.0, -0.05, 0.05, 90.0, -90.0, 180.0, -180.0,
             -0.1, 0.1, 89.95, 90.05, -89.95, -90.05, 179.95, -179.95,
             10.0, -10.0, 100.0, -100.0, 99.95, 100.05, -190.0, -80.0,
             -10.05, -9.95, 109.95, 110.05]                          # slack-edge probes
    return vals


# --------------------------------------------------------------------------------------------------
# F1: wrap180 / trueYx / inQ1 / inQ3 parity (executable — Node vs phaseqc)
# --------------------------------------------------------------------------------------------------
def test_js_wrap180_trueyx_quadrant_parity_sweep(tmp_path):
    """EXECUTABLE PARITY (F1). The extracted STATIONS_JS wrap180/trueYx/inQ1/inQ3 must agree EXACTLY
    with phaseqc over the full ±360 sweep + seam values. FAILS IF the JS modulo/band semantics diverge
    from the Python spec anywhere in the domain — in particular the truncated-% bug: JS `%` keeps the
    dividend's sign, so a negative stored t[4] (exactly the wrong-convention stations this feature
    exists to catch) unwraps to the wrong value and flips the verdict (shown red against the pre-fix
    JS: 362 trueYx mismatches, verdict flip at stored≈−0.05)."""
    js = curatorpage.STATIONS_JS
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_constants(js) + "\n"
        + _extract_js_function(js, "floormod") + "\n"
        + _extract_js_function(js, "wrap180") + "\n"
        + _extract_js_function(js, "trueYx") + "\n"
        + _extract_js_function(js, "mapYx") + "\n"
        + _extract_js_function(js, "inQ1") + "\n"
        + _extract_js_function(js, "inQ3") + "\n"
        + """
const vectors = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = vectors.map(function (v) {
  return { v: v, trueYx: trueYx(v), inQ1: inQ1(v), inQ3: inQ3(v) };
});
process.stdout.write(JSON.stringify(out));
""")
    vectors = _sweep_vectors()
    got = _run_node(tmp_path, driver, vectors)
    mismatches = []
    for row in got:
        v = row["v"]
        exp_true = phaseqc.true_phi_yx(v)
        exp_q1 = phaseqc.in_quadrant_xy(v)
        exp_q3 = phaseqc.in_quadrant_yx(v)
        if row["trueYx"] != exp_true or row["inQ1"] != exp_q1 or row["inQ3"] != exp_q3:
            mismatches.append(
                f"stored={v}: JS trueYx={row['trueYx']} inQ1={row['inQ1']} inQ3={row['inQ3']} "
                f"!= py trueYx={exp_true} inQ1={exp_q1} inQ3={exp_q3}")
    assert not mismatches, (
        f"{len(mismatches)} JS/Python mismatches over {len(vectors)} vectors; first 8:\n"
        + "\n".join(mismatches[:8]))


# --------------------------------------------------------------------------------------------------
# F2: URL construction parity (executable — absolute /data/... URLs, tricky slug/id encoding)
# --------------------------------------------------------------------------------------------------
def test_js_data_urls_absolute(tmp_path):
    """EXECUTABLE URL PIN (F2). The extracted STATIONS_JS dataUrl/stationJsonUrl must produce the
    exact expected ABSOLUTE strings for a tricky slug/id (space, plus, hash — hash unencoded would
    truncate the URL at a fragment). ALSO asserts (source-level) that EVERY fetchJson target in the
    JS is absolute (/data/... or a variable built from these helpers). FAILS IF any fetch is
    page-relative — from /gateway/curator/survey/<slug> a relative 'data/...' resolves to
    /gateway/curator/survey/data/... → 404 → the whole Stations tab is dead (the shipped pre-fix
    state, shown red)."""
    js = curatorpage.STATIONS_JS
    # Source-level half: every literal fetchJson('...') target must start /data/.
    literals = re.findall(r"fetchJson\('([^']+)'", js)
    relative = [u for u in literals if not u.startswith("/data/")]
    assert not relative, f"page-relative fetch targets in STATIONS_JS (dead in deployment): {relative}"
    # Executable half: the URL helpers produce exactly the expected absolute encoded strings.
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "dataUrl") + "\n"
        + _extract_js_function(js, "stationJsonUrl") + "\n"
        + """
const out = {
  cat: dataUrl('catalogue.json'),
  tf: dataUrl('tf.json'),
  station: stationJsonUrl('my survey+2026', 'S01 A#7'),
};
process.stdout.write(JSON.stringify(out));
""")
    got = _run_node(tmp_path, driver, {})
    assert got["cat"] == "/data/catalogue.json", got
    assert got["tf"] == "/data/tf.json", got
    assert got["station"] == "/data/products/my%20survey%2B2026/S01%20A%237/station.json", got


# --------------------------------------------------------------------------------------------------
# F4d: classify (slack + median) parity (executable — series semantics, seam-straddling medians)
# --------------------------------------------------------------------------------------------------
def test_js_classify_median_parity(tmp_path):
    """EXECUTABLE SERIES PARITY (F4d). The extracted STATIONS_JS classify (slack-widened per-point
    flags + seam-mapped median + median-vs-band verdict) must agree exactly with
    phaseqc.classify_series over boundary-heavy series, including a yx cluster straddling the ±180
    seam (where a naive median of (−180,180]-wrapped values is catastrophically wrong). FAILS IF the
    JS median/slack semantics diverge from the pinned Python spec."""
    js = curatorpage.STATIONS_JS
    driver = (
        "import { readFileSync } from 'fs';\n"
        + _extract_constants(js) + "\n"
        + _extract_js_function(js, "floormod") + "\n"
        + _extract_js_function(js, "wrap180") + "\n"
        + _extract_js_function(js, "trueYx") + "\n"
        + _extract_js_function(js, "mapYx") + "\n"
        + _extract_js_function(js, "inQ1") + "\n"
        + _extract_js_function(js, "inQ3") + "\n"
        + _extract_js_function(js, "medianOf") + "\n"
        + _extract_js_function(js, "classify") + "\n"
        + """
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(function (c) { return classify(c.values, c.mode); });
process.stdout.write(JSON.stringify(out));
""")
    def _stored_for_true_yx(t):
        return round(phaseqc.wrap180(t + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)

    cases = [
        # xy: in-band, slack-band, and beyond-slack points; median inside the band.
        {"mode": "xy", "values": [10.0, 45.0, 95.0, -5.0, 200.0, None]},
        # xy: median beyond band+slack (coherent wrong quadrant).
        {"mode": "xy", "values": [-120.0, -130.0, -140.0]},
        # yx: healthy Q3 cluster (stored values for true -135/-100/-170).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-135.0, -100.0, -170.0)]},
        # yx: SEAM-STRADDLING cluster — true values -179, -178, +179 (stored 1.0, 2.0, -1.0). A naive
        # (-180,180] median would average across the seam; the engine's (-360,0] mapping keeps it sane.
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-179.0, -178.0, 179.0)]},
        # yx: coherent wrong quadrant (true +45/+30 => stored -135/-150).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (45.0, 30.0)]},
        # yx: slack-edge points (true -85 => within slack; true -75 => beyond slack).
        {"mode": "yx", "values": [_stored_for_true_yx(t) for t in (-85.0, -75.0, -135.0)]},
        # all-None: no verdict.
        {"mode": "xy", "values": [None, None]},
    ]
    got = _run_node(tmp_path, driver, cases)
    for i, case in enumerate(cases):
        exp = phaseqc.classify_series(case["values"], mode=case["mode"])
        g = got[i]
        assert g["points"] == exp["points"], (i, case, g, exp)
        assert g["any_out"] == exp["any_out"], (i, case, g, exp)
        assert g["n"] == exp["n_classified"], (i, case, g, exp)
        assert g["median"] == exp["median"], (i, case, g["median"], exp["median"])
        assert g["medianIn"] == exp["median_in"], (i, case, g, exp)


# ==================================================================================================
# H1 (C43-S2a-HOTFIX): the Stations-tab row filter, driven by an ENGINE-PRODUCED catalogue.
#
# THE LESSON IS THE PIN: the merged Stage-2a filter compared the catalogue `survey` column to the
# hub's SLUG, but the engine writes the survey display LABEL there (build_portal.py:
# r["survey"] = survey_label) — zero matches, Stations tab blank on EVERY production survey
# (owner-reported 2026-07-11). No pin caught it because none drove the filter with rows the ENGINE
# produced. These pins run the REAL engine (the same _run_preview seam the gateway uses) over the
# engine's own sample survey and drive the EXTRACTED filter function with the emitted catalogue —
# hand-built rows are banned here by design.
#
# Skip posture: the engine stack (mt_metadata) is absent in the stackless gateway CI lane, so these
# pins skip there with EXACTLY the lane's one allow-listed tripwire reason (gateway-ci.yml --allow);
# on the dev box (ausmt env) and the engine lanes they RUN. Node-absent boxes hit the file-level
# pytestmark above, which is deliberately NOT allow-listed.
# ==================================================================================================
_ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"
# EXACTLY the gateway lane's one allow-listed skip reason (.github/workflows/gateway-ci.yml --allow).
_ENGINE_SKIP_REASON = "real engine stack / sample survey / validator not present"


def _has_real_engine() -> bool:
    """Mirrors test_runner.py's precondition for the no-mocks engine e2e: mt_metadata importable +
    the sample survey + a validator (sibling or vendored — _run_preview's in-build validation needs
    one). The mt_metadata requirement is what legitimately skips the H1 engine-truth pins in the
    stackless gateway lane."""
    import importlib.util

    from gateway.tests.conftest import resolve_validator_dir
    return (importlib.util.find_spec("mt_metadata") is not None
            and (_ENGINE_DIR / "data" / "sample-survey" / "survey.yaml").is_file()
            and resolve_validator_dir() is not None)


@pytest.fixture(scope="module")
def engine_corpus(tmp_path_factory):
    """A REAL engine-built corpus (catalogue/sci/tf + the slug-keyed products/ tree) over the
    engine's own 2-EDI sample survey, laid out as TWO surveys whose slugs are chosen so one is a
    PROPER PREFIX of the other (burra-2017 / burra-2017-18) — the filter pin must prove the
    trailing-dot survey boundary in 'au.<slug>.', not just non-emptiness. Labels (survey.yaml
    `name`) deliberately differ from slugs, as on every real survey."""
    if not _has_real_engine():
        pytest.skip(_ENGINE_SKIP_REASON)
    import time

    from gateway.runner import runner as gw_runner
    from gateway.runner.runner import RunnerConfig
    from gateway.tests.conftest import require_validator_dir
    base = tmp_path_factory.mktemp("h1-engine-corpus")
    sample = _ENGINE_DIR / "data" / "sample-survey"
    surveys = {"burra-2017": "Burra Reconnaissance 2017", "burra-2017-18": "Burra 2017-18"}
    sy = (sample / "survey.yaml").read_text(encoding="utf-8")
    assert "slug: sample-survey" in sy and 'name: "CI Sample Survey"' in sy, (
        "sample survey.yaml drifted — the two-survey fixture derives from its slug/name lines")
    pkg = base / "package"
    for slug, label in surveys.items():
        d = pkg / slug
        (d / "transfer_functions" / "edi").mkdir(parents=True)
        (d / "survey.yaml").write_text(
            sy.replace("slug: sample-survey", f"slug: {slug}")
              .replace('name: "CI Sample Survey"', f'name: "{label}"'), encoding="utf-8")
        for edi in sorted((sample / "transfer_functions" / "edi").glob("*.edi")):
            shutil.copy(edi, d / "transfer_functions" / "edi" / edi.name)
    cfg = RunnerConfig(incoming_dir=base / "incoming", quarantine_dir=base / "quarantine",
                       jobs_dir=base / "jobs", validator_path=str(require_validator_dir()),
                       timeout_s=900, engine_dir=_ENGINE_DIR)
    out = base / "preview-data"
    summary_path = base / "preview-summary.json"
    ok = gw_runner._run_preview(cfg, pkg, out, summary_path, deadline=time.monotonic() + 600)
    assert ok, f"real engine preview build failed: {summary_path.read_text(encoding='utf-8')}"
    corpus = {name: json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
              for name in ("catalogue", "sci", "tf")}
    corpus["surveys"] = surveys
    corpus["products"] = out / "products"
    return corpus


def test_stations_filter_selects_engine_built_rows_by_slug(engine_corpus, tmp_path):
    """H1 EXECUTABLE ENGINE-TRUTH PIN. The extracted STATIONS_JS row filter (surveyRows), driven in
    Node with the catalogue the REAL ENGINE emitted, must return EXACTLY the stations the engine
    built for each slug — judged against the engine's own slug-keyed products/<slug>/ tree, an
    INDEPENDENT observable (the products tree is keyed by slug on disk; the catalogue rows carry
    the label). FAILS IF the filter misses a station the engine built for the slug (the shipped
    Stage-2a defect: label-vs-slug compare matched nothing — shown red 2026-07-11, 0 of 2 rows for
    both fixture slugs) OR pulls a sibling survey's rows across the trailing-dot boundary
    (au.burra-2017. must not match au.burra-2017-18.*, and vice versa)."""
    js = curatorpage.STATIONS_JS
    cmap = re.search(r"var C = \{.*?\};", js, re.DOTALL)
    assert cmap, "the catalogue column map (var C = {...}) not found in STATIONS_JS"
    driver = (
        "import { readFileSync } from 'fs';\n"
        + cmap.group(0) + "\n"
        + _extract_js_function(js, "surveyRows") + "\n"
        + """
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const slug of p.slugs) {
  out[slug] = surveyRows(p.cat, p.sci, p.tf, slug).map(function (r) {
    return { id: r.cat[C.id], ausmt_id: r.cat[C.ausmt_id], survey_col: r.cat[C.survey],
             sc: r.sc !== null, tf: r.tf !== null };
  });
}
process.stdout.write(JSON.stringify(out));
""")
    slugs = sorted(engine_corpus["surveys"])
    got = _run_node(tmp_path, driver, {
        "cat": engine_corpus["catalogue"], "sci": engine_corpus["sci"],
        "tf": engine_corpus["tf"], "slugs": slugs})
    for slug in slugs:
        label = engine_corpus["surveys"][slug]
        built = sorted(p.name for p in (engine_corpus["products"] / slug).iterdir())
        assert built, f"fixture sanity: the engine built no stations for {slug}"
        rows = got[slug]
        assert sorted(r["id"] for r in rows) == built, (
            f"slug {slug!r}: filter selected {sorted(r['id'] for r in rows)} but the engine built "
            f"{built} (products/{slug}/) — a missed station blanks the Stations tab; an extra one "
            f"leaks a sibling survey across the au.<slug>. boundary")
        for r in rows:
            assert r["ausmt_id"].startswith(f"au.{slug}."), (slug, r)
            assert r["sc"] and r["tf"], f"index-aligned sci/tf must join for {r['ausmt_id']}"
            # ENGINE TRUTH, pinned where the defect lived: the catalogue survey column carries the
            # display LABEL, never the slug. If the engine ever changes that, this narrates the seam.
            assert r["survey_col"] == label != slug, (
                f"engine semantics drifted: catalogue survey column is {r['survey_col']!r}, "
                f"expected the display label {label!r} (never the slug)")


def test_engine_slugs_are_safe_component_fixed_points(engine_corpus):
    """H1 VERIFY-GATE PIN, engine-truth form (architect ruling 2026-07-11). The 'au.' + slug + '.'
    prefix join is exact ONLY because every slug that can reach the hub is a safe_component FIXED
    POINT: the engine passes every declared slug through safe_component before it enters ausmt_id
    (build_portal.py discover_work), safe_component is idempotent, and the hub route 404s unless an
    on-disk <slug>/survey.yaml package exists — so no non-fixed-point slug is reachable. The literal
    every-validate_slug-legal-slug form of the gate is FALSE (a legal slug may contain '..', which
    safe_component collapses to '-'; verified 2026-07-11: 108 of 4920 legal probes transform); such
    a slug fails EMPTY (zero rows — the honest no-stations message), never WRONG (a sibling's rows).
    FAILS IF the engine's slug normalisation drifts so a produced slug is no longer a fixed point
    (the prefix join would then silently blank that survey's Stations tab), or a fixture-tree
    package declares a non-fixed-point slug."""
    import importlib
    import sys
    eng = str(_ENGINE_DIR / "extract")
    sys.path.insert(0, eng)
    try:
        bp = importlib.import_module("build_portal")
    finally:
        sys.path.remove(eng)
    # (1) Every slug the engine ACTUALLY PRODUCED (its own slug-keyed products tree) round-trips,
    #     and passes the hub route's charset gate (publish.validate_slug) — i.e. it is reachable.
    produced = sorted(p.name for p in engine_corpus["products"].iterdir() if p.is_dir())
    assert produced, "fixture sanity: the engine produced no slug-keyed products"
    for slug in produced:
        assert bp.safe_component(slug) == slug, (
            f"engine-produced slug {slug!r} is not a safe_component fixed point — "
            f"'au.' + slug + '.' would no longer prefix-match its own ausmt_ids")
        publish.validate_slug(slug)
    # (2) Every on-disk package slug in the fixture tree (engine/data/<pkg>/survey.yaml), read the
    #     way the engine reads it (declared slug, else the directory name).
    import yaml
    checked = 0
    for sy in sorted(_ENGINE_DIR.glob("data/*/survey.yaml")):
        y = yaml.safe_load(sy.read_text(encoding="utf-8"))
        declared = str(y.get("slug", sy.parent.name)) if isinstance(y, dict) else sy.parent.name
        assert bp.safe_component(declared) == declared, (
            f"fixture package {sy.parent.name} declares non-fixed-point slug {declared!r}")
        checked += 1
    assert checked, "fixture sanity: no engine/data/*/survey.yaml packages found"
