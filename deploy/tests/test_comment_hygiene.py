"""A comment in the deploy and gateway trees states a constraint; git carries the provenance.

The third twin of portal/tests/test_comment_hygiene.py, over the two trees this workflow runs:
gateway-ci.yml invokes `pytest gateway/tests deploy/tests` and triggers on both `gateway/**` and
`deploy/**`, so a comment added to either is swept by the pull request that adds it.

The rule is the source-tier one: a comment may state what must hold and why it would break
otherwise, an invariant another file depends on, a bare pointer to the pin that holds it, or a
licence obligation. It may not carry design history, decision provenance, work-item identifiers,
dates, placeholders or commented-out code. Test files keep their pin semantics and may cite a
contract path, because that is how a pin is traced.

TWO EXCLUSIONS, both deliberate. This file is excluded from its own sweep, by basename, because the
vocabulary it forbids has to be written down somewhere to be forbidden. The vendored validator under
gateway/tests/fixtures is a byte-for-byte pinned copy of third-party production code whose sha is
the point of vendoring it, so it is not ours to rewrite; engine/pyproject.toml excludes it from lint
for the same reason.

Fails if: any comment on a covered surface matches the forbidden vocabulary, OR the extractor stops
seeing comments on a surface class at all (a scanner that reads nothing must not report PASS over
it).
"""
import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent        # deploy/
ROOT = DEPLOY.parent                                   # repo root
GATEWAY = ROOT / "gateway"

SELF = "test_comment_hygiene.py"
VENDORED = "vendored_validation"

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

CODE_LINE = re.compile(r"^(?:<script\b|L\.map\(|fetch\()")
LEADERS = ("<!--", "-->", "/*", "*/", "//", "*", "#")


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
    ".py": r'(?s:"""(?:.|\n)*?""")|(?m:^[ \t]*#.*$)',
}


def comments(path, text):
    """Every comment in one file, as (line number, text), each counted once."""
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


def offences(files):
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, comment in comments(path, text):
            labels = sorted({label for pattern, label in DENY if pattern.search(comment)})
            for line in comment.splitlines():
                if CODE_LINE.match(bare(line)):
                    labels.append("commented-out code")
                    break
            if labels:
                excerpt = " ".join(comment.split())[:110]
                where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
                found.append(f"{where}:{lineno}: {', '.join(sorted(set(labels)))}: {excerpt}")
    return found


def under(base):
    return [
        p for p in sorted(base.rglob("*.py"))
        if p.is_file() and p.name != SELF and VENDORED not in p.parts and "__pycache__" not in p.parts
    ]


def deploy_tree():
    return under(DEPLOY)


def gateway_tree():
    return under(GATEWAY)


SURFACES = {"the deploy tree": deploy_tree, "the gateway tree": gateway_tree}


def test_deploy_comments_state_constraints_only():
    hits = offences(deploy_tree())
    assert not hits, (
        f"{len(hits)} comment(s) in deploy/ carry provenance rather than a constraint:\n" + "\n".join(hits)
    )


def test_gateway_comments_state_constraints_only():
    hits = offences(gateway_tree())
    assert not hits, (
        f"{len(hits)} comment(s) in gateway/ carry provenance rather than a constraint:\n" + "\n".join(hits)
    )


def test_every_surface_class_is_actually_read():
    empty = []
    for label, files in SURFACES.items():
        found = files()
        assert found, f"{label}: no files matched, so this sweep would pass over nothing"
        seen = sum(len(comments(p, p.read_text(encoding='utf-8'))) for p in found)
        if seen == 0:
            empty.append(f"{label}: {len(found)} file(s), zero comments extracted")
    assert not empty, "the extractor read no comments at all on:\n" + "\n".join(empty)


def test_the_vendored_validator_is_left_alone():
    vendored = [p for p in GATEWAY.rglob("*.py") if VENDORED in p.parts]
    assert vendored, "the vendored validator is missing, so this exclusion would be silent"
    assert not [p for p in gateway_tree() if VENDORED in p.parts], (
        "the sweep reached into the vendored validator, whose bytes are a pinned third-party copy"
    )


def test_a_planted_comment_is_caught(tmp_path):
    f = tmp_path / "planted.py"
    f.write_text("a = 1\n# UX6 Wave B: the owner's ruling of 2026-08-19\n", encoding="utf-8")
    assert offences([f]), "the scanner did not catch a planted comment"


def test_a_clean_comment_is_not_flagged(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("# The two lists must stay equal; pinned by tests/test_frontdoor_ts_routes.py.\na = 1\n", encoding="utf-8")
    assert not offences([f]), "the scanner flagged a comment that states a constraint and a pin"
