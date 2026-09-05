"""releases.html: the citable-snapshot listing page, portal half.

The page lists the quarterly releases cut by engine/extract/cut_release.py. Everything it says about a
release is READ at load time from the served release index and the per-release release.json, so the two
ways this page could lie are (a) baking a release fact into the markup where it would silently go stale,
and (b) reporting "no releases cut yet" when the truth is "this request could not find out". The
behavioural half of that is driven in jsdom by tools/releases_test.js; this module pins the static half,
plus the chrome that makes it look like the rest of the portal.

Each assertion states its failure criterion:

  * PALETTE - FAILS if releases.html's five D+ surface/accent tokens are not byte-identical to
    about.html's. (tests/test_theme_tokens.py pins index/about/add-survey against each other; this is
    the same guard extended to the new page without editing that module's file list.)
  * HEADER PARITY - FAILS if releases.html's header is not the same three-zone header about.html
    carries: the same nav ids in the same order, the same six centre items in the same order, exactly
    one .counts block in the right zone. Non-vacuous: a page with a hand-rolled header trips every line.
  * NO APP STATE - FAILS if the page carries index's live map-state ids (nVis/nSel/nTot), which have no
    meaning on a page with no map, no filter and no selection.
  * FOOTER CHROME - FAILS if the footer keeps the retired About-this-build popover or a version
    chip, loses the bottom-left MTCAT link, or does not carry the AuScope-NCRIS lockup the
    one-footer rule put in the right region on every surface.
  * NO INLINE SCRIPT - FAILS if the page carries an inline <script> block. The deployed CSP for every
    page except add-survey.html is script-src 'self' with no 'unsafe-inline' (@strictPages in
    deploy/docker/caddy/Caddyfile is a `not path /add-survey.html` matcher, so a NEW page picks up the
    strict policy automatically); an inline block here would be blocked in production only.
  * NOTHING HARD-CODED - FAILS if a release tag, DOI, doi.org URL or count is baked into the markup, or
    if the list container does not ship empty and hidden.
  * EMPTY STATE - FAILS if the agreed empty-state sentence is not present verbatim, or if the
    could-not-be-read state is missing or says the same thing as the empty state.
  * NO DEAD LINK - FAILS if the pending-DOI marker is ever emitted as an anchor.
  * SAFE RENDERING - FAILS if releases.js reaches the DOM through innerHTML: every value it renders
    (tags, notes, commits, file paths) comes from a served JSON document.
  * THE ENTRY POINT - FAILS if about.html's Documentation section stops linking this page, or if a
    Releases link comes back to index.html's footer. The rule took the link out of every footer
    and the #build colophon that first inherited it is deleted, so section 8 is the page's one
    route in.
"""
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # portal/
RELEASES = ROOT / "releases.html"
RELEASES_JS = ROOT / "releases.js"
ABOUT = ROOT / "about.html"
INDEX = ROOT / "index.html"
DRIVER = ROOT / "tools" / "releases_test.js"

EMPTY_STATE = "No releases cut yet; releases are quarterly snapshots of the corpus."

_VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "base", "col", "embed",
         "param", "track", "wbr"}


class _Zone(HTMLParser):
    """Records every start tag with its attributes plus which of <header>/<footer> it sits inside, so
    the assertions run against the parsed DOM rather than raw text (HTML comments never reach
    handle_starttag, so a commented-out example cannot pass a structural pin)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []          # (tag, attrs, in_header, in_footer, in_nav, in_aboutbuild)
        self._d = {"header": 0, "footer": 0, "nav": 0}
        self._ab_at = None          # footer depth at which a details.aboutbuild opened

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        self.elements.append((tag, d,
                              self._d["header"] > 0 or tag == "header",
                              self._d["footer"] > 0 or tag == "footer",
                              self._d["nav"] > 0 or tag == "nav",
                              self._ab_at is not None))
        for zone in self._d:
            if tag == zone:
                self._d[zone] += 1
            elif self._d[zone] > 0 and tag not in _VOID:
                self._d[zone] += 1
        if self._ab_at is None and tag == "details" and "aboutbuild" in _classes(d):
            self._ab_at = self._d["footer"]

    def handle_endtag(self, tag):
        for zone in self._d:
            if self._d[zone] > 0 and tag not in _VOID:
                self._d[zone] -= 1
        if self._ab_at is not None and self._d["footer"] < self._ab_at:
            self._ab_at = None


def _classes(attrs):
    return set(attrs.get("class", "").split())


def _els(path):
    p = _Zone()
    p.feed(path.read_text(encoding="utf-8"))
    return p.elements


def _header(path):
    return [(t, a, in_nav) for (t, a, in_h, _f, in_nav, _ab) in _els(path) if in_h]


def _footer(path):
    return [(t, a, in_ab) for (t, a, _h, in_f, _n, in_ab) in _els(path) if in_f]


def test_releases_page_exists():
    assert RELEASES.exists(), "portal/releases.html is missing"
    assert RELEASES_JS.exists(), "portal/releases.js is missing"


# --- chrome ---------------------------------------------------------------------------------------

DPLUS = ("--ink", "--panel", "--panel-2", "--line", "--copper", "--text", "--muted")


def _token(css, name):
    m = re.search(re.escape(name) + r"\s*:\s*(#[0-9A-Fa-f]{6})", css)
    assert m, f"{name} not found"
    return m.group(1).upper()


def test_palette_matches_about():
    rel, abt = RELEASES.read_text(encoding="utf-8"), ABOUT.read_text(encoding="utf-8")
    for name in DPLUS:
        assert _token(rel, name) == _token(abt, name), (
            f"releases.html {name} is {_token(rel, name)}, about.html says {_token(abt, name)}; the "
            f"surface/accent tokens are declared verbatim on every page and must not split-brain")


def _nav_ids(path):
    return [a.get("id") for (_t, a, in_nav) in _header(path) if in_nav and a.get("id")]


def _centre_order(path):
    """The five primary header items in document order, each reduced to a stable label. Mirrors the
    reducer in test_about_uniform_chrome.test_header_parity_about_matches_index, including its
    styling of a stray .about item as 'other:<href>', which is how a sixth header entry (the retired
    How-to-use link, or a successor to it) shows up here instead of passing quietly."""
    out = []
    for _tag, a, in_nav in _header(path):
        if in_nav and a.get("id") in ("navMap", "navSurveys", "navCollections"):
            out.append(a["id"])
        elif "about" in _classes(a) and a.get("href") == "about.html":
            out.append("about")
        elif "about" in _classes(a):
            out.append("other:" + (a.get("href") or a.get("id") or _tag))
        elif "contribute" in _classes(a):
            out.append("contribute")
    return out


def test_header_parity_releases_matches_about():
    """Every shipped header is FIVE items, namely Map, Surveys, Collections, About, Contribute.
    Releases arrived on main carrying the retired sixth entry, a "How to use AusMT" link to
    about.html#howto, so this pin holds it to the five-item order the shipped header carries.
    Non-vacuous in both halves: run against that six-item header, the RELEASES assertion below fails
    with other:about.html#howto in slot four."""
    assert _nav_ids(RELEASES) == ["navMap", "navSurveys", "navCollections"], (
        f"releases.html nav must be navMap, navSurveys, navCollections in that order; "
        f"got {_nav_ids(RELEASES)}")
    assert _nav_ids(RELEASES) == _nav_ids(ABOUT), "releases.html and about.html nav ids diverge"

    expected = ["navMap", "navSurveys", "navCollections", "about", "contribute"]
    assert _centre_order(ABOUT) == expected, (
        "about.html's header changed shape; re-check what releases.html is being held to")
    assert _centre_order(RELEASES) == expected, (
        f"releases.html header items must run {expected}; got {_centre_order(RELEASES)}")

    counts = [a for (_t, a, _n) in _header(RELEASES) if "counts" in _classes(a)]
    assert len(counts) == 1, (
        f"the header must carry exactly one mono stats block (.counts) in its right zone; found {len(counts)}")
    assert "hidden" in counts[0], (
        "the corpus-totals block must ship hidden and be revealed only once the catalogue resolves, so a "
        "file:// page or an unpublished deployment shows nothing rather than a zero total")

    active = [a.get("id") for (_t, a, in_nav) in _header(RELEASES) if in_nav and "active" in _classes(a)]
    assert active == [], (
        f"releases.html must not highlight a view button (none of them is the current page); active={active}")


def test_no_live_app_state_ids():
    ids = {a.get("id") for (_t, a, *_r) in _els(RELEASES)}
    banned = {"nVis", "nSel", "nTot"} & ids
    assert not banned, (
        f"releases.html carries index's live map-state ids {sorted(banned)}; they describe a map, filter "
        f"and selection that do not exist on this page")


def test_footer_chrome_matches_the_other_pages():
    """The one-footer rule emptied the right region of Releases and About this build and put the
    AuScope-NCRIS lockup there instead, so the chrome this page must match is the new one. FAILS if
    the popover or a version chip comes back here, if the MTCAT link leaves the bottom-left, or if
    the lockup is missing. The strings and the targets are held for all six documents at once in
    tests/test_footer_regions.py; this is the same shape asserted from this page's own parsed DOM."""
    els = _footer(RELEASES)
    details = [a for (t, a, _ab) in els if t == "details" and "aboutbuild" in _classes(a)]
    assert not details, f"the About-this-build popover is retired from the footer; found {len(details)}"

    chips = [a for (t, a, _ab) in els if "data-ver-chip" in a]
    assert not chips, (
        "the version chip left the footer with the popover, and the about.html section that "
        "inherited it is deleted; no surface on this site carries one")

    apilinks = [a for (t, a, _ab) in els if "apilink" in _classes(a)]
    assert len(apilinks) == 1 and apilinks[0].get("href") == "data/mtcat.json", (
        "the machine-readable MTCAT link is pinned bottom-left in the footer on every page")

    logos = [a for (t, a, _ab) in els if t == "img" and "auscope-ncris-white.png" in a.get("src", "")]
    assert [a.get("alt") for a in logos] == ["AuScope and NCRIS"], (
        f"the footer must carry exactly one AuScope-NCRIS lockup, with its alt text; found {logos}")


# --- deployed-CSP and link safety -----------------------------------------------------------------

def test_scripts_are_external_only():
    """The scripts this page loads, and no others. The version chip left every surface with the
    About-this-build popover, so the script that filled it is gone from the tree as well as from
    this page; tests/test_about_uniform_chrome.py holds every page script the tree ships to being
    loaded by at least one page. Contract: LANE-CONTRACT-ABOUT-PAGE.md."""
    raw = RELEASES.read_text(encoding="utf-8")
    for src in ("config.js", "releases.js"):
        assert f'<script src="{src}"></script>' in raw, f"releases.html must load {src} as an external script"
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", raw, re.S)
    assert not [b for b in inline if b.strip()], (
        "releases.html must carry NO inline <script>: the deployed CSP for this page is script-src 'self' "
        "with no 'unsafe-inline', so an inline block would be blocked in production only")


def test_no_cdn_reference():
    hits = [ln for ln in RELEASES.read_text(encoding="utf-8").splitlines() if "cdnjs.cloudflare.com" in ln]
    assert not hits, f"releases.html must not load anything from a CDN: {hits}"


def test_external_links_carry_noopener_noreferrer():
    raw = RELEASES.read_text(encoding="utf-8")
    # The QUOTED form, which is the only way the bug tests/test_no_tabnabbing.py guards can appear
    # (target="_rel" / window.open(url, "_rel")). A bare-substring ban like that module's would trip on
    # this suite's own filename in a comment.
    assert '"_rel"' not in raw, 'found "_rel" (the reverse-tabnabbing target typo) in releases.html'
    blank = raw.count('target="_blank"')
    paired = raw.count('target="_blank" rel="noopener noreferrer"')
    assert blank == paired, "every target=\"_blank\" anchor must carry rel=\"noopener noreferrer\""

    js = RELEASES_JS.read_text(encoding="utf-8")
    assert '"_blank"' in js and '"noopener noreferrer"' in js, (
        "the DOI resolver link releases.js builds opens a third-party origin and must be created with "
        "target=_blank AND rel='noopener noreferrer'")


# --- honesty --------------------------------------------------------------------------------------

def test_nothing_about_a_release_is_hard_coded():
    raw = RELEASES.read_text(encoding="utf-8")
    body = raw.split("<body>", 1)[1]
    assert "doi.org" not in body, (
        "releases.html must not carry a DOI resolver URL: every DOI is read from the release documents "
        "at load time, so a baked-in one could only ever go stale or be wrong")
    assert not re.search(r"\b10\.\d{4,9}/\S", body), "a DOI is hard-coded into releases.html"
    assert not re.search(r"\b20\d\d-Q[1-4]\b", body), "a release tag is hard-coded into releases.html"

    lst = [a for (_t, a, *_r) in _els(RELEASES) if a.get("id") == "relList"]
    assert len(lst) == 1, "releases.html needs exactly one #relList container"
    assert "hidden" in lst[0], "#relList must ship hidden; releases.js reveals it only once rows exist"
    assert re.search(r'<div id="relList" hidden></div>', raw), (
        "#relList must ship EMPTY: every row is built from the served index, never from markup")


def test_empty_state_is_present_and_distinct_from_unreadable():
    raw = RELEASES.read_text(encoding="utf-8")
    msg = re.search(r'<span id="relEmptyMsg">(.*?)</span>', raw, re.S)
    assert msg and msg.group(1).strip() == EMPTY_STATE, (
        f"the agreed empty-state sentence is missing or reworded; expected {EMPTY_STATE!r}")

    states = {a.get("id"): a for (_t, a, *_r) in _els(RELEASES)
              if a.get("id") in ("relLoading", "relEmpty", "relError", "relList")}
    assert set(states) == {"relLoading", "relEmpty", "relError", "relList"}, (
        f"releases.html must carry all four page states; found {sorted(states)}")
    for sid in ("relEmpty", "relError", "relList"):
        assert "hidden" in states[sid], f"#{sid} must ship hidden"
    assert "hidden" not in states["relLoading"], (
        "#relLoading is the shipped-visible state: a reader whose fetch never resolves must be told the "
        "page is still reading, not shown a claim the page cannot yet support")

    body = raw.split("<body>", 1)[1]
    err = re.search(r'id="relError"[^>]*>(.*?)</div>', body, re.S)
    assert err and "could not be read" in err.group(1), (
        "the unreadable state must say the index could not be READ. 'Absent or empty' is a fact about "
        "the corpus; 'unreadable' is a fact about this request, and a routing problem must never be "
        "reported to every reader as 'no releases have ever been cut'")
    assert EMPTY_STATE not in err.group(1), "the unreadable state must not repeat the empty-state claim"


def test_both_missing_index_states_show_the_document_they_probed():
    """A 404 on the index has two very different causes: no release has been cut, or the release tier
    is not routed on this deployment (deploy/docker/caddy/Caddyfile roots /data/* at the CURRENT BUILD,
    so /data/releases/ needs its own handle_path block that does not exist yet). The sentence alone
    cannot distinguish them, so both states name the document they asked for. FAILS if either probe
    line is missing, or if it ships with a URL baked into the markup instead of the one really
    requested."""
    ids = {a.get("id"): a for (_t, a, *_r) in _els(RELEASES)}
    for probe, code in (("relEmptyProbe", "relEmptyPath"), ("relErrorProbe", "relErrorPath")):
        assert probe in ids and code in ids, f"releases.html is missing #{probe} / #{code}"
        assert "hidden" in ids[probe], (
            f"#{probe} must ship hidden so it can only ever state a URL that was really requested")
    raw = RELEASES.read_text(encoding="utf-8")
    for code in ("relEmptyPath", "relErrorPath"):
        assert f'<code id="{code}"></code>' in raw, (
            f"#{code} must ship EMPTY: releases.js fills it with the URL it actually fetched, which is "
            f"the only value that can be trusted to reflect this deployment's data_base_url")


def test_pending_doi_is_text_and_never_a_link():
    js = RELEASES_JS.read_text(encoding="utf-8")
    assert '"DOI: not yet minted"' in js, (
        "the reserved-as-text honesty pattern is the agreed wording for an unminted release")
    # The pending marker is built as a <span>, the resolvable one as an <a>. If the pending branch ever
    # created an anchor, the page would ship a resolver link that 404s for every reader.
    pending = re.search(r'el\("span", "pending", "DOI: not yet minted"\)', js)
    assert pending, "the pending DOI marker must be created as a plain <span>, never an anchor"


def _code(path):
    """The file with its // line comments and /* */ blocks stripped, so a pin on a code pattern cannot
    be satisfied or tripped by prose ABOUT that pattern."""
    src = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in src.splitlines())


def test_releases_js_never_uses_innerhtml():
    js = _code(RELEASES_JS)
    assert "innerHTML" not in js, (
        "releases.js renders tags, notes, commits and file paths that all originate in a served JSON "
        "document; they must reach the DOM through textContent, never innerHTML")


def test_releases_js_does_not_parse_the_catalogue():
    """The catalogue documents are LINKED, never parsed, so this page has no opinion about the MTCAT
    payload shape and nothing to break when the schema version moves. FAILS if releases.js starts
    reading fields out of mtcat.json."""
    js = _code(RELEASES_JS)
    for field in ("surveys[", ".stations", "related_identifiers", "schema_version"):
        assert field not in js, (
            f"releases.js reads {field!r}: it must only ever LINK the catalogue documents, not parse them")


# --- the entry point ------------------------------------------------------------------------------

def test_about_carries_the_entry_point_the_footer_gave_up():
    """The Releases link was in every footer until the one-footer rule; the page still needs ONE
    entry point or it is unreachable from the site. It was about.html's #build colophon, which also
    carried the running build's identity; that section is deleted and the identity is gone from the
    page, so the route alone survives in section 8, Documentation, beside the other places
    a reader is sent for more.

    FAILS if about.html's Documentation section stops linking releases.html, if the deleted colophon
    comes back to hold the link instead, or if a Releases link comes back to index.html's footer."""
    about = ABOUT.read_text(encoding="utf-8")
    assert '<section id="build">' not in about, (
        "the #build colophon is deleted; the entry point lives in section 8 now")
    section = about.split('<section id="docs">', 1)
    assert len(section) == 2, "about.html must carry the Documentation section that holds this entry point"
    assert 'href="releases.html"' in section[1].split("</section>", 1)[0], (
        "about.html's Documentation section must link releases.html, the page's only entry point "
        "since the footer gave the link up and the colophon that inherited it was deleted")
    els = _footer(INDEX)
    links = [a for (t, a, _ab) in els if t == "a" and a.get("href") == "releases.html"]
    assert not links, (
        f"index.html's footer carries no Releases link: {links}")


# --- behaviour ------------------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_releases_page_behaviour():
    """Drives the REAL releases.js against the REAL releases.html in jsdom (tools/releases_test.js):
    structure, citation text, the two DOI outcomes, and the honesty states. Skips when the jsdom
    dev-dependency is absent (CI runs `npm ci` in portal/ first)."""
    assert DRIVER.exists(), "tools/releases_test.js missing"
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if "Cannot find module 'jsdom'" in (r.stderr or ""):
        pytest.skip("jsdom not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, f"releases driver failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "RELEASES OK" in r.stdout, r.stdout
