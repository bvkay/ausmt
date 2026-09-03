"""A comment on a shipped surface states a constraint; git carries the provenance.

Every byte of a comment in portal/*.html and portal/src/*.js is downloaded by every visitor, so
the comments the portal ships are part of the product. This module holds the house rule over them:
a comment may state what must hold and why it would break otherwise, an invariant another file
depends on, a bare pointer to the pin that holds it, or a licence/attribution obligation. It may
not carry design history, decision provenance, work-item identifiers, dates, placeholders or
commented-out code.

The same rule reaches the source that WRITES shipped bytes (engine/extract/_pages.py, which is a
trigger path of this workflow for exactly that reason) and the generators and guard tests under
portal/. Test files keep their pin semantics and may cite a contract path, because that is how a
pin is traced; they are held to the vocabulary rule alone.

THIS FILE IS EXCLUDED FROM ITS OWN SWEEP, by basename, because the vocabulary it forbids has to be
written down somewhere to be forbidden. The engine and deploy twins carry the same exclusion for
the same reason.

The shipped surfaces carry one rule the others do not: a comment may not OPEN on a bare work-item
tag, which is an identifier the vocabulary list cannot see because the tag is the whole of it.

Fails if: any comment on a covered surface matches the forbidden vocabulary, OR a shipped document
carries more comment bytes than its cap, OR the extractor stops seeing comments on a surface class
at all (a scanner that reads nothing must not report PASS over it).
"""
import re
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent      # portal/
ROOT = PORTAL.parent                                 # repo root

SELF = "test_comment_hygiene.py"

# ---------------------------------------------------------------------------
# The forbidden vocabulary. Each entry is (pattern, what it is), and the label
# is what an offending comment is reported as.
# ---------------------------------------------------------------------------
DENY = (
    (re.compile(r"\bowner(?:'s|s)?\b", re.I), "decision-owner language"),
    (re.compile(r"\brulings?\b", re.I), "ruling language"),
    (re.compile(r"\bapproved\b", re.I), "approval language"),
    (re.compile(r"\bwave\s+[a-z]\b", re.I), "wave identifier"),
    (re.compile(r"\bux\d", re.I), "work-item identifier"),
    (re.compile(r"\btask\s*#", re.I), "work-item identifier"),
    (re.compile(r"\blanes?\b", re.I), "lane name"),
    (re.compile(r"\btreatments?\b", re.I), "design-history vocabulary"),
    (re.compile(r"old\s*->\s*new", re.I), "old-to-new history"),
    (re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b"), "dated note"),
    (re.compile(r"YOUR-"), "placeholder"),
    (re.compile(r"TODO\(", re.I), "unowned marker"),
    (re.compile(r"\bFIXME\b", re.I), "unowned marker"),
)

# A comment line that is code rather than prose. The leaders are stripped first, so the same
# three shapes are caught behind <!-- -->, /* */, // and #.
CODE_LINE = re.compile(r"^(?:<script\b|L\.map\(|fetch\()")
LEADERS = ("<!--", "-->", "/*", "*/", "//", "*", "#")

# A comment that OPENS on a bare work-item tag ("R10:", "C4 (", "X7:", "B4 -"). The vocabulary list
# above cannot see these, because the tag is the whole identifier. Anchored to the head of the
# comment, where such a tag always sits, so a hex value or a standard's name mid-sentence is safe.
# Held over the shipped surfaces only, which is where the sweep is measured in bytes.
LEAD_TAG = re.compile(r"^[A-Z]{1,3}\d{1,2}[a-z]?\b\s*[:.,()\-]")


def bare(line):
    s = line.strip()
    changed = True
    while changed:
        changed = False
        for lead in LEADERS:
            if s.startswith(lead):
                s = s[len(lead):].strip()
                changed = True
    return s


def comments(path, text):
    """Every comment in one file, as (line number, text)."""
    suffix = path.suffix
    patterns = []
    if suffix == ".html":
        patterns = [r"(?s)<!--.*?-->", r"(?s)/\*.*?\*/"]
    elif suffix == ".js":
        patterns = [r"(?s)/\*.*?\*/", r"(?m)^[ \t]*//.*$"]
    elif suffix == ".css":
        patterns = [r"(?s)/\*.*?\*/"]
    elif suffix == ".py":
        patterns = [r'(?s)"""(?:.|\n)*?"""', r"(?m)^[ \t]*#.*$"]
    out = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            out.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
    return sorted(out)


def offences(files, shipped=False):
    """Every forbidden comment across a set of files, as report lines."""
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, comment in comments(path, text):
            labels = sorted({label for pattern, label in DENY if pattern.search(comment)})
            for line in comment.splitlines():
                if CODE_LINE.match(bare(line)):
                    labels.append("commented-out code")
                    break
            if shipped:
                head = next((bare(ln) for ln in comment.splitlines() if bare(ln)), "")
                if LEAD_TAG.match(head):
                    labels.append("work-item identifier")
            if labels:
                excerpt = " ".join(comment.split())[:110]
                where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
                found.append(f"{where}:{lineno}: {', '.join(sorted(set(labels)))}: {excerpt}")
    return found


def comment_bytes(path):
    text = path.read_text(encoding="utf-8")
    return sum(len(c.encode("utf-8")) for _, c in comments(path, text))


def listing(*globs):
    out = []
    for base, pattern in globs:
        out += [p for p in sorted(base.glob(pattern)) if p.is_file() and p.name != SELF]
    return out


# The shipped documents, and the cap each one's comments may occupy. A cap is a measurement with
# modest headroom, not an aspiration: it is what stops the sweep being undone one paragraph at a
# time. The corresponding caps for the pages the engine emits live in the engine twin.
SHIPPED_HTML_CAPS = {
    "index.html": 18_000,
    "about.html": 8_000,
    "add-survey.html": 8_000,
    "releases.html": 5_000,
    "brand.html": 3_000,
    "404.html": 1_500,
}
SHIPPED_JS_CAP = 240_000


def shipped_html():
    return [PORTAL / name for name in SHIPPED_HTML_CAPS]


def shipped_js():
    return listing((PORTAL / "src", "*.js"))


def emitter():
    return [ROOT / "engine" / "extract" / "_pages.py"]


def generators():
    return listing((PORTAL / "tools", "*.py"), (PORTAL / "tools", "*.js"))


def guard_tests():
    return listing((PORTAL / "tests", "*.py"), (PORTAL / "tests", "*.js"))


SURFACES = {
    "shipped HTML": shipped_html,
    "shipped JS": shipped_js,
    "the page emitter": emitter,
    "the generators": generators,
    "the guard tests": guard_tests,
}


# ---------------------------------------------------------------------------
# The rule, per surface class.
# ---------------------------------------------------------------------------
def test_shipped_html_comments_state_constraints_only():
    hits = offences(shipped_html(), shipped=True)
    assert not hits, (
        f"{len(hits)} comment(s) in the shipped HTML carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_shipped_js_comments_state_constraints_only():
    hits = offences(shipped_js(), shipped=True)
    assert not hits, (
        f"{len(hits)} comment(s) in portal/src/*.js carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_page_emitter_comments_state_constraints_only():
    hits = offences(emitter(), shipped=True)
    assert not hits, (
        f"{len(hits)} comment(s) in the page emitter carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_generator_comments_state_constraints_only():
    hits = offences(generators())
    assert not hits, (
        f"{len(hits)} comment(s) in portal/tools carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_guard_test_comments_state_constraints_only():
    hits = offences(guard_tests())
    assert not hits, (
        f"{len(hits)} comment(s) in portal/tests carry provenance rather than a constraint "
        "(a pin may cite the contract that it holds; it may not carry dates, decision provenance "
        "or work-item identifiers):\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# The caps.
# ---------------------------------------------------------------------------
def test_each_shipped_document_stays_under_its_comment_cap():
    over = []
    for name, cap in SHIPPED_HTML_CAPS.items():
        got = comment_bytes(PORTAL / name)
        if got > cap:
            over.append(f"portal/{name}: {got:,} bytes of comments, cap {cap:,}")
    assert not over, "shipped documents over their comment cap (every byte ships to every visitor):\n" + "\n".join(over)


def test_shipped_scripts_stay_under_their_comment_cap():
    got = sum(comment_bytes(p) for p in shipped_js())
    assert got <= SHIPPED_JS_CAP, (
        f"portal/src/*.js carries {got:,} bytes of comments, cap {SHIPPED_JS_CAP:,}; "
        "the scripts are served to every visitor"
    )


# ---------------------------------------------------------------------------
# Non-vacuity: the scanner must be reading something, and it must catch a plant.
# ---------------------------------------------------------------------------
def test_every_surface_class_is_actually_read():
    empty = []
    for label, files in SURFACES.items():
        found = files()
        assert found, f"{label}: no files matched, so this sweep would pass over nothing"
        seen = sum(len(comments(p, p.read_text(encoding='utf-8'))) for p in found)
        if seen == 0:
            empty.append(f"{label}: {len(found)} file(s), zero comments extracted")
    assert not empty, "the extractor read no comments at all on:\n" + "\n".join(empty)


def test_a_planted_comment_is_caught_in_every_comment_syntax(tmp_path):
    plants = {
        "planted.html": "<p>x</p>\n<!-- UX6 Wave B: the owner's ruling of 2026-08-19 -->\n",
        "planted.js": "var a = 1;\n// UX6 Wave B: the owner's ruling of 2026-08-19\n",
        "planted.css": "a{color:red}\n/* UX6 Wave B: the owner's ruling of 2026-08-19 */\n",
        "planted.py": "a = 1\n# UX6 Wave B: the owner's ruling of 2026-08-19\n",
    }
    for name, body in plants.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        assert offences([f]), f"the scanner did not catch a planted comment in {name}"


def test_a_planted_commented_out_script_is_caught(tmp_path):
    f = tmp_path / "planted_block.html"
    f.write_text('<!--\n<script defer src="https://example.invalid/x.js"></script>\n-->\n', encoding="utf-8")
    hits = offences([f])
    assert hits and "commented-out code" in hits[0], "the scanner did not catch a commented-out script tag"


def test_a_clean_comment_is_not_flagged(tmp_path):
    f = tmp_path / "clean.js"
    f.write_text("// The two lists must stay equal; pinned by tests/test_footer_regions.py.\nvar a = 1;\n", encoding="utf-8")
    assert not offences([f]), "the scanner flagged a comment that states a constraint and a pin"


def test_a_planted_work_item_tag_is_caught_on_a_shipped_surface(tmp_path):
    f = tmp_path / "planted_tag.css"
    f.write_text("/* C18: the cache seam. */\na{color:red}\n", encoding="utf-8")
    assert not offences([f]), "the vocabulary list alone should not see a bare work-item tag"
    assert offences([f], shipped=True), "the shipped-surface rule did not catch a bare work-item tag"


def test_the_work_item_rule_does_not_flag_ordinary_prose(tmp_path):
    f = tmp_path / "prose.css"
    f.write_text("/* IPv4 addresses are truncated to /24; WCAG AA (4.5:1) is the floor. */\na{color:red}\n", encoding="utf-8")
    assert not offences([f], shipped=True), "the work-item rule flagged ordinary prose"
