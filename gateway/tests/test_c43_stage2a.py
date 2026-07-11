"""C43 Stage 2a verification pins (record D13 + the contract's pin list). Each pin states its failure
criterion (Invariant 10) and is mutation-provable — the report carries a captured failing run for each
guarded behaviour. Async bodies run under conftest.run().

Pins here:
  * PHASE QUADRANT + φyx UNWRAP (phaseqc, the authoritative server-side seam the STATIONS_JS mirrors):
    the +180 presentation shift on t[4] is inverted before classifying — a TRUE-Q3 station (stored t[4]
    near 0…90) classifies IN-quadrant; reading the stored value as true phase mis-classifies it.
  * [FC-2] LAG LABEL: with served ≠ published the Stations panel carries the publish-pending label.
  * CSP SWEEP extended to every NEW Stage-2a renderer/JS constant + rendered surface.
  * HISTORY READ-ONLY: the history-job argv carries only the read-only `log` verb (allowlist assertion).
  * QUARANTINE CONTAINMENT: a traversal attempt 404s; a real package file serves with the safe
    attachment + nosniff discipline.
  * KEYS: a note is stored + rendered + ABSENT from any git-bound artifact; submission counts are
    correct; revoked rows render read-only (no note editor, no revoke button).
  * S2a-5 BUILD-ID SHORTENER: canonical triple-barrel -> short display; malformed -> verbatim fallback.
"""
from __future__ import annotations

import re
import subprocess

from gateway import builddisplay, curatorpage, phaseqc
from gateway.runner import edit as edit_mod
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)


# ==================================================================================================
# Phase quadrant classification + the φyx +180 unwrap (phaseqc — the authoritative seam)
# ==================================================================================================
def test_phi_xy_quadrant_classification():
    """φxy (t[3], stored = true) classifies against Q1 widened by the engine-gate slack (fix-round F4:
    band −10…100 with QUADRANT_SLACK_DEG = 10). FAILS IF an in-band(+slack) value is flagged (a red
    dot on a point the engine gate tolerates), an outside-by-more-than-slack value is not flagged, or
    the slack edges are wrong (the −10.0/100.0 edge vectors are IN; −10.1/100.1 are OUT — a
    hard-band implementation fails the edge vectors)."""
    s = phaseqc.QUADRANT_SLACK_DEG
    assert s == 10.0
    assert phaseqc.in_quadrant_xy(0.0) is True
    assert phaseqc.in_quadrant_xy(45.0) is True
    assert phaseqc.in_quadrant_xy(90.0) is True
    assert phaseqc.in_quadrant_xy(-10.0) is True      # slack edge — the engine gate tolerates this
    assert phaseqc.in_quadrant_xy(100.0) is True      # slack edge
    assert phaseqc.in_quadrant_xy(-10.1) is False     # beyond slack => red dot
    assert phaseqc.in_quadrant_xy(100.1) is False
    assert phaseqc.in_quadrant_xy(120.0) is False
    assert phaseqc.in_quadrant_xy(None) is None


def test_quadrant_slack_matches_engine_gate():
    """CROSS-IMPORT PARITY PIN (fix-round F4a, architect ruling): the workbench's QUADRANT_SLACK_DEG
    must EQUAL the engine gate's single-sourced constant (engine/extract/_conventions.py:98) — the
    workbench verdict and the served-corpus Gate-2 verdict must never diverge on tolerance. FAILS IF
    either side changes its slack without the other. _conventions imports stdlib-only at module level
    (numpy is function-local), so this import runs in the stack-less gateway CI env."""
    import importlib
    import sys
    from pathlib import Path
    eng = Path(__file__).resolve().parents[2] / "engine" / "extract"
    assert (eng / "_conventions.py").is_file(), f"engine gate module missing at {eng}"
    sys.path.insert(0, str(eng))
    try:
        conv = importlib.import_module("_conventions")
    finally:
        sys.path.remove(str(eng))
    assert phaseqc.QUADRANT_SLACK_DEG == conv.QUADRANT_SLACK_DEG, (
        f"workbench slack {phaseqc.QUADRANT_SLACK_DEG} != engine gate slack "
        f"{conv.QUADRANT_SLACK_DEG} (_conventions.py) — the two verdicts have diverged")


def test_phi_yx_unwrap_true_q3_classifies_in_quadrant():
    """THE φyx-UNWRAP PIN. A station whose TRUE φyx sits in Q3 (−180…−90) has a STORED t[4] near 0…90
    (because engine _edi_tf stores phs_yx_adj = true + 180, re-wrapped). The workbench MUST subtract
    the shift and classify the TRUE phase — so a true-Q3 station classifies IN-quadrant. FAILS IF the
    workbench reads the stored value as the true phase (then stored 45° would look like Q1 = 'in Q1',
    and against Q3 it would read as OUT — the mis-classification this pin catches).

    NON-VACUOUS: for true φyx = −135°, stored t[4] = +45°. in_quadrant_yx(+45°) must be True (it
    unwraps to −135° ∈ Q3). A naive `Q3_LO <= 45 <= Q3_HI` is False — so a no-unwrap implementation
    fails this exact assertion."""
    for true_yx in (-135.0, -100.0, -170.0, -90.0, -180.0, -91.0):
        stored = phaseqc.wrap180(true_yx + phaseqc.YX_PRESENTATION_SHIFT_DEG)  # == engine norm_phase
        assert phaseqc.true_phi_yx(round(stored, 1)) is not None
        assert abs(phaseqc.true_phi_yx(round(stored, 1)) - true_yx) < 0.05, (true_yx, stored)
        assert phaseqc.in_quadrant_yx(round(stored, 1)) is True, (
            f"true φyx={true_yx} (stored t[4]={round(stored, 1)}) must classify IN Q3 after the +180 "
            "unwrap — reading the stored value directly would mis-classify it")


def test_phi_yx_unwrap_true_q1_classifies_out_of_quadrant():
    """The converse: a station whose TRUE φyx is beyond the Q3 band by MORE than the slack (a genuinely
    wrong-quadrant yx) must classify OUT. FAILS IF the unwrap is skipped (stored −135 would then read
    as Q3 = 'in', hiding the real wrong-quadrant station) or the slack edge is wrong (−79.9 is 10.1°
    outside the band => OUT; −80.0 is exactly at the slack edge => IN)."""
    for true_yx in (45.0, 10.0, -45.0, -79.9):
        stored = round(phaseqc.wrap180(true_yx + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)
        assert phaseqc.in_quadrant_yx(stored) is False, (true_yx, stored)


def test_phi_yx_slack_and_seam_edges():
    """Fix-round F4 edge semantics for yx: (a) a true value within the slack of the band (−85, −80) is
    IN (the engine gate tolerates it — no red dot); (b) a true value just past +180 THROUGH THE SEAM
    (+175 maps to −185 on the (−360,0] axis, within slack of the −180 edge) is IN — the seam mapping is
    what makes Q3±slack one contiguous window. FAILS IF the seam mapping is dropped (naive (−180,180]
    comparison calls +175 OUT) or the slack is not applied."""
    for true_yx in (-85.0, -80.0, 175.0, 171.0):
        stored = round(phaseqc.wrap180(true_yx + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)
        assert phaseqc.in_quadrant_yx(stored) is True, (true_yx, stored)
    # Just beyond the seam-side slack: true +169.9 maps to −190.1 — 0.1° beyond => OUT.
    stored = round(phaseqc.wrap180(169.9 + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)
    assert phaseqc.in_quadrant_yx(stored) is False, stored


def test_classify_series_median_verdict():
    """classify_series (fix-round F4c — engine-rule alignment): the VERDICT is the MEDIAN of classified
    points vs band+slack (median_in), per-point flags mark only beyond-slack points (red dots), and the
    reported median rides the engine's seam-mapped axis for yx. FAILS IF a scattered outlier flips the
    verdict (median-vs-point confusion), the median seam mapping is dropped (a ±180-straddling cluster
    would median near 0 and read as catastrophically out), or an all-None series invents a verdict."""
    # xy: one beyond-slack outlier among in-band points => red dot (points[2] False) but the MEDIAN
    # verdict stays IN — scattered outliers must not flip a station verdict (the engine rule).
    xy = phaseqc.classify_series([10.0, 45.0, 200.0], mode="xy")
    assert xy["points"] == [True, True, False]
    assert xy["any_out"] is True
    assert xy["median"] == 45.0 and xy["median_in"] is True
    # xy: a coherently wrong series => median beyond band+slack => verdict OUT.
    xy_bad = phaseqc.classify_series([-120.0, -130.0, -140.0], mode="xy")
    assert xy_bad["median"] == -130.0 and xy_bad["median_in"] is False
    # yx healthy Q3 cluster: median reported in (−180,180], verdict IN.
    yx_stored = [round(phaseqc.wrap180(v + 180.0), 1) for v in (-135.0, -100.0, -170.0)]
    yx = phaseqc.classify_series(yx_stored, mode="yx")
    assert yx["median"] == -135.0 and yx["median_in"] is True and yx["any_out"] is False
    # yx SEAM-STRADDLING cluster (true −179/−178/+179): the (−360,0] mapping keeps the median at the
    # seam (−179 side, mapped −181 for +179) instead of a nonsense near-0 average; verdict IN.
    yx_seam = phaseqc.classify_series(
        [round(phaseqc.wrap180(v + 180.0), 1) for v in (-179.0, -178.0, 179.0)], mode="yx")
    assert yx_seam["median_in"] is True, yx_seam
    assert yx_seam["median"] == -179.0, yx_seam   # mapped median −179 (middle of −181/−179/−178)
    # all-None => no verdict at all.
    empty = phaseqc.classify_series([None, None], mode="xy")
    assert empty["any_out"] is False and empty["median"] is None and empty["median_in"] is None
    assert empty["n_classified"] == 0


def test_stations_js_mirrors_phaseqc_constants():
    """SOURCE ASSERTION: the browser-side STATIONS_JS embeds the SAME phase constants + structural
    elements phaseqc defines (the EXECUTABLE parity pin proves the semantics; this cheap sweep catches
    a wholesale removal even where node is unavailable). FAILS IF the JS drops the +180 shift, the
    Q1/Q3 bounds, the slack, the floored modulo, the seam map, or the unwrap-then-classify structure."""
    js = curatorpage.STATIONS_JS
    assert "YX_SHIFT = 180.0" in js, "the +180 presentation shift must be in the JS mirror"
    assert "Q1_LO = 0.0" in js and "Q1_HI = 90.0" in js
    assert "Q3_LO = -180.0" in js and "Q3_HI = -90.0" in js
    assert "SLACK = 10.0" in js, "the engine-gate slack must be in the JS mirror (fix-round F4)"
    # FLOORED modulo (fix-round F1): the CPython float-% form, never bare truncated %.
    assert "function floormod" in js and "if (r !== 0 && r < 0) r += y" in js
    # trueYx must SUBTRACT the shift then wrap (the unwrap), and inQ3 must go through trueYx + mapYx.
    assert "wrap180(stored - YX_SHIFT)" in js, "φyx must be unwrapped (stored - shift), not read raw"
    assert "var v = trueYx(stored)" in js, "inQ3 must classify the UNWRAPPED true phase"
    assert "function mapYx" in js and "mapYx(v)" in js, "yx must classify on the seam-mapped axis"
    assert "function medianOf" in js, "the median verdict (F4c) must be in the JS mirror"


# ==================================================================================================
# [FC-2] lag label on the Stations panel
# ==================================================================================================
def _hub_survey(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="s2a-survey",
                      yaml_text="schema_version: \"0.2\"\nslug: s2a-survey\n"
                                "project_name: S2a\nversion: 1.0.0\n")
    return surveys_live


def test_fc2_lag_label_rendered_when_served_differs_from_published(tmp_path):
    """[FC-2] LAG-LABEL PIN. The Stations tab carries the server-rendered published HEAD in
    data-published-head; the stations JS compares it to the served build's source_commit and renders
    the 'facts from build … — publish pending' label ON THE PANEL. This pin proves the label MACHINERY
    is present: the panel scaffold carries the published HEAD hook AND the JS carries the publish-
    pending label string + the lag comparison. FAILS IF the hook or the label machinery is absent."""
    async def _body():
        surveys_live = _hub_survey(tmp_path)

        class HeadGit(FakeGit):
            def __call__(self, args, *, cwd, env=None):
                # read_published_head runs `rev-parse --short HEAD` — answer with a KNOWN published sha.
                from gateway.publish import GitResult
                if args[:2] == ["rev-parse", "--short"]:
                    return GitResult(returncode=0, stdout="pub1234\n", stderr="")
                return super().__call__(args, cwd=cwd, env=env)

        async with app_client(tmp_path, git_runner=HeadGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/s2a-survey?tab=stations")
            assert r.status_code == 200
            # The STATIONS PANEL scaffold (not merely the drift chip elsewhere on the page) carries the
            # published-HEAD hook the stations JS reads — assert it on the survey-stations div's own tag
            # so the pin is scoped to THIS panel (the drift chip carries its own data-published-head).
            m = re.search(r'<div id="survey-stations"[^>]*>', r.text)
            assert m, "the survey-stations panel scaffold must render"
            assert 'data-published-head="pub1234"' in m.group(0), (
                "the stations panel itself must carry the [FC-2] published-HEAD hook")
            assert 'src="/gateway/curator/stations.js"' in r.text
        # The JS carries the [FC-2] label + the lag comparison (served source_commit vs published HEAD).
        js = curatorpage.STATIONS_JS
        assert "publish pending" in js, "the [FC-2] publish-pending label must be in the stations JS"
        assert "lagPending" in js and "publishedHead" in js, "the served-vs-published lag compare"
    run(_body())


# ==================================================================================================
# S2a-SPLIT: the Stations tab split layout (list LEFT / data panel RIGHT; narrow = panel-first)
# ==================================================================================================
def test_stations_split_scaffold_structure_and_dom_order(tmp_path):
    """S2a-SPLIT RENDER PIN. The Stations tab body carries the split structure: a .stations-split
    grid whose DATA PANEL container (#station-detail) precedes the LIST container (#stations-list) in
    DOM order, and the list container carries the .st-list class the CSS grids into the LEFT column.
    Panel-first DOM order is the load-bearing narrow-stacking mechanism (see the CSS pin below): on a
    one-column layout the panel stacks above the list with NO `order` needed. FAILS IF the split
    container is absent, the two slots are missing, or the panel does NOT precede the list in DOM."""
    async def _body():
        surveys_live = _hub_survey(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/s2a-survey?tab=stations")
            assert r.status_code == 200
            body = r.text
            assert 'class="stations-split"' in body, "the split grid container must render"
            # The stations tab opts into the wide measure (usability fix 2026-07-11: inside the
            # default 960px wrap the list truncated and the panel cramped); the hub's OTHER tabs
            # keep the reading measure — scope-checked below via the overview tab.
            assert 'class="wrap wide"' in body, "the stations tab must use the wide page measure"
            i_panel = body.find('id="station-detail"')
            i_list = body.find('id="stations-list"')
            assert i_panel >= 0, "the DATA panel slot (#station-detail) must render"
            assert i_list >= 0, "the LIST slot (#stations-list) must render"
            # DOM ORDER (amended owner ruling): the DATA PANEL comes FIRST so it stacks ABOVE the list
            # on a narrow single column. A list-first DOM (the reverse) fails here.
            assert i_panel < i_list, (
                "the data panel (#station-detail) must PRECEDE the list (#stations-list) in DOM order "
                "so narrow screens stack panel-first")
            assert 'class="st-list"' in body, "the list container carries the grid-left .st-list class"
            # Scope: the wide measure is the STATIONS tab's opt-in only — the hub's overview tab
            # keeps the default reading measure (the H2 'no silent global widening' rule).
            r2 = await client.get("/gateway/curator/survey/s2a-survey")
            assert r2.status_code == 200 and 'class="wrap wide"' not in r2.text, (
                "the wide measure must not leak to the hub's other tabs")
            assert 'class="st-panel"' in body, "the panel container carries the grid-right .st-panel class"
    run(_body())


def test_stations_split_css_layout_mechanism_present():
    """S2a-SPLIT CSS-MECHANISM PIN. Pins the ACTUAL layout mechanism the render pin relies on, so a CSS
    regression that silently breaks the layout goes red even though the DOM is unchanged:
      (a) WIDE: .stations-split is a 2-column grid; the list is placed in grid-column 1 (LEFT) and the
          panel in grid-column 2 (RIGHT) — the amended list-left/panel-right arrangement.
      (b) The list scrolls in its OWN fixed-height region: .st-scroll has overflow-y + a max-height
          (never a full-page table — the >300-row requirement).
      (c) NARROW (max-width:720px): the grid collapses to one column, so panel-first DOM order stacks
          the panel above the list.
    FAILS IF any of the three mechanism pieces is dropped from the shell CSS."""
    head = curatorpage._HEAD
    # (a) two-column grid with explicit list-left / panel-right placement — INCLUDING grid-row.
    assert ".stations-split{display:grid" in head, "the split must be a CSS grid"
    assert "grid-template-columns:minmax(24rem,28rem) minmax(0,1fr)" in head, (
        "wide: the list column must fit its five columns un-truncated (24-28rem), panel takes the rest "
        "(usability incident 2026-07-11: a fixed 20rem list truncated Quality and forced an inner "
        "horizontal scrollbar)")
    # grid-ROW is load-bearing, not decoration (usability incident 2026-07-11): with only grid-COLUMN
    # set, auto-placement cannot move backwards within a row, so the DOM-second list wanting column 1
    # lands in ROW 2 — BELOW the panel; three screens down once a real station renders. Both items
    # must be pinned to row 1. FAILS IF either grid-row:1 is dropped.
    assert ".stations-split .st-list{grid-column:1;grid-row:1}" in head, (
        "the LIST must be pinned to column 1 ROW 1 (grid auto-placement drops it to row 2 otherwise)")
    assert ".stations-split .st-panel{grid-column:2;grid-row:1}" in head, (
        "the PANEL must be pinned to column 2 ROW 1")
    assert "align-items:start" in head, "columns are top-aligned so the list never pushes the panel down"
    # (b) the list's own fixed-height scroll region.
    assert ".st-scroll{max-height:" in head and "overflow-y:auto" in head, (
        "the list must scroll in a fixed-height region, never as a full-page table")
    # (c) narrow collapse to one column (panel-first DOM => panel-above-list stacking).
    m = re.search(r"@media \(max-width:720px\)\{(.*?)\}\s*</style>", head, re.DOTALL)
    assert m, "the responsive @media block must exist"
    narrow = m.group(1)
    assert ".stations-split{grid-template-columns:1fr}" in narrow, (
        "narrow screens must collapse the split to a single column so the panel stacks above the list")
    assert "grid-row:auto" in narrow, (
        "narrow: grid-row must return to auto so the two items STACK (the wide grid-row:1 pins would "
        "otherwise force both into one row = side-by-side squeeze on a phone)")


def test_stations_split_no_page_scroll_on_row_select():
    """S2a-SPLIT NO-SCROLL PIN. Clicking a station must populate the RIGHT panel WITHOUT scrolling the
    page away. The row handler must NOT navigate to a fragment or call scrollIntoView — it selects the
    row (adds the .on highlight) and repopulates #station-detail in place. FAILS IF the JS reintroduces
    a location-hash link (href='#') or a scroll call in the row-selection path (the merged behaviour put
    the drill-down BELOW a full-page table and used an in-list anchor, which jumped the viewport)."""
    js = curatorpage.STATIONS_JS
    # The whole ROW is the selection target (st-row), not an in-cell anchor with href='#'.
    assert "'st-row'" in js, "each list row carries the .st-row selection class"
    assert "classList.add('on')" in js, "the selected row gets a visible highlight (.on)"
    # No scroll CALL and no scroll-to-hash navigation in the JS (a prose mention in a comment is fine;
    # a .scrollIntoView( invocation or an assignment to location.hash is the viewport-jumping vector).
    assert ".scrollIntoView(" not in js, "row selection must not call scrollIntoView (viewport jump)"
    assert "location.hash" not in js, "row selection must not navigate to a fragment (viewport jump)"
    assert "link.href = '#'" not in js, "the merged in-list hash anchor (viewport-jumping) must be gone"


# ==================================================================================================
# CSP sweep extended to every NEW Stage-2a renderer + JS constant
# ==================================================================================================
def test_c43_stage2a_js_constants_are_raw_and_csp_clean():
    """Every NEW Stage-2a JS constant (STATIONS_JS) is RAW JS — no <script> wrapper, no on*= handler,
    and no innerHTML-with-DATA path (SVG is built via createElementNS, values via textContent). FAILS
    IF a Stage-2a constant ships wrapped/inline, or a new innerHTML=<data> path lands."""
    js = curatorpage.STATIONS_JS
    assert "<script" not in js.lower(), "STATIONS_JS must be RAW JS, not <script>-wrapped"
    assert not re.search(r"""\bon[a-z]{3,}\s*=\s*['"]""", js), "no on*= handler in STATIONS_JS"
    # No innerHTML assignment anywhere (the SVG-via-string vector the contract forbids for data).
    assert ".innerHTML" not in js, "STATIONS_JS must never assign innerHTML (createElementNS/textContent only)"
    # createElementNS IS used (the SVG is genuinely DOM-built, not string-concatenated into innerHTML).
    assert "createElementNS" in js


def test_c43_stage2a_source_csp_sweep():
    """SOURCE-LEVEL CSP sweep of the modules Stage-2a touched: no inline on*= handler and no inline
    <script> block without src=. Mirrors test_serve_reconcile.py's sweep, extended to the Stage-2a
    additions. FAILS IF a new inline handler/script lands in a listed module."""
    from pathlib import Path
    pkg = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ("curatorpage.py", "app.py"):
        p = pkg / name
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""\bon[a-z]{3,}\s*=\s*['"\\]""", line):
                offenders.append(f"{name}:{i} (handler): {line.strip()[:90]}")
            if re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", line):
                offenders.append(f"{name}:{i} (inline <script>): {line.strip()[:90]}")
    assert offenders == [], "inline JS is dead under the CSP:\n" + "\n".join(offenders)


def test_stations_and_history_rendered_surfaces_csp_clean(tmp_path):
    """RENDERED CSP sweep of the new Stations + History tabs (served bytes). FAILS IF either ships an
    inline <script> or an on*= handler."""
    async def _body():
        surveys_live = _hub_survey(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for tab in ("stations", "history"):
                r = await client.get(f"/gateway/curator/survey/s2a-survey?tab={tab}")
                assert r.status_code == 200, (tab, r.status_code)
                for m in re.finditer(r"<script\b[^>]*>", r.text):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"{tab}: inline <script>: {m.group(0)}"
                assert re.findall(r"<[^>]*\son[a-z]{2,}\s*=", r.text) == [], f"{tab}: inline handler"
            # The stations.js route serves RAW JS (not <script>-wrapped), session-gated.
            r = await client.get("/gateway/curator/stations.js")
            assert r.status_code == 200
            assert "<script" not in r.text.lower()
    run(_body())


# ==================================================================================================
# History read-only (allowlist assertion, S1 fix-round F1 style)
# ==================================================================================================
def test_history_argv_is_read_only_log_verb():
    """HISTORY READ-ONLY PIN (allowlist style). The history-job argv carries ONLY the read-only `log`
    verb — never a mutating git verb. FAILS IF the argv's subcommand is anything but an allow-listed
    read-only verb (proven able to fail below by asserting a mutating verb is refused)."""
    from pathlib import Path
    argv = edit_mod._history_argv(Path("/srv/surveys/surveys/x"), Path("/srv/surveys"))
    verb = edit_mod._history_subcommand(argv)
    assert verb == "log", f"history argv subcommand must be 'log', got {verb!r}"
    assert verb in edit_mod._HISTORY_READONLY_VERBS
    # No mutating verb appears anywhere in the argv (belt-and-braces: the whole token list is scanned).
    mutating = {"commit", "push", "add", "rm", "reset", "checkout", "merge", "rebase", "clean",
                "tag", "branch", "fetch", "pull", "gc", "prune", "filter-branch", "update-ref"}
    assert not (set(argv) & mutating), f"history argv must carry no mutating verb: {argv}"


def test_history_job_refuses_non_read_only_verb(monkeypatch, tmp_path):
    """MUTATION-PROOF for the read-only assertion: if the argv builder is subverted to emit a mutating
    verb, run_history_job REFUSES (EditError, 'non-read-only') rather than running it — BEFORE any
    subprocess. FAILS IF a non-read-only verb can slip through the guard (proven able to fail: this is
    exactly the injected mutating-verb argv, and the pre-check must catch it)."""
    import pytest

    # A real package dir with a survey.yaml so the job passes its existence check and REACHES the
    # verb guard (the guard, not the missing-file branch, is what must fire).
    pkg = tmp_path / "surveys" / "x"
    pkg.mkdir(parents=True)
    (pkg / "survey.yaml").write_text("slug: x\n", encoding="utf-8")

    def _evil_argv(package_root, surveys_root):
        return ["git", "-C", str(package_root), "commit", "-m", "x"]

    monkeypatch.setattr(edit_mod, "_history_argv", _evil_argv)
    with pytest.raises(edit_mod.EditError, match="non-read-only"):
        edit_mod.run_history_job(pkg, surveys_root=tmp_path)


def test_history_tab_renders_real_git_log(tmp_path):
    """END-TO-END: the History tab renders the survey package's real git log (subject + release-note
    body, author, date) via the runner history read-job. FAILS IF the tab does not surface a committed
    change, or leaks a mutating action (rename/retire — Stage 4)."""
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live, slug="hist-survey",
                          yaml_text="schema_version: \"0.2\"\nslug: hist-survey\n"
                                    "project_name: Hist\nversion: 1.0.0\n")
        # Make surveys-live a REAL git repo so the history read-job has commits to read.
        root = surveys_live

        def git(*a):
            subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "curator@ausmt.local")
        git("config", "user.name", "AusMT Gateway")
        git("add", "-A")
        git("commit", "-qm", "initial import of hist-survey")
        (root / "surveys" / "hist-survey" / "survey.yaml").write_text(
            "schema_version: \"0.2\"\nslug: hist-survey\nproject_name: Hist\nversion: 1.1.0\n",
            encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "metadata edit by curator:alice\n\nfixed the citation author")

        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hist-survey?tab=history")
            assert r.status_code == 200
            assert "initial import of hist-survey" in r.text
            assert "metadata edit by curator:alice" in r.text
            assert "fixed the citation author" in r.text          # the release-note body renders
            # NO rename/retire ACTION in the History tab (Stage 4). Read-only: the History body carries
            # no <form> and no rename/retire action route. (The copy may mention "rename" descriptively
            # — the pin is on the absence of an ACTION, not the word.)
            history_body = r.text.split('history</h1>', 1)[-1]
            assert "<form" not in history_body, "the History tab must carry no action form (read-only)"
            assert "/rename" not in r.text and "/retire" not in r.text
    run(_body())


# ==================================================================================================
# Quarantine containment (preview-route style)
# ==================================================================================================
def _seed_quarantined(gw, cfg, *, slug="badsurvey", files=None):
    """Insert a submission, drive it SCANNED->QUARANTINED, and materialise a package tree on disk."""
    from gateway import db as db_mod
    from gateway import states as states_mod
    sid = db_mod.new_id()
    gw.db.insert_submission(submission_id=sid, zip_sha256="q" * 64, zip_bytes=10,
                            submitter_name="Bad Actor", submitter_email="b@example.org",
                            submitter_orcid=None, token_hash="q" * 64)
    gw.db.transition(sid, states_mod.SCANNED, actor="gateway", reason="clean")
    gw.db.transition(sid, states_mod.QUARANTINED, actor="runner",
                     reason="validator reported FAIL", slug=slug)
    pkg = cfg.quarantine_dir / sid / "package" / slug
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "survey.yaml").write_text("slug: %s\n" % slug, encoding="utf-8")
    for rel, text in (files or {}).items():
        dest = cfg.quarantine_dir / sid / "package" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return sid


def test_quarantine_view_lists_files_and_reason(tmp_path):
    """The quarantine detail view lists the package files + the refusal reason for a QUARANTINED
    submission. FAILS IF the file listing or the reason is absent."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            sid = _seed_quarantined(gw, cfg, files={"badsurvey/notes.txt": "hello"})
            r = await client.get(f"/gateway/curator/quarantine/{sid}")
            assert r.status_code == 200
            assert "validator reported FAIL" in r.text          # the refusal reason
            assert "notes.txt" in r.text                          # a listed package file
    run(_body())


def test_quarantine_containment_traversal_404s(tmp_path):
    """QUARANTINE CONTAINMENT PIN. A `..` traversal in the file subpath resolves outside the package
    root and 404s; a real package file serves with the safe attachment + nosniff discipline. FAILS IF a
    traversal escapes containment, or a served file is inline-renderable (no attachment/nosniff)."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            sid = _seed_quarantined(gw, cfg, files={"badsurvey/data.edi": ">HEAD\n"})
            # Plant a REAL file OUTSIDE the package root (a sibling reports/ dir) so the traversal pin is
            # NON-VACUOUS: with containment disabled, `../reports/secret.txt` would resolve to this
            # existing file and be SERVED. Containment must 404 it instead.
            outside = cfg.quarantine_dir / sid / "reports"
            outside.mkdir(parents=True, exist_ok=True)
            (outside / "secret.txt").write_text("curator-only report bytes", encoding="utf-8")
            # A real IN-PACKAGE file serves, forced to download, nosniff, under a locked-down CSP.
            ok = await client.get(f"/gateway/curator/quarantine/{sid}/file/badsurvey/data.edi")
            assert ok.status_code == 200
            assert ok.headers.get("content-disposition") == "attachment"
            assert ok.headers.get("x-content-type-options") == "nosniff"
            assert "default-src 'none'" in (ok.headers.get("content-security-policy") or "")
            # Traversals that escape the package root => 404. Use %2f (URL-encoded slash) so httpx does
            # NOT normalise the `..` away client-side — the encoded form reaches the handler as a
            # literal `../` subpath, proving SERVER-SIDE containment (not the client) stops it (the same
            # mechanism the preview-route containment test uses). The reports/secret.txt case is the
            # non-vacuous one: that file EXISTS one level above the package root, so a disabled
            # containment check would resolve to it and serve it.
            for evil in ("..%2f..%2f..%2f..%2fetc%2fpasswd", "..%2freports%2fsecret.txt",
                         "..%2freports%2fvalidate.json"):
                bad = await client.get(f"/gateway/curator/quarantine/{sid}/file/{evil}")
                assert bad.status_code == 404, (evil, bad.status_code)
                assert b"curator-only report bytes" not in bad.content
    run(_body())


def test_quarantine_non_quarantined_id_404s(tmp_path):
    """The quarantine surface 404s for an id that is NOT in QUARANTINE (no oracle for other states
    through this surface). FAILS IF a non-quarantined submission is inspectable here."""
    async def _body():
        from gateway.tests.conftest import seed_validated
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            vid = seed_validated(gw, cfg)   # a VALIDATED (not quarantined) submission
            r = await client.get(f"/gateway/curator/quarantine/{vid}")
            assert r.status_code == 404
    run(_body())


# ==================================================================================================
# Keys deltas (D7)
# ==================================================================================================
def test_key_note_stored_rendered_and_counts(tmp_path):
    """KEYS PIN. A note set on a key is stored (sqlite), rendered on the page, and the submission count
    + unused-key nudge render. FAILS IF the note round-trip breaks, the count is wrong, or the nudge is
    missing for a never-used key."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="field-team-1", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            csrf = csrf_for_session(client)
            # Set a note via the route.
            r = await client.post(f"/gateway/curator/uploaders/{kid}/note",
                                  data={"note": "for the SA field campaign", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.list_uploader_keys()[0].note == "for the SA field campaign"
            # Attribute two submissions to this uploader (audit trail) + one to another key.
            for i in range(2):
                gw.db.insert_submission(submission_id=("A%025d" % i)[:26].upper().replace(" ", "0"),
                                        zip_sha256="z%d" % i, zip_bytes=1, submitter_name="s",
                                        submitter_email="e", submitter_orcid=None,
                                        token_hash="t%d" % i, uploader_name="field-team-1")
            page = await client.get("/gateway/curator/uploaders")
            assert "for the SA field campaign" in page.text     # note rendered
            assert "never used" in page.text                     # unused-key nudge (never used)
            assert "uploader-key-rotation" in page.text          # rotation runbook link
            counts = gw.db.submission_counts_by_uploader()
            assert counts.get("field-team-1") == 2
    run(_body())


def test_key_note_absent_from_git_bound_artifacts(tmp_path):
    """PII-CONTAINMENT PIN (D2.5): a key note lives ONLY in sqlite — it NEVER enters surveys-live (the
    git-bound publication ledger). FAILS IF a note byte reaches any file under surveys-live."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        surveys_live = _hub_survey(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="k", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            csrf = csrf_for_session(client)
            needle = "NOTE-NEEDLE-DO-NOT-COMMIT-abc123"
            await client.post(f"/gateway/curator/uploaders/{kid}/note",
                              data={"note": needle, "csrf_token": csrf}, follow_redirects=False)
            # The needle is in the DB...
            assert gw.db.list_uploader_keys()[0].note == needle
            # ...and NOWHERE under surveys-live (the only git-bound tree the gateway touches).
            from pathlib import Path
            for p in Path(surveys_live).rglob("*"):
                if p.is_file():
                    assert needle not in p.read_bytes().decode("utf-8", "replace"), (
                        f"key note leaked into git-bound artifact {p}")
    run(_body())


def test_revoked_key_renders_read_only(tmp_path):
    """A revoked key stays listed as an audit row with NO note editor and NO revoke button (read-only).
    FAILS IF a revoked row offers an editable note form or a revoke action."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="old-key", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            gw.db.set_uploader_key_note(kid, note="the revoked note")
            assert gw.db.revoke_uploader_key(kid, revoked_by=CURATOR_NAME) is True
            page = await client.get("/gateway/curator/uploaders")
            assert page.status_code == 200
            assert "revoked" in page.text
            assert "the revoked note" in page.text                # note shown read-only
            # No note-editor FORM and no revoke FORM target this revoked key id.
            assert f"/gateway/curator/uploaders/{kid}/note" not in page.text
            assert f"/gateway/curator/uploaders/{kid}/revoke" not in page.text
    run(_body())


def test_revoked_key_note_post_refused(tmp_path):
    """F6 PIN (architect ruling — revoked keys are IMMUTABLE audit rows). A note POST to a REVOKED key
    id is refused 4xx and the stored note is UNCHANGED — the UI hiding the editor is not the
    enforcement; the route + the DB `AND revoked_utc IS NULL` guard are. FAILS IF the route accepts a
    note update on a revoked id (the shipped pre-fix behaviour, 'by-design' docstring overruled), or
    the DB layer alone would have persisted it."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="frozen-key", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            assert gw.db.set_uploader_key_note(kid, note="frozen at revocation") is True
            assert gw.db.revoke_uploader_key(kid, revoked_by=CURATOR_NAME) is True
            csrf = csrf_for_session(client)
            r = await client.post(f"/gateway/curator/uploaders/{kid}/note",
                                  data={"note": "mutated after revoke", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 409, (r.status_code, r.text)
            key = gw.db.get_uploader_key(kid)
            assert key.note == "frozen at revocation", "the revoked key's note must be unchanged"
            # DB-layer guard is independent (belt-and-braces under the route check).
            assert gw.db.set_uploader_key_note(kid, note="direct DB mutation") is False
            assert gw.db.get_uploader_key(kid).note == "frozen at revocation"
    run(_body())


def test_note_and_create_length_caps(tmp_path):
    """F5 PIN. Over-length inputs are REFUSED (400) and nothing persists beyond the cap: a 2001-char
    note POST leaves the stored note unchanged; an over-length name/email on create creates no key.
    (Cap posture: REJECT, not truncate — silently dropping the tail of a curator's text loses
    information without telling them.) FAILS IF an over-length value persists or is truncated in."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="cap-key", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            csrf = csrf_for_session(client)
            # Over-length note => 400, stored note unchanged (None).
            r = await client.post(f"/gateway/curator/uploaders/{kid}/note",
                                  data={"note": "x" * 2001, "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 400, (r.status_code, r.text)
            assert gw.db.get_uploader_key(kid).note is None
            # Exactly at the cap => accepted (the cap is inclusive).
            r = await client.post(f"/gateway/curator/uploaders/{kid}/note",
                                  data={"note": "y" * 2000, "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.get_uploader_key(kid).note == "y" * 2000
            # Over-length NAME on create => 400, no key row created.
            n_before = len(gw.db.list_uploader_keys())
            r = await client.post("/gateway/curator/uploaders/create",
                                  data={"name": "n" * 121, "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert len(gw.db.list_uploader_keys()) == n_before
            # Over-length EMAIL on create => 400, no key row created.
            r = await client.post("/gateway/curator/uploaders/create",
                                  data={"name": "ok-name", "email": "e" * 255, "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 400
            assert len(gw.db.list_uploader_keys()) == n_before
    run(_body())


# ==================================================================================================
# S2a-5 build-id display shortener
# ==================================================================================================
def test_build_id_shortener_canonical_and_verbatim_fallback():
    """S2a-5 PIN. A canonical triple-barrel build id shortens to '<source short> · HH:MM UTC'; a
    malformed id falls back VERBATIM (never hide information). FAILS IF the canonical form is not
    shortened, or a malformed id is mangled/hidden instead of shown verbatim."""
    canon = "252a96fed49c74477ed24e159e6689c8100fcb4c-b898f26-2026-07-10T06:00:39.252632+00:00"
    assert builddisplay.short_build_id(canon) == "b898f26 · 06:00 UTC"
    assert builddisplay.short_build_id(
        "252a96fed49c74477ed24e159e6689c8100fcb4c-b898f26-2026-07-10T06:00:39Z") == "b898f26 · 06:00 UTC"
    assert builddisplay.short_build_id("unknown-unknown-2026-07-10T06:00:39+00:00") == "unknown · 06:00 UTC"
    # Malformed => verbatim.
    assert builddisplay.short_build_id("not-a-build-id") == "not-a-build-id"
    assert builddisplay.short_build_id("just some text with no barrels") == "just some text with no barrels"
    assert builddisplay.short_build_id("") == ""
    assert builddisplay.short_build_id(None) == ""


def test_build_id_shortener_mirrored_in_chip_and_panel_js():
    """SOURCE ASSERTION: both the drift chip (CONTEXT_BAR_JS) and the Served-build card (SERVE_PANEL_JS)
    embed the shortBuildId mirror AND set the full id on hover via a title attribute (not markup).
    FAILS IF either chrome drops the shortener or the full-id-on-hover affordance."""
    for const in (curatorpage.CONTEXT_BAR_JS, curatorpage.SERVE_PANEL_JS):
        assert "function shortBuildId(id)" in const, "the shortener mirror must be in both JS constants"
        assert "setAttribute('title'" in const, "the full id must be available on hover (title attr)"
