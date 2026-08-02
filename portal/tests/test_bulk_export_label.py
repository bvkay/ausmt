"""The BULK-EXPORT LABEL contract: one token, two repositories of code, and the page that discloses it.

The portal's multi-file export marks its own file requests with a query flag so the server-log
aggregator can tell a drag-selected bulk export from a single station download. That flag is a
CROSS-SUBSYSTEM CONSTANT: portal/src/exports.js writes it and deploy/scripts/aggregate_stats.py reads
it, and the two lanes of CI never run each other's suites. Change the token on one side and the split
degenerates silently -- every bulk export starts counting as single, forever, with nothing red.

So the token is pinned HERE, in the portal lane (which gates portal/** and docs/docs/**), and mirrored
in deploy/tests (which gates deploy/** and gateway/**). Whichever side is edited, its own lane fails.

The disclosure is pinned in the same module for the same reason: the flag is the ONE thing the portal
deliberately puts into the access log, the public analytics page is where that is disclosed, and
docs/docs/** triggers this lane. A change that adds a label without disclosing it, or removes the
disclosure while the label stays, fails here.

Pure stdlib + a regex over committed sources. No Node, no network, no skip.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
REPO = ROOT.parent
EXPORTS_JS = ROOT / "src" / "exports.js"
DRAWER_JS = ROOT / "src" / "drawer.js"
AGGREGATOR = REPO / "deploy" / "scripts" / "aggregate_stats.py"
DISCLOSURE = REPO / "docs" / "docs" / "introduction" / "usage-analytics.md"

_JS_FLAG = re.compile(r"""SEL_BULK_FLAG\s*=\s*["']([^"']+)["']""")
_PY_FLAG = re.compile(r"""^_SELECT_BULK_FLAG\s*=\s*["']([^"']+)["']""", re.M)


def _js_flag() -> str:
    m = _JS_FLAG.search(EXPORTS_JS.read_text(encoding="utf-8"))
    assert m, f"{EXPORTS_JS} must declare SEL_BULK_FLAG; the export label has no other source"
    return m.group(1)


def _py_flag() -> str:
    m = _PY_FLAG.search(AGGREGATOR.read_text(encoding="utf-8"))
    assert m, f"{AGGREGATOR} must declare _SELECT_BULK_FLAG; the fold has no other source"
    return m.group(1)


def test_the_portal_and_the_aggregator_agree_on_the_flag():
    """CROSS-SUBSYSTEM PIN. The producer and the consumer of the label must name the same token. FAILS
    IF either side is edited alone, which is a silent failure everywhere else: the fold keeps working,
    every export simply reclassifies as a single download and nothing goes red."""
    assert AGGREGATOR.is_file(), "this pin runs from a full checkout (portal-ci lane), never skipped"
    js, py = _js_flag(), _py_flag()
    assert js == py, (f"portal/src/exports.js writes {js!r} and deploy/scripts/aggregate_stats.py "
                      f"reads {py!r}; a bulk export would be counted as a single download")
    assert "=" in js and "?" not in js and "&" not in js, \
        f"the flag is one whole query PARAMETER, not a query string: {js!r}"


def test_only_the_bulk_export_flow_writes_the_flag():
    """SINGLE-WRITER PIN. An unlabelled fetch is what "single" means downstream, so the label must be
    written at ONE call site. The drawer's per-station download links go through a different helper and
    must stay unlabelled; a stray flag there would silently reclassify every single download as bulk.
    FAILS IF the token appears in any portal source other than the export module."""
    flag = _js_flag()
    offenders = [str(p.relative_to(REPO)) for p in sorted((ROOT / "src").glob("*.js"))
                 if p != EXPORTS_JS and flag in p.read_text(encoding="utf-8")]
    assert offenders == [], f"only the export flow may write {flag!r}; also found in {offenders}"
    assert flag not in DRAWER_JS.read_text(encoding="utf-8"), \
        "a labelled single-station download would reclassify every single download as a bulk one"


def test_the_public_analytics_page_discloses_the_label():
    """DISCLOSURE PIN. The flag is the one thing the portal puts INTO the access log rather than
    reading out of it, and the public analytics page is where that is disclosed. It must name the flag
    exactly, and it must state what is NOT added: no extra request, nothing about who is asking. FAILS
    IF the label ships undisclosed, or if the disclosure is vague about what the flag is."""
    assert DISCLOSURE.is_file(), "this pin runs from a full checkout (portal-ci lane), never skipped"
    text = DISCLOSURE.read_text(encoding="utf-8")
    assert f"`{_js_flag()}`" in text, "the disclosure must name the flag it is disclosing"
    assert "No separate request is made for the label" in text, \
        "and must say the label adds no request of its own"
    assert "nothing about who is asking is recorded" in text, "and adds no identity"
    assert "single-station download links in a station drawer carry no flag" in text, \
        "and that the unlabelled path is what makes an unlabelled fetch mean 'single'"
