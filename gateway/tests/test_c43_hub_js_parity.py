"""C43-HUB executable JS pins: the survey-hub overview logic (clusterWarnings, attentionPlan,
cardsPlan, hubCounts/qaFlagCount, terse diagnoses, the Stations chip) run IN NODE against a
build_report.json the REAL ENGINE produced over a doctored fixture survey — never hand-typed rows
(standing rule: data-seam pins consume PRODUCER-TRUTH fixtures).

THE FIXTURE (module-scoped, one real build): the engine's CC-BY sample survey EDI (Vulcan_A1,
clean e^{+iωt}, ZROT=0) copied under new DATAIDs and phase-doctored to trip the C25 gates
DETERMINISTICALLY (the test_convention_gates manipulation, reimplemented as pure-text transforms):
  * CP1L02..CP1L05 — Zyx alone conjugated, each with a distinct extra twist (0/1/2/3 deg), so the
    quadrant gate WARNs (single off-diagonal out) with a DISTINCT median per station: four
    same-class warn entries whose ids share the alphabetic prefix run CP1L — the clusterWarnings
    acceptance shape (the mockup's capricorn rows).
  * CP1B10 — Zxy alone conjugated: a SECOND warn class (quadrant:Zxy), must NOT join the cluster.
  * CP2B13 + CP2B14 — full conjugation: Gate-2 FAILs (e^{-i omega t} conjugation signature) ->
    structured stations_dropped refusals; two of them prove the package note renders ONCE and
    that a 2-member run stays UNclustered (< 3).
  * Vulcan_A1 — untouched clean control (served, no warn).

Node dependency posture: pure `node`, no jsdom/npm (the extracted functions are DOM-free by
design); node absence is deliberately NOT allow-listed (the lane must red, not hollow out).
Engine posture: the real engine stack (mt_metadata + the sample survey) is absent in the
stackless gateway CI lane — those pins skip there with EXACTLY the lane's one allow-listed
tripwire reason and RUN on the dev box + the engine/build lanes (ubuntu). Nothing here is
ubuntu-ONLY: every test that can run on this Windows dev box does.

Failure criterion is in each test's docstring (Invariant 10).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys

import pytest

from gateway import curatorpage

# Shared harness helpers + skip posture (the S2a parity file is the house pattern).
from gateway.tests.test_c43_stage2a_js_parity import (  # noqa: F401
    _ENGINE_DIR, _ENGINE_SKIP_REASON, _extract_js_function, _run_node,
)

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason="node not present — executable JS parity pins need the node binary "
           "(deliberately NOT on the gateway skip-tripwire allow-list: absent node in CI must red the lane)")


def _has_engine() -> bool:
    """The producer-truth fixture needs the REAL engine (mt_metadata) + its sample survey. No
    validator needed (--no-validate build), unlike the S2a _run_preview corpus."""
    import importlib.util
    return (importlib.util.find_spec("mt_metadata") is not None
            and (_ENGINE_DIR / "data" / "sample-survey" / "survey.yaml").is_file())


# --------------------------------------------------------------------------------------------------
# EDI phase doctoring (pure text; mirrors engine/tests/test_convention_gates.py's block helpers)
# --------------------------------------------------------------------------------------------------
_NUM = re.compile(r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?")


def _find_block(lines, name):
    start, data = None, []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if start is None:
            if s.upper().startswith(">" + name.upper()):
                rest = s[len(name) + 1:]
                if rest[:1] in ("", " ", "\t", "/"):
                    start = i
            continue
        if s.startswith(">"):
            break
        if s:
            data.append(i)
    if start is None:
        raise AssertionError(f"fixture base has no >{name} block")
    return start, data


def _read_block(text, name):
    lines = text.splitlines()
    _, data = _find_block(lines, name)
    vals = []
    for i in data:
        vals.extend(float(m) for m in _NUM.findall(lines[i]))
    return vals


def _write_block(text, name, values):
    lines = text.splitlines()
    start, data = _find_block(lines, name)
    rows = [" ".join(f"{v: .9E}" for v in values[i:i + 6]) for i in range(0, len(values), 6)]
    new = (lines[:data[0]] + rows + lines[data[-1] + 1:]) if data else \
        (lines[:start + 1] + rows + lines[start + 1:])
    return "\n".join(new) + "\n"


def _mutate_offdiag(text: str, comp: str, *, conjugate: bool, rot_deg: float = 0.0) -> str:
    """Doctor ONE off-diagonal (comp 'XY'|'YX'): z' = twist-then-conjugate, i.e.
    conj(z * e^{i rot}). Conjugating one off-diagonal alone is exactly the Gate-2 WARN shape
    (test_single_component_distortion_warns_not_fails); the per-copy twist makes each station's
    WARN median distinct, so the engine aggregates one frame entry per station (the real
    capricorn shape clusterWarnings exists for)."""
    zr = _read_block(text, f"Z{comp}R")
    zi = _read_block(text, f"Z{comp}I")
    a = math.radians(rot_deg)
    out_r, out_i = [], []
    for r, i in zip(zr, zi):
        r2 = r * math.cos(a) - i * math.sin(a)
        i2 = r * math.sin(a) + i * math.cos(a)
        out_r.append(r2)
        out_i.append(-i2 if conjugate else i2)
    text = _write_block(text, f"Z{comp}R", out_r)
    return _write_block(text, f"Z{comp}I", out_i)


def _conjugate_all(text: str) -> str:
    """Full e^{-iωt} conjugation (negate every Z imaginary block) — the Gate-2 FAIL shape
    (conjugation signature; test_conjugated_z_fails_with_convention_message)."""
    for comp in ("XX", "XY", "YX", "YY"):
        vals = [-v for v in _read_block(text, f"Z{comp}I")]
        text = _write_block(text, f"Z{comp}I", vals)
    return text


def _with_dataid(text: str, station_id: str) -> str:
    assert 'DATAID="A1"' in text, "sample EDI drifted — the fixture rewrites DATAID=\"A1\""
    return text.replace('DATAID="A1"', f'DATAID="{station_id}"')


SLUG = "capr-hub-2026"
LABEL = "Capricorn Hub Fixture"


@pytest.fixture(scope="module")
def warn_report(tmp_path_factory):
    """A build_report.json the REAL ENGINE produced over the doctored fixture survey (module
    docstring). Returns {'rep', 'survey', 'out', 'products'}. Every expectation the pins consume
    is asserted here as fixture sanity FIRST, so a gate-behaviour drift fails loudly at the
    producer, not mysteriously in a JS pin."""
    if not _has_engine():
        pytest.skip(_ENGINE_SKIP_REASON)
    base = tmp_path_factory.mktemp("c43hub-warn-corpus")
    sample = _ENGINE_DIR / "data" / "sample-survey"
    text = (sample / "transfer_functions" / "edi" / "Vulcan_A1.edi").read_text(encoding="latin-1")
    sy = (sample / "survey.yaml").read_text(encoding="utf-8")
    assert "slug: sample-survey" in sy and 'name: "CI Sample Survey"' in sy, (
        "sample survey.yaml drifted — the fixture derives from its slug/name lines")
    pkg = base / "package" / SLUG
    edi = pkg / "transfer_functions" / "edi"
    edi.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        sy.replace("slug: sample-survey", f"slug: {SLUG}")
          .replace('name: "CI Sample Survey"', f'name: "{LABEL}"'), encoding="utf-8")
    # Clean control.
    (edi / "Vulcan_A1.edi").write_text(text, encoding="latin-1")
    # The CP1L prefix run: four same-class (Zyx) warns with DISTINCT medians.
    for n, twist in ((2, 0.0), (3, 1.0), (4, 2.0), (5, 3.0)):
        sid = f"CP1L{n:02d}"
        (edi / f"{sid}.edi").write_text(
            _mutate_offdiag(_with_dataid(text, sid), "YX", conjugate=True, rot_deg=twist),
            encoding="latin-1")
    # A second warn CLASS (Zxy) on a non-run id.
    (edi / "CP1B10.edi").write_text(
        _mutate_offdiag(_with_dataid(text, "CP1B10"), "XY", conjugate=True), encoding="latin-1")
    # Two refusals (conjugation signature) — the once-only package note + the <3-members-stay-
    # unclustered proof.
    for sid in ("CP2B13", "CP2B14"):
        (edi / f"{sid}.edi").write_text(_conjugate_all(_with_dataid(text, sid)),
                                        encoding="latin-1")
    out, prod = base / "data", base / "products"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    # --bundle-edi so the served-XML pass runs (it is what records the canonical-conditioning
    # notes into build_report; test_build_report.py's _build uses the same flag).
    r = subprocess.run(
        [sys.executable, "-m", "extract.build_portal", "--surveys", str(base / "package"),
         "--out", str(out), "--products", str(prod), "--bundle-edi", "--no-validate"],
        cwd=str(_ENGINE_DIR), capture_output=True, text=True, encoding="utf-8", env=env,
        timeout=900)
    assert r.returncode == 0, r.stderr
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    survey = rep["surveys"][SLUG]
    # ---- fixture sanity: the engine really produced the shapes the pins consume ----
    assert survey["stations_built"] == 6, survey["stations_built"]
    dropped = sorted(d["station"] for d in survey["stations_dropped"])
    assert dropped == ["CP2B13", "CP2B14"], dropped
    for d in survey["stations_dropped"]:
        assert d["reason"].startswith("[sign-convention] BOTH off-diagonal"), d
        assert "conjugation signature" in d["reason"], d
    warns = [e for e in survey["frame"]
             if e["note"].startswith("convention: ")
             and "outside its expected quadrant" in e["note"]]
    carriers = sorted(s for e in warns for s in (e["stations"] or []))
    assert carriers == ["CP1B10", "CP1L02", "CP1L03", "CP1L04", "CP1L05"], carriers
    assert sum(e["count"] for e in warns) == 5
    assert any("arg(Zxy)" in e["note"] for e in warns), "the second warn class must exist"
    assert not any("frame: " in e["note"] and "de-rotated" in e["note"]
                   for e in survey["frame"]), "fixture must stay as-stored (no derotation)"
    assert survey["conditioning"], "the sample survey lineage must carry conditioning notes"
    return {"rep": rep, "survey": survey, "out": out, "products": prod}


# --------------------------------------------------------------------------------------------------
# Node driver: extract the WHOLE pure-helper family once
# --------------------------------------------------------------------------------------------------
_HUB_FNS = ("isQuadrantWarnNote", "qaFlagCount", "hubCounts", "stationsChipText",
            "frameCardFacts", "signedDegStr", "terseDrop", "terseWarn", "attentionItems",
            "idPrefix", "classSummary", "clusterWarnings", "truncEmail", "metaInfoText",
            "attentionPlan", "attentionHref", "attentionLinkText", "durationText",
            "cacheWord", "cardsPlan", "conditioningScope")


def _hub_driver(body: str) -> str:
    js = curatorpage.SURVEY_HUB_JS
    # Anchor on the closing quote+semicolon: the note copy itself contains a bare ';'
    # ('custodian-side re-export; each row …'), so a lazy match to the first ';' truncates
    # mid-string (shown as a node SyntaxError when it did).
    note = re.search(r"var REFUSED_NOTE = [\s\S]*?';", js)
    assert note, "REFUSED_NOTE declaration not found in SURVEY_HUB_JS"
    parts = ["import { readFileSync } from 'fs';", note.group(0)]
    parts += [_extract_js_function(js, n) for n in _HUB_FNS]
    parts.append(body)
    return "\n".join(parts)


_PLAN_DRIVER_BODY = """
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {
  counts: hubCounts(p.survey),
  chip: stationsChipText(hubCounts(p.survey)),
  cards: cardsPlan(p.survey, p.rep),
  plan: attentionPlan(p.survey, p.citationEmail || ''),
  scopes: (p.survey.conditioning || []).map(function (c) {
    return conditioningScope(c, p.survey.stations_built);
  }),
  hrefs: {
    removal: attentionHref('removal', p.slug),
    stations: attentionHref('stations', p.slug),
    metadata: attentionHref('metadata', p.slug),
    none: attentionHref(null, p.slug)
  }
};
process.stdout.write(JSON.stringify(out));
"""


def _run_plan(tmp_path, warn_report, citation_email=""):
    return _run_node(tmp_path, _hub_driver(_PLAN_DRIVER_BODY),
                     {"survey": warn_report["survey"], "rep": warn_report["rep"],
                      "slug": SLUG, "citationEmail": citation_email})


# --------------------------------------------------------------------------------------------------
# The pins
# --------------------------------------------------------------------------------------------------
def test_cluster_warnings_producer_truth(warn_report, tmp_path):
    """CLUSTERING ENGINE-TRUTH PIN (contract H2 acceptance shape). Driven with the REAL engine's
    build_report: the four same-class Zyx warns on the CP1L prefix run collapse to ONE row
    ('CP1L02 … CP1L05', '4 stations — …; clustered on one line', full notes in the title); the
    second class (CP1B10, Zxy) stays its own row and NEVER joins the cluster; the TWO refusals
    (CP2B, same class, 2 members) stay UNclustered (< 3). FAILS IF the prefix grouping breaks
    (no cluster / everything clustered), a different class leaks into a cluster, or a 2-member
    run clusters."""
    got = _run_plan(tmp_path, warn_report)
    rows = [s["row"] for s in got["plan"] if "row" in s]
    clusters = [r for r in rows if r["n"] > 1]
    assert len(clusters) == 1, [r["sid"] for r in rows]
    c = clusters[0]
    assert c["sid"] == "CP1L02 … CP1L05"
    assert c["n"] == 4 and c["ids"] == ["CP1L02", "CP1L03", "CP1L04", "CP1L05"]
    assert c["kind"] == "warn"
    assert c["text"] == ("4 stations — one off-diagonal (Zyx) out of expected quadrant — "
                         "served with note; clustered on one line")
    # Every clustered station's FULL engine note rides the title (nothing hidden).
    for sid in c["ids"]:
        assert sid + ": convention: " in c["title"], c["title"]
    # The second class is its own row, never absorbed.
    zxy = [r for r in rows if r["sid"] == "CP1B10"]
    assert len(zxy) == 1 and zxy[0]["n"] == 1
    assert "arg(Zxy) median " in zxy[0]["text"] and "Zyx in-quadrant" in zxy[0]["text"]
    # The 2-member refusal run stays UNclustered.
    fail_sids = sorted(r["sid"] for r in rows if r["kind"] == "fail")
    assert fail_sids == ["CP2B13", "CP2B14"]


def test_refusal_rows_terse_with_full_reason_in_title(warn_report, tmp_path):
    """SEVERITY-ROW PIN (refusals). Each refusal renders as a fail row whose TERSE diagnosis names
    the signature + the engine's own medians ('refused — both off-diagonals out of quadrant;
    e^{-i omega t} conjugation signature (Zxy …°, Zyx …°)'), whose title carries the VERBATIM
    full gate reason, and whose action link targets the station-removal list. FAILS IF the terse
    line degrades to the full gate paragraph, the full reason is dropped from the title, or the
    link target drifts."""
    got = _run_plan(tmp_path, warn_report)
    fails = [s["row"] for s in got["plan"] if "row" in s and s["row"]["kind"] == "fail"]
    reasons = {d["station"]: d["reason"] for d in warn_report["survey"]["stations_dropped"]}
    assert len(fails) == 2
    for row in fails:
        assert re.match(
            r"^refused — both off-diagonals out of quadrant; e\^\{-i omega t\} conjugation "
            r"signature \(Zxy [+-]\d+(\.\d+)?°, Zyx [+-]\d+(\.\d+)?°\)$", row["text"]), row["text"]
        assert row["title"] == reasons[row["sid"]], "the FULL gate reason must ride the title"
        assert len(row["text"]) < len(row["title"]), "terse means terse"
        assert row["link"] == "removal"
    assert got["hrefs"]["removal"] == f"/gateway/curator/edit/{SLUG}/stations"
    assert got["hrefs"]["stations"] == f"/gateway/curator/survey/{SLUG}?tab=stations"
    assert got["hrefs"]["metadata"] == f"/gateway/curator/survey/{SLUG}?tab=metadata"
    assert got["hrefs"]["none"] is None


def test_package_note_renders_once_despite_multiple_refusals(warn_report, tmp_path):
    """BOILERPLATE-ONCE PIN (contract H2). With TWO refusals in the report, the refused-stations-
    stay-in-package note appears EXACTLY ONCE in the plan, positioned after the last fail row and
    before the first warn row. FAILS IF the note repeats per refusal row (the mockup regression
    this pin exists for) or disappears."""
    got = _run_plan(tmp_path, warn_report)
    plan = got["plan"]
    notes = [i for i, s in enumerate(plan) if "note" in s]
    assert len(notes) == 1, f"the package note must render ONCE, got {len(notes)}"
    kinds = ["note" if "note" in s else s["row"]["kind"] for s in plan]
    last_fail = max(i for i, k in enumerate(kinds) if k == "fail")
    first_warn = min(i for i, k in enumerate(kinds) if k == "warn")
    assert last_fail < notes[0] < first_warn, kinds
    assert "Refused stations stay in the published package" in plan[notes[0]]["note"]


def test_four_cards_producer_truth_and_build_id_absent(warn_report, tmp_path):
    """FOUR-CARDS PIN (engine truth) incl. the build-id-card-ABSENT assertion. cardsPlan over the
    real report yields EXACTLY the mockup's four cards: Serving/published '6 / 8' with '2 refused
    by convention gate'; QA flags 5 (warn tone); Frame 'as-stored' + 'declared-zero reference'
    (Q1 ruling: derotation notes only, record vocabulary, never 'geomagnetic'); Last build
    '<duration> s' + 'cold · engine <sha>' (a fresh build is all cache misses). FAILS IF a card
    is added/removed/reordered, the build-id card returns, published != built + dropped, or the
    frame card invents a frame fact."""
    got = _run_plan(tmp_path, warn_report)
    cards = got["cards"]
    assert [c["label"] for c in cards] == ["Serving / published", "QA flags", "Frame",
                                           "Last build"]
    assert not any("build" in c["label"].lower() and "id" in c["label"].lower() for c in cards)
    sp = cards[0]
    assert sp["value"] == "6" and sp["small"] == " / 8"
    assert sp["sub"] == "2 refused by convention gate"
    qa = cards[1]
    assert qa["value"] == "5" and qa["tone"] == "warn"
    fr = cards[2]
    assert fr["value"] == "as-stored" and fr["sub"] == "declared-zero reference"
    assert "geomagnetic" not in json.dumps(cards), "the engine never asserts 'geomagnetic'"
    lb = cards[3]
    assert re.match(r"^\d+(\.\d)? s$", lb["value"]), lb["value"]
    # PRODUCER TRUTH: this fixture build runs WITHOUT the C18 cache (no cache dir), so its
    # counters are all zero and there IS no cold/warm fact — the sub must carry only the engine
    # sha, never an invented 'cold'. The cold/warm/mixed words are pinned below on cache states
    # DERIVED from the real report (counter fields mutated, shape preserved).
    assert lb["sub"] == "engine " + warn_report["rep"]["engine_commit"], lb["sub"]
    driver = _hub_driver("""
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(p.cases.map(function (c) {
  return cardsPlan(c.survey, p.rep)[3].sub;
})));
""")
    base = warn_report["survey"]
    cases = [{"survey": dict(base, cache=dict(base["cache"], hits=0, misses=6))},
             {"survey": dict(base, cache=dict(base["cache"], hits=6, misses=0))},
             {"survey": dict(base, cache=dict(base["cache"], hits=4, misses=2))}]
    sha = warn_report["rep"]["engine_commit"]
    subs = _run_node(tmp_path, driver, {"cases": cases, "rep": warn_report["rep"]})
    assert subs == [f"cold · engine {sha}", f"warm · engine {sha}", f"mixed · engine {sha}"], subs


def test_chip_and_qa_card_share_one_flag_definition(warn_report, tmp_path):
    """Q2 SHARED-DEFINITION PIN. The H1 Stations-chip flagged number and the H2 QA-flags card
    render the SAME number from the SAME input (qaFlagCount over the convention-warn frame
    entries): chip '2 dropped · 5 flagged', card value '5', counts {serving 6, published 8}.
    FAILS IF the two surfaces disagree, published stops being built + dropped, or a healthy
    survey grows a chip (null at 0/0)."""
    got = _run_plan(tmp_path, warn_report)
    assert got["counts"] == {"serving": 6, "published": 8, "dropped": 2, "flagged": 5}
    assert got["chip"] == "2 dropped · 5 flagged"
    assert got["cards"][1]["value"] == "5", "card and chip must share qaFlagCount"
    assert str(got["counts"]["flagged"]) == got["cards"][1]["value"]
    # 0/0 -> no chip (hidden): drive with a clean survey shape derived from the real one.
    clean = dict(warn_report["survey"], stations_dropped=[], frame=[])
    got2 = _run_node(tmp_path, _hub_driver(_PLAN_DRIVER_BODY),
                     {"survey": clean, "rep": warn_report["rep"], "slug": SLUG})
    assert got2["chip"] is None, "a healthy survey must show NO chip"


def test_conditioning_scope_all_n_form(warn_report, tmp_path):
    """CONDITIONING-TABLE PIN. The scope cell renders the mockup's 'all N' form when every served
    station carries the note (the fixture's lineage notes are survey-wide), never a bare count
    with a redundant enumeration. FAILS IF the all-N form regresses to '6 (A1, CP1B10, …)' or
    the count no longer matches the engine's."""
    got = _run_plan(tmp_path, warn_report)
    survey = warn_report["survey"]
    assert got["scopes"], "fixture carries conditioning entries"
    for entry, scope in zip(survey["conditioning"], got["scopes"]):
        if entry["count"] == survey["stations_built"]:
            assert scope == f"all {survey['stations_built']}", (entry, scope)
        else:
            assert str(entry["count"]) in scope or (entry["stations"] or []), (entry, scope)


def test_info_row_only_when_server_stamped(warn_report, tmp_path):
    """Q3 INFO-ROW PIN. The metadata info row appears ONLY when the server stamped the citation
    email (attentionPlan's citationEmail argument = the data-citation-email attribute): with it,
    ONE blue info row, last, 'citation author is an email address (graham.heinson@…) — baked
    into all 6 served station XML', linking to the Metadata tab; without it, NO info row. FAILS
    IF the row appears unstamped (the deleted string-matching would), the truncation leaks the
    domain, or the count is invented."""
    got = _run_plan(tmp_path, warn_report, citation_email="graham.heinson@adelaide.edu.au")
    rows = [s["row"] for s in got["plan"] if "row" in s]
    infos = [r for r in rows if r["kind"] == "info"]
    assert len(infos) == 1
    info = infos[0]
    assert got["plan"][-1] == {"row": info}, "the info row renders last"
    assert info["sid"] == "metadata" and info["link"] == "metadata"
    assert info["text"] == ("citation author is an email address (graham.heinson@…) — baked "
                            "into all 6 served station XML")
    assert "adelaide" not in info["text"], "truncate at the @ — the domain is noise here"
    got2 = _run_plan(tmp_path, warn_report)
    assert not any(s["row"]["kind"] == "info" for s in got2["plan"] if "row" in s)


def test_frame_card_derotation_headline_from_note_vocabulary(warn_report, tmp_path):
    """Q1 FRAME-CARD PIN (both branches). Headline derives from DE-ROTATION notes ONLY: the real
    as-stored fixture yields 'as-stored'; grafting the ENGINE'S OWN derotation/R3 note shapes
    (verbatim vocabulary from _conventions.py) onto the real report yields 'N de-rotated' with
    the enumerated-carrier union, and the R3 sub-line 'declared acquisition frame recorded'.
    Convention-warn entries must NEVER flip the headline. FAILS IF warns count as frame state,
    the union double-counts a station carried by two derotation notes, or the sub-line invents
    vocabulary the record does not carry."""
    driver = _hub_driver("""
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(p.cases.map(function (c) { return frameCardFacts(c); })));
""")
    real_frame = warn_report["survey"]["frame"]
    # The engine's own note shapes (_conventions.py notes.append vocabulary), verbatim:
    imp = {"note": "frame: impedance+tipper de-rotated 14 deg -> the file's declared "
                   "zero-azimuth reference", "count": 2, "stations": ["S01", "S02"],
           "except": None}
    tip = {"note": "frame: tipper de-rotated with the impedance (tipper blocks declare "
                   "no azimuth)", "count": 1, "stations": ["S02"], "except": None}
    r3 = {"note": "frame: served in its declared acquisition frame, x-axis 8 deg",
          "count": 3, "stations": None, "except": None}
    cases = [real_frame,                       # as-stored (warns present, no derotation)
             real_frame + [imp, tip],          # 2 de-rotated (S02 counted ONCE across two notes)
             real_frame + [r3]]                # as-stored + R3 declared-frame sub-line
    got = _run_node(tmp_path, driver, {"cases": cases})
    assert got[0] == {"headline": "as-stored", "sub": "declared-zero reference"}
    assert got[1]["headline"] == "2 de-rotated", got[1]
    assert got[2] == {"headline": "as-stored", "sub": "declared acquisition frame recorded"}


def test_warn_terse_lines_derive_from_engine_notes(warn_report, tmp_path):
    """TERSE-WARN PIN. terseWarn over the REAL engine warn notes produces the mockup-shaped terse
    line ('arg(Zyx) median +134.8° out of expected quadrant; Zxy in-quadrant — served with
    note') carrying the ENGINE'S OWN median (verbatim digits from the note, no re-rounding), and
    classes the note by component. An unrecognisable note falls back VERBATIM. FAILS IF the
    median is dropped/recomputed, the class misassigns the component, or the fallback hides
    text."""
    driver = _hub_driver("""
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(p.notes.map(function (n) { return terseWarn(n); })));
""")
    warns = [e for e in warn_report["survey"]["frame"]
             if e["note"].startswith("convention: ")
             and "outside its expected quadrant" in e["note"]]
    notes = [e["note"] for e in warns] + ["something the engine never wrote"]
    got = _run_node(tmp_path, driver, {"notes": notes})
    for note, t in zip(notes[:-1], got[:-1]):
        m = re.search(r"arg\(Z(xy|yx)\) mid-band median (-?\d+(?:\.\d+)?) deg", note)
        comp, med = "Z" + m.group(1), m.group(2)
        assert t["cls"] == f"quadrant:{comp}", (note, t)
        sign = "+" if float(med) >= 0 else ""
        assert t["terse"].startswith(f"arg({comp}) median {sign}{med}° out of expected quadrant"), \
            (note, t)
        assert t["terse"].endswith("— served with note")
    assert got[-1] == {"cls": "frame-note", "terse": "something the engine never wrote"}, \
        "unrecognised notes fall back verbatim"


def test_three_member_cluster_uses_middot_join(warn_report, tmp_path):
    """CLUSTER-JOIN SHAPE PIN. Exactly 3 same-class members render 'A · B · C' (the mockup's
    refusal-cluster shape); 4+ render 'first … last'. Driven with the PRODUCER-TRUTH items
    (attentionItems over the real survey), sliced to three CP1L members — sliced producer values,
    not hand-typed rows. FAILS IF the 3-member join style drifts or slicing to 2 members starts
    clustering."""
    driver = _hub_driver("""
const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const items = attentionItems(p.survey).filter(function (it) {
  return it.cls === 'quadrant:Zyx';
});
process.stdout.write(JSON.stringify({
  n4: clusterWarnings(items),
  n3: clusterWarnings(items.slice(0, 3)),
  n2: clusterWarnings(items.slice(0, 2))
}));
""")
    got = _run_node(tmp_path, driver, {"survey": warn_report["survey"]})
    assert got["n4"][0]["sid"] == "CP1L02 … CP1L05"
    assert len(got["n3"]) == 1 and got["n3"][0]["sid"] == "CP1L02 · CP1L03 · CP1L04"
    assert len(got["n2"]) == 2 and all(r["n"] == 1 for r in got["n2"]), \
        "2 same-class members must stay individual rows"
