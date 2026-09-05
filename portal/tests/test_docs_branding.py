"""AusMT branding on the documentation site, and the table rule that made it readable.

DOCS REFERENCE-GRADE, STAGE 2. The mkdocs readthedocs theme renders one bold line in the sidebar
header, either config.site_name or, with theme.logo set, an image INSTEAD of the name. The
layout is three lines, so docs/overrides/main.html replaces the theme's site_name block:

    line 1   the AuScope mark and the AusMT wordmark, side by side
    line 2   Australia's Magnetotelluric Data Portal
    line 3   Documentation, on its own line

The third line is the one worth a pin. "Documentation" beside the wordmark is the layout the theme
gives you for free (site_name is "AusMT Documentation"), so it is the shape this lockup drifts back
into the moment someone simplifies the override away. Each assertion states its failure criterion.

  * the lockup exists and is ordered           FAILS if the override stops emitting any of the three
                                               lines, or emits them out of order.
  * Documentation is its own block             FAILS if the Documentation span is nested inside the
                                               line-1 lockup, or if its CSS stops making it a block.
  * the mark is a real in-repo asset           FAILS if docs/docs/img/auscope-icon-white.png is
                                               missing or has drifted from the portal's vendored
                                               copy. The docs tree carries its own copy so the built
                                               site is self-contained; this keeps the two in step.
  * the mobile bar carries no third line       FAILS if the narrow-screen bar goes back to rendering
                                               config.site_name, which puts "AusMT Documentation" on
                                               one line.
  * mkdocs wires both files up                 FAILS if custom_dir or extra_css is dropped, which
                                               would leave the markup unstyled or the override dead.
  * table cells wrap                           FAILS if the stylesheet stops overriding the theme's
                                               white-space:nowrap on cells and on code spans in
                                               cells. That rule is why the reference field tables fit
                                               the content column instead of scrolling sideways.
  * no version list is hardcoded               FAILS if a literal docs-mtcat-<version> tag appears in
                                               mkdocs.yml or .readthedocs.yaml. Documentation
                                               versions follow the MTCAT schema version and are cut
                                               as annotated tags; a list in a config file would need
                                               editing at every bump and would go stale between them.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/
REPO = ROOT.parent                              # the ausmt monorepo root

OVERRIDE = REPO / "docs" / "overrides" / "main.html"
STYLESHEET = REPO / "docs" / "docs" / "css" / "ausmt.css"
MKDOCS = REPO / "docs" / "mkdocs.yml"
RTD = REPO / ".readthedocs.yaml"

DOCS_MARK = REPO / "docs" / "docs" / "img" / "auscope-icon-white.png"
PORTAL_MARK = ROOT / "vendor" / "auscope-icon-white.png"

TAGLINE = "Australia's Magnetotelluric Data Portal"


def _text(p):
    return p.read_text(encoding="utf-8")


def _site_name_block():
    """The body of the override's site_name block, which is the sidebar lockup."""
    body = _text(OVERRIDE)
    m = re.search(r"\{%\s*block site_name\s*%\}(.*?)\{%\s*endblock\s*%\}", body, flags=re.S)
    assert m, "docs/overrides/main.html must override the theme's site_name block"
    return m.group(1)


def test_the_sidebar_lockup_carries_the_three_lines_in_order():
    block = _site_name_block()
    positions = {}
    for label, needle in (("mark", "auscope-icon-white.png"),
                          ("wordmark", ">AusMT<"),
                          ("tagline", TAGLINE),
                          ("documentation", ">Documentation<")):
        i = block.find(needle)
        assert i >= 0, f"the sidebar lockup is missing its {label} ({needle!r})"
        positions[label] = i
    assert positions["mark"] < positions["wordmark"] < positions["tagline"] < positions["documentation"], (
        "the lockup must read mark, wordmark, tagline, Documentation, in that order; found "
        f"{sorted(positions, key=positions.get)}")


def test_documentation_is_not_inside_the_wordmark_line():
    """The rule, stated as markup: line 1 is the mark and the wordmark, and nothing else. If the
    Documentation span moves inside .ausmt-lockup it renders beside the wordmark whatever the CSS
    says, because that element is the flex row."""
    block = _site_name_block()
    lockup = re.search(r'<span class="ausmt-lockup">(.*?)</span>\s*</span>', block, flags=re.S)
    assert lockup, "the lockup row (.ausmt-lockup) must wrap the mark and the wordmark"
    assert "Documentation" not in lockup.group(1), (
        "Documentation must never sit inside .ausmt-lockup; that element is the mark-and-wordmark "
        "flex row, so anything in it renders on line 1")
    assert TAGLINE not in lockup.group(1), "the tagline is line 2, not part of the wordmark row"


def test_the_stylesheet_gives_the_last_two_lines_their_own_line():
    css = _text(STYLESHEET)
    for cls in (".ausmt-tagline", ".ausmt-docs"):
        m = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", css)
        assert m, f"{cls} must be styled in docs/docs/css/ausmt.css"
        assert "display: block" in m.group(1), (
            f"{cls} must be display:block so it takes its own line; the theme's header is inline")


def test_the_mark_is_the_portals_own_asset_byte_for_byte():
    """The docs sidebar's AuScope symbol is a COPY of the portal's vendored file, so the two must not
    drift. It is not the mark the portal HEADER carries: the AusMT dot mark is the site identity
    everywhere except about.html and this sidebar, both of which are waiting on the same
    decision."""
    assert DOCS_MARK.exists(), (
        "docs/docs/img/auscope-icon-white.png is the only brand asset the built site can reference; "
        "mkdocs copies docs/docs/, not portal/vendor/")
    assert PORTAL_MARK.exists(), "portal/vendor/auscope-icon-white.png is the source of that copy"
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    assert digest(DOCS_MARK) == digest(PORTAL_MARK), (
        "the docs copy of the AuScope symbol has drifted from the portal's vendored copy; the two "
        "copies of that one file must stay identical")


def test_the_mobile_bar_shows_the_wordmark_without_the_third_line():
    body = _text(OVERRIDE)
    m = re.search(r"\{%\s*block mobile_nav\s*%\}(.*?)\{%\s*endblock\s*%\}", body, flags=re.S)
    assert m, (
        "the narrow-screen bar must be overridden too; the theme renders config.site_name there, "
        "which is 'AusMT Documentation' on one line")
    block = m.group(1)
    assert "auscope-icon-white.png" in block and ">AusMT<" in block, (
        "the mobile bar carries the mark and the wordmark")
    assert "Documentation" not in block, (
        "the mobile bar must not carry the word Documentation beside the wordmark")
    assert "config.site_name" not in block, (
        "rendering config.site_name puts 'AusMT Documentation' back on one line")


def test_mkdocs_loads_the_override_and_the_stylesheet():
    conf = _text(MKDOCS)
    assert re.search(r"^\s*custom_dir:\s*overrides\s*$", conf, flags=re.M), (
        "mkdocs.yml must point theme.custom_dir at docs/overrides, or main.html is never read")
    assert re.search(r"^extra_css:", conf, flags=re.M) and "css/ausmt.css" in conf, (
        "mkdocs.yml must load css/ausmt.css, or the lockup renders with the theme's own header "
        "styling")


def test_table_cells_and_their_code_spans_are_released_from_nowrap():
    """The theme sets white-space:nowrap on every table cell, every header row and every inline code
    span. That is why the reference field tables scrolled sideways: a Note cell of several hundred
    characters became one line. Both halves of the override are pinned, because dropping either one
    brings the scrollbar back."""
    css = re.sub(r"/\*.*?\*/", "", _text(STYLESHEET), flags=re.S)   # selectors only, no prose
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    cells = [b for sel, b in blocks if "table.docutils td," in sel]
    code = [b for sel, b in blocks if "table.docutils td code," in sel]
    assert cells and "white-space: normal" in cells[0], (
        "table cells must set white-space:normal; the theme's nowrap is what forces the sideways "
        "scroll")
    assert code and "white-space: normal" in code[0], (
        "code spans inside cells must set white-space:normal too; the theme sets nowrap on every "
        "code span, and the reference tables are mostly code spans")
    assert code and "overflow-wrap" in code[0], (
        "code spans inside cells must be allowed to break; a path like "
        "engine/schema/build_report.schema.json is one unbreakable token wider than the column")


def test_no_documentation_version_is_hardcoded():
    """Documentation versions follow the MTCAT schema version and are cut as annotated
    docs-mtcat-<version> tags, activated in the Read the Docs project. Nothing in the repository
    enumerates them, so a cut needs no file change. A literal tag here would be stale by the next
    bump. The convention may be described in prose; only a concrete version is forbidden."""
    pinned = re.compile(r"docs-mtcat-\d")
    hits = []
    for p in (MKDOCS, RTD):
        for lineno, line in enumerate(_text(p).splitlines(), start=1):
            if pinned.search(line):
                hits.append(f"{p.relative_to(REPO)}:{lineno}: {line.strip()[:120]}")
    assert not hits, (
        "no concrete documentation version belongs in the build configuration; the tags are the "
        "version list. Found:\n" + "\n".join(hits))
