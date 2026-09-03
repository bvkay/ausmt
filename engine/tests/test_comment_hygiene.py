"""A comment in the engine states a constraint; git carries the provenance.

The twin of portal/tests/test_comment_hygiene.py, over the engine's own tree. Two kinds of surface
live here and both are held to the same rule. The SERVED tier is the CSS _pages.py inlines into
every page it emits, so those comment bytes are multiplied by the corpus and are capped as well as
swept. The SOURCE tier is engine/extract, engine/scripts and this suite: a comment may state what
must hold and why it would break otherwise, an invariant another file depends on, a bare pointer to
the pin that holds it, or a licence obligation, and may not carry design history, decision
provenance, work-item identifiers, dates, placeholders or commented-out code. Test files keep their
pin semantics and may cite a contract path, because that is how a pin is traced.

IMAGE TOPOLOGY. Every path this module reads is under engine/, which deploy/docker/engine.Dockerfile
COPYs to /app/engine, so this test runs identically on a checkout and inside the engine image and
needs no skip. It must stay that way: reaching for portal/, docs/ or .github/ from here would make
the module skip or fail in the image lanes, where those trees are not shipped. The portal half of
the sweep therefore lives in portal/tests, which runs on a checkout.

THIS FILE IS EXCLUDED FROM ITS OWN SWEEP, by basename, because the vocabulary it forbids has to be
written down somewhere to be forbidden.

Fails if: any comment on a covered surface matches the forbidden vocabulary, OR the served CSS
carries more comment bytes than its cap, OR the extractor stops seeing comments on a surface class
at all (a scanner that reads nothing must not report PASS over it).
"""
import ast
import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent       # engine/

SELF = "test_comment_hygiene.py"

DENY = (
    # OWNER in capitals is a shell variable this repo's compose files carry, so a comment naming
    # it is naming an identifier, not recording who decided something.
    (re.compile(r"\b(?!(?-i:OWNER)\b)owner(?:'s|s)?\b", re.I), "decision-owner language"),
    (re.compile(r"\brulings?\b", re.I), "ruling language"),
    # Approval OF A DESIGN DECISION, which is what may not be recorded here. The bare word is
    # left alone: "Approved-by:" is a git trailer this code writes, and a curator approving a
    # submission is the gateway's own workflow, not a note about who settled an argument.
    (re.compile(r"\bowner[-\s]approved\b|\bapproved\s+(?:by\s+the\s+owner|mockup|preview|design|wording|copy)\b",
                re.I), "approval language"),
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

CODE_LINE = re.compile(r"^(?:<script\b|L\.map\(|fetch\()")
LEADERS = ("<!--", "-->", "/*", "*/", "//", "*", "#")

# A comment that OPENS on a bare work-item tag, which the vocabulary list cannot see because the
# tag is the whole identifier. Held over the served tier only, the one measured in bytes.
LEAD_TAG = re.compile(r"^[A-Z]{1,3}\d{1,2}[a-z]?\b\s*[:.,()\-]")

# The served CSS is inlined into every emitted page, so its comment bytes are paid once per page in
# the corpus rather than once in the tree.
SERVED_CSS_CAP = 1_200


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


# One left-to-right scan per file, so every comment is counted once and only once. A separate pass
# per syntax double-counts twice over: a // line inside a /* */ block is read by both, and so is a
# /* that a line comment happens to contain, such as the glob contract/*.json. Both overstate the
# bytes, which would let a cap pass on an artefact instead of on the sweep.
SYNTAX = {
    ".html": r"(?s:<!--.*?-->)|(?s:/\*.*?\*/)",
    ".js": r"(?s:/\*.*?\*/)|(?m:^[ \t]*//.*$)",
    ".css": r"(?s:/\*.*?\*/)",
}
HASH = re.compile(r"(?m:^[ \t]*#.*$)")


def python_comments(text):
    """A Python file's # comments and its REAL docstrings.

    A triple-quoted string is not a docstring by virtue of its quotes: gateway/curatorpage.py holds
    the curator console's HTML and its browser-side scripts in them, and a regex that reads those as
    comments reports the served page as a wall of offences. The AST is what tells the two apart, so
    the sweep lands on the module's own prose and never on a template it serves."""
    out = [(text.count("\n", 0, m.start()) + 1, m.group(0)) for m in HASH.finditer(text)]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return sorted(out)
    starts, total = [], 0
    for line in text.splitlines(keepends=True):
        starts.append(total)
        total += len(line)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        first = node.body[0] if node.body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            c = first.value
            out.append((c.lineno, text[starts[c.lineno - 1] + c.col_offset:
                                       starts[c.end_lineno - 1] + c.end_col_offset]))
    return sorted(out)


def comments(path, text):
    """Every comment in one file, as (line number, text), each counted once."""
    if path.suffix == ".py":
        return python_comments(text)
    pattern = SYNTAX.get(path.suffix)
    if not pattern:
        return []
    scanner = re.compile(pattern)
    out, pos = [], 0
    while True:
        match = scanner.search(text, pos)
        if not match:
            return out
        out.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
        pos = match.end()


def offences(files, served=False):
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        seen = comments(path, text)
        if served:
            # The served stylesheet is a CSS comment inside a Python string, which the Python
            # extractor sees only as one opaque literal. Read it as CSS as well, so the rule lands
            # on the block a reader of an emitted page would see.
            seen = seen + [(text.count("\n", 0, m.start()) + 1, m.group(0))
                           for m in re.finditer(r"(?s)/\*.*?\*/", text)]
        for lineno, comment in sorted(seen):
            labels = sorted({label for pattern, label in DENY if pattern.search(comment)})
            for line in comment.splitlines():
                if CODE_LINE.match(bare(line)):
                    labels.append("commented-out code")
                    break
            if served:
                head = next((bare(ln) for ln in comment.splitlines() if bare(ln)), "")
                if LEAD_TAG.match(head):
                    labels.append("work-item identifier")
            if labels:
                excerpt = " ".join(comment.split())[:110]
                where = path.relative_to(ENGINE.parent) if path.is_relative_to(ENGINE.parent) else path.name
                found.append(f"{where}:{lineno}: {', '.join(sorted(set(labels)))}: {excerpt}")
    return found


def listing(*globs):
    out = []
    for base, pattern in globs:
        out += [p for p in sorted(base.glob(pattern)) if p.is_file() and p.name != SELF]
    return out


def emitter():
    return [ENGINE / "extract" / "_pages.py"]


def extractors():
    return listing((ENGINE / "extract", "*.py"))


def scripts():
    return listing((ENGINE / "scripts", "*.py"))


def guard_tests():
    return listing((ENGINE / "tests", "*.py"))


SURFACES = {
    "the extractors": extractors,
    "the scripts": scripts,
    "the guard tests": guard_tests,
}


def served_css_comments():
    """The CSS comments _pages.py inlines into every page it emits."""
    text = (ENGINE / "extract" / "_pages.py").read_text(encoding="utf-8")
    return re.findall(r"(?s)/\*.*?\*/", text)


# ---------------------------------------------------------------------------
# The served tier: what every emitted page carries.
# ---------------------------------------------------------------------------
def test_served_css_comments_state_constraints_only():
    hits = offences(emitter(), served=True)
    assert not hits, (
        f"{len(hits)} comment(s) in the page emitter carry provenance rather than a constraint "
        "(its stylesheet is inlined into every page the engine emits):\n" + "\n".join(hits)
    )


def test_served_css_stays_under_its_comment_cap():
    found = served_css_comments()
    assert found, "no CSS comments were extracted from the emitter, so this cap would pass over nothing"
    got = sum(len(c.encode("utf-8")) for c in found)
    assert got <= SERVED_CSS_CAP, (
        f"the served stylesheet carries {got:,} bytes of comments, cap {SERVED_CSS_CAP:,}; "
        "every emitted page in the corpus pays this once"
    )


# ---------------------------------------------------------------------------
# The source tier.
# ---------------------------------------------------------------------------
def test_extractor_comments_state_constraints_only():
    hits = offences(extractors())
    assert not hits, (
        f"{len(hits)} comment(s) in engine/extract carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_script_comments_state_constraints_only():
    hits = offences(scripts())
    assert not hits, (
        f"{len(hits)} comment(s) in engine/scripts carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_guard_test_comments_state_constraints_only():
    hits = offences(guard_tests())
    assert not hits, (
        f"{len(hits)} comment(s) in engine/tests carry provenance rather than a constraint "
        "(a pin may cite the contract that it holds; it may not carry dates, decision provenance "
        "or work-item identifiers):\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# Image topology, and non-vacuity.
# ---------------------------------------------------------------------------
def test_every_path_this_module_reads_is_inside_the_engine_tree():
    outside = []
    for files in SURFACES.values():
        for path in files() + emitter():
            if not path.resolve().is_relative_to(ENGINE):
                outside.append(str(path))
    assert not outside, (
        "this module reads outside engine/, which the engine image does not ship, so it would "
        "skip or fail in the image lanes:\n" + "\n".join(outside)
    )


def test_every_surface_class_is_actually_read():
    empty = []
    for label, files in SURFACES.items():
        found = files()
        assert found, f"{label}: no files matched, so this sweep would pass over nothing"
        seen = sum(len(comments(p, p.read_text(encoding="utf-8"))) for p in found)
        if seen == 0:
            empty.append(f"{label}: {len(found)} file(s), zero comments extracted")
    assert not empty, "the extractor read no comments at all on:\n" + "\n".join(empty)


def test_a_planted_comment_is_caught(tmp_path):
    f = tmp_path / "planted.py"
    f.write_text("a = 1\n# UX6 Wave B: the owner's ruling of 2026-08-19\n", encoding="utf-8")
    assert offences([f]), "the scanner did not catch a planted comment"


def test_a_planted_work_item_tag_is_caught_on_the_served_tier(tmp_path):
    f = tmp_path / "planted_tag.py"
    f.write_text('_CSS = """\n/* C18: the cache seam. */\n"""\n', encoding="utf-8")
    assert not offences([f]), "the vocabulary list alone should not see a bare work-item tag"
    assert offences([f], served=True), "the served-tier rule did not catch a bare work-item tag"


def test_a_clean_comment_is_not_flagged(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("# The two lists must stay equal; pinned by tests/test_index_pages.py.\na = 1\n", encoding="utf-8")
    assert not offences([f], served=True), "the scanner flagged a comment that states a constraint and a pin"
