"""A comment in the deploy and gateway trees states a constraint; git carries the provenance.

The third twin of portal/tests/test_comment_hygiene.py, over the two trees this workflow runs:
gateway-ci.yml invokes `pytest gateway/tests deploy/tests` and triggers on both `gateway/**` and
`deploy/**`, so a comment added to either is swept by the pull request that adds it.

The rule is the source-tier one: a comment may state what must hold and why it would break
otherwise, an invariant another file depends on, a bare pointer to the pin that holds it, or a
licence obligation. It may not carry design history, decision provenance, work-item identifiers,
dates, placeholders, commented-out code or the name of a contract document. Test files keep their
pin semantics and may cite a contract path, because that is how a pin is traced.

DEPLOY IS NOT A PYTHON TREE. Most of what deploy/ ships is shell, YAML, systemd units, a Caddyfile
and a Makefile, and a Python-only sweep passed over all of it. The extractor reads a # comment in
any of those, trailing comments included, so the operator-facing scripts are held to the same rule
as the code.

TWO EXCLUSIONS, both deliberate. This file is excluded from its own sweep, by basename, because the
vocabulary it forbids has to be written down somewhere to be forbidden. The vendored validator under
gateway/tests/fixtures is a byte-for-byte pinned copy of third-party production code whose sha is
the point of vendoring it, so it is not ours to rewrite; engine/pyproject.toml excludes it from lint
for the same reason.

Fails if: any comment on a covered surface breaks the rule, OR the extractor stops seeing comments
on a surface class at all (a scanner that reads nothing must not report PASS over it), OR the three
pins stop carrying the same extractor.
"""
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent        # deploy/
ROOT = DEPLOY.parent                                   # repo root
GATEWAY = ROOT / "gateway"

SELF = "test_comment_hygiene.py"
VENDORED = "vendored_validation"


# --- shared extractor and vocabulary: begin ---------------------------------
# The three pins carry this block byte for byte. It cannot be imported from one
# place: engine/tests must read nothing outside engine/, which the engine image
# is the only tree to ship, so a shared module would make the engine pin skip
# in the image builds. deploy/tests holds the three copies equal instead.
#
# THE EXTRACTOR. One left-to-right scan per file, so every comment is counted
# once and only once: a // inside a /* */ block, a /* inside a line comment, a #
# inside a quoted shell word and a // inside a URL are none of them comments,
# and a scan that reads them as comments overstates the bytes a cap measures.
#
# The scanners are string-aware, which is what lets a comment AFTER code on the
# same line be counted: a regex anchored to the start of a line cannot tell a
# trailing comment from a slash inside a string. JavaScript is the hard case,
# because / is both division and the opening of a regex literal and a regex may
# contain \/\/. The tell is the token before the slash: a value (an identifier
# or number that is not a keyword, a ) or a ]) means division, anything else
# means a regex. That is the standard heuristic; it misreads only code that
# divides by a parenthesised expression and writes a comment marker inside the
# divisor.
_WORD = re.compile(r"[A-Za-z_$][\w$]*|\d[\w.]*")
_REGEX_OK_AFTER_WORD = {
    "return", "typeof", "case", "in", "of", "new", "delete", "void", "do",
    "instanceof", "else", "yield", "await", "throw",
}


def _skip_quoted(text, i, quote):
    """Index just past a ' or " string opened at i. An unterminated quote ends
    at the newline, so a lone apostrophe in prose cannot swallow the file."""
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        if c == "\n":
            return i
        i += 1
    return n


def _skip_regex(text, i):
    """Index just past a regex literal opened at i, character classes included."""
    n = len(text)
    i += 1
    in_class = False
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            return i
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            return i + 1
        i += 1
    return n


def _skip_template(text, i):
    """Index just past a template literal opened at i, ${} holes included. A
    comment written inside a hole is not extracted, a construct these trees do
    not contain; what matters is that the literal's own bytes, which are full of
    // in URLs and /* in markup, are never read as comments."""
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if c == "$" and i + 1 < n and text[i + 1] == "{":
            i = _skip_hole(text, i + 2)
            continue
        i += 1
    return n


def _skip_hole(text, i):
    """Index just past the `}` closing a `${` hole, nested strings included."""
    n = len(text)
    depth = 1
    while i < n and depth:
        c = text[i]
        if c in "'\"":
            i = _skip_quoted(text, i, c)
            continue
        if c == "`":
            i = _skip_template(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i


def js_comments(text):
    """(offset, text) for every // and /* */ comment in JavaScript, a comment
    trailing code on the same line included."""
    out = []
    i, n = 0, len(text)
    prev = ""
    prev_word = ""
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append((i, text[i:end]))
            i = end
            prev, prev_word = "", ""
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append((i, text[i:end]))
            i = end
            prev, prev_word = "", ""
            continue
        if c in "'\"":
            i = _skip_quoted(text, i, c)
            prev, prev_word = c, ""
            continue
        if c == "`":
            i = _skip_template(text, i)
            prev, prev_word = "`", ""
            continue
        word = _WORD.match(text, i)
        if word:
            prev_word = word.group(0)
            prev = prev_word[-1]
            i = word.end()
            continue
        if c == "/" and (prev_word in _REGEX_OK_AFTER_WORD
                         or (not prev_word and prev not in {")", "]"})):
            i = _skip_regex(text, i)
            prev, prev_word = "/", ""
            continue
        if not c.isspace():
            prev, prev_word = c, ""
        i += 1
    return out


def css_comments(text):
    """(offset, text) for every /* */ comment in CSS, quoted urls skipped."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append((i, text[i:end]))
            i = end
            continue
        if c in "'\"":
            i = _skip_quoted(text, i, c)
            continue
        i += 1
    return out


_TAG_OPEN = re.compile(r"<(script|style)\b([^>]*)>", re.I)
_JS_TYPES = {"", "text/javascript", "application/javascript", "module",
             "text/ecmascript", "application/ecmascript"}
_TYPE_ATTR = re.compile(r"""\btype\s*=\s*["']?([^"'\s>]*)""", re.I)


def html_comments(text):
    """(offset, text) for every <!-- --> comment, every CSS comment inside a
    <style> block and every JavaScript comment inside a <script> block. The
    inline scripts are the larger half of a shipped page's commentary and a
    scanner blind to them reports a page as clean that is not. A
    <script type="application/ld+json"> block is DATA: its https:// values are
    not comments and it is not read as JavaScript."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("<!--", i):
            end = text.find("-->", i)
            end = n if end < 0 else end + 3
            out.append((i, text[i:end]))
            i = end
            continue
        tag = _TAG_OPEN.match(text, i)
        if tag:
            name = tag.group(1).lower()
            close = re.compile(r"</%s\b" % name, re.I).search(text, tag.end())
            end = close.start() if close else n
            body = text[tag.end():end]
            if name == "style":
                out += [(tag.end() + k, c) for k, c in css_comments(body)]
            else:
                attr = _TYPE_ATTR.search(tag.group(2))
                if (attr.group(1).lower() if attr else "") in _JS_TYPES:
                    out += [(tag.end() + k, c) for k, c in js_comments(body)]
            i = end
            continue
        i += 1
    return out


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_QUOTE_OPENS_AFTER = set(" \t\n=:([,{$|&;>")
# A heredoc body is DATA the script writes, EXCEPT where it is the source an interpreter on the
# same line is about to run: there it is code, and its comments are comments on a surface this
# sweep covers. These scripts reach their interpreter through a probed variable ("$PY"), so the
# variable is resolved from the file rather than only the literal command being matched.
_INTERPRETER = re.compile(r"\b(python3|python|node|perl|bash|sh)\b")
_SHELL_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")


def _interpreter_vars(text):
    """The shell variables this file binds to an interpreter, in the two shapes these scripts use:
    a direct assignment, and the probe loop whose variable ranges over the candidates."""
    loops = {}
    for m in re.finditer(r"(?m)^[ \t]*for[ \t]+([A-Za-z_]\w*)[ \t]+in[ \t]+([^\n;]*)", text):
        found = _INTERPRETER.search(m.group(2))
        if found:
            loops[m.group(1)] = found.group(1)
    names = {}
    for m in re.finditer(r"(?m)^[ \t]*([A-Za-z_]\w*)=(\"?)([^\n\"]*)\2", text):
        value = m.group(3)
        found = _INTERPRETER.search(value)
        if found:
            names[m.group(1)] = found.group(1)
            continue
        ref = re.fullmatch(r"\$\{?([A-Za-z_]\w*)\}?", value.strip())
        if ref and ref.group(1) in loops:
            names[m.group(1)] = loops[ref.group(1)]
    return names


def _fed_to(prefix, interpreter_vars):
    """The interpreter this heredoc feeds, from the text before the << on its own line."""
    found = _INTERPRETER.search(prefix)
    if found:
        return found.group(1)
    for var in _SHELL_VAR.finditer(prefix):
        if var.group(1) in interpreter_vars:
            return interpreter_vars[var.group(1)]
    return None


def _scanner_for(interpreter):
    if interpreter in ("python", "python3"):
        return python_comments
    if interpreter == "node":
        return js_comments
    return hash_comments


def hash_comments(text):
    """(offset, text) for every # comment in a shell script, a YAML document, a
    systemd unit, a Caddyfile, a Makefile or a Dockerfile, a comment trailing a
    command on the same line included. A # opens a comment only at the start of
    a line or after whitespace, the rule shell and YAML share, so ${var#pattern}
    and a URL fragment stay code. A heredoc body is data the script WRITES and
    is skipped; a quote opens a string only at a token boundary, so an
    apostrophe inside an unquoted YAML scalar cannot swallow the rest of the
    file; and a #! shebang is a directive to the kernel, not commentary."""
    out = []
    interpreter_vars = _interpreter_vars(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"" and (i == 0 or text[i - 1] in _QUOTE_OPENS_AFTER):
            i = _skip_quoted(text, i, c)
            continue
        if c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
            here = _HEREDOC.match(text, i)
            if here:
                term = re.compile(r"^[ \t]*%s[ \t]*$" % re.escape(here.group(2)), re.M)
                stop = term.search(text, here.end())
                fed = _fed_to(text[text.rfind("\n", 0, i) + 1:i], interpreter_vars)
                if fed:
                    opens = text.find("\n", here.end())
                    opens = here.end() if opens < 0 else opens + 1
                    closes = stop.start() if stop else n
                    if closes > opens:
                        out += [(opens + at, body)
                                for at, body in _scanner_for(fed)(text[opens:closes])]
                i = stop.end() if stop else n
                continue
        if c == "#" and (i == 0 or text[i - 1] in " \t\n"):
            if i + 1 < n and text[i + 1] == "!" and text.count("\n", 0, i) == 0:
                end = text.find("\n", i)
                i = n if end < 0 else end
                continue
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append((i, text[i:end]))
            i = end
            continue
        i += 1
    return out


def python_comments(text):
    """A Python file's # comments and its commentary strings.

    The # comments come from the tokenizer, so a # inside a string literal is
    never read as one and a # trailing code on the same line always is. The
    commentary strings are every STATEMENT-level string expression the AST
    holds: a docstring is one of those, and so is a triple-quoted paragraph
    dropped into the middle of a function, which is commentary written with
    quotes and must not be the way around this rule. A string that is assigned
    or returned is a value and not commentary, which is how the console
    gateway/curatorpage.py serves and the stylesheet engine/extract/_pages.py
    serves stay out of the sweep as content."""
    out = []
    chars, total = [], 0
    for line in text.splitlines(keepends=True):
        chars.append(total)
        total += len(line)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out.append((chars[tok.start[0] - 1] + tok.start[1], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        out = [(m.start(), m.group(0)) for m in re.finditer(r"(?m)^[ \t]*#.*$", text)]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return sorted(out)
    # An AST column offset counts UTF-8 BYTES, not characters, so the slice is taken over the
    # encoded source. Slicing the str by those offsets overshoots by one position per non-ASCII
    # character earlier on the line, which silently returns a comment that is not the comment.
    raw = text.encode("utf-8")
    starts, total = [], 0
    for line in text.splitlines(keepends=True):
        starts.append(total)
        total += len(line.encode("utf-8"))
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if (isinstance(node, ast.Expr) and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            opens = starts[value.lineno - 1] + value.col_offset
            closes = starts[value.end_lineno - 1] + value.end_col_offset
            out.append((len(raw[:opens].decode("utf-8")), raw[opens:closes].decode("utf-8")))
    return sorted(out)


# .txt is here because the configuration classes LIST it: a requirements file and an allow-list
# carry a # comment like any other declared configuration, and a class the extractor cannot read
# reports green over whatever is written in it.
HASH_SUFFIXES = {".sh", ".bash", ".yml", ".yaml", ".service", ".timer", ".conf",
                 ".example", ".map", ".dockerfile", ".toml", ".cfg", ".ini", ".txt"}
HASH_NAMES = {"Caddyfile", "Makefile", "Dockerfile", ".gitignore", ".dockerignore"}


def source_text(path):
    """One file's text, with a leading byte-order mark removed. Python's own loader strips a BOM, so
    a module that carries one imports and its tests run; ast.parse does not, so the AST half of this
    extractor raises on it and the file's docstrings become invisible. A surface a scanner cannot
    read reports clean, which is the one failure this module may not have."""
    return path.read_text(encoding="utf-8-sig")


def comments(path, text):
    """Every comment in one file, as (line number, text), each counted once."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        found = python_comments(text)
    elif suffix in (".html", ".htm", ".plist", ".xml", ".svg"):
        found = html_comments(text)
    elif suffix in (".js", ".mjs", ".hujson", ".json5"):
        found = js_comments(text)
    elif suffix == ".css":
        found = css_comments(text)
    elif suffix in HASH_SUFFIXES or path.name in HASH_NAMES:
        found = hash_comments(text)
    else:
        return []
    return [(text.count("\n", 0, off) + 1, body) for off, body in found]


def comment_bytes(path):
    text = source_text(path)
    return sum(len(body.encode("utf-8")) for _, body in comments(path, text))


# THE VOCABULARY. A rule is a pattern, the label an offending comment is
# reported under, and any number of exemptions. An exemption reads the matched
# text and a BOUNDED window around it, never the rest of the comment: a
# lookahead that scans to the end of a module docstring lets one mention of a
# shell variable pages away excuse every use of the word, which is how a
# narrowing turns into a hole.
WINDOW = 60


class Rule:
    """An exemption is (pattern over the matched text or None, pattern over the
    window or None) and excuses a match when every part it names holds; a match
    is excused when ANY of the rule's exemptions does."""

    def __init__(self, pattern, label, exemptions=()):
        self.pattern = pattern
        self.label = label
        self.exemptions = exemptions

    def excused(self, text, match):
        window = text[max(0, match.start() - WINDOW):match.end() + WINDOW]
        for on_match, near in self.exemptions:
            if on_match is not None and not on_match.search(match.group(0)):
                continue
            if near is not None and not near.search(window):
                continue
            return True
        return False

    def hits(self, text):
        return [m for m in self.pattern.finditer(text) if not self.excused(text, m)]


RULES = (
    # OWNER in capitals is a shell variable the compose files carry, so naming
    # it beside AUSMT_ or calling it a variable is naming an identifier.
    # Everywhere else the word records who settled an argument, and the
    # exemption may read only the variable's own neighbourhood.
    Rule(re.compile(r"\bowner(?:'s|s)?\b(?!@)", re.I), "decision-owner language",
         ((re.compile(r"^OWNER$"), re.compile(r"AUSMT_|\bvariable\b|\benv\b")),)),
    Rule(re.compile(r"\brulings?\b|\bruled\b", re.I), "ruling language"),
    # Approval of a DESIGN DECISION is what may not be recorded here. The
    # gateway's own workflow, in which a curator approves a submission and the
    # code writes an `Approved-by:` trailer, is the one sense that survives, and
    # it survives only where that workflow is named beside the word.
    Rule(re.compile(r"\bapprov(?:e|es|ed|al|als|ing)\b", re.I), "approval language",
         ((None, re.compile(r"curat|submi|trailer|Approved-by|moderat|reviewer", re.I)),)),
    # Every spelling of it: "Cleanup wave (D)", "Wave-1", "wave 1", "DOCS WAVE".
    # A wave is a run of work, and the ordinary English senses of the word are
    # reworded rather than exempted, because an exemption here would be a hole
    # wide enough to write any wave name through.
    Rule(re.compile(r"\bwaves?\b", re.I), "wave identifier"),
    Rule(re.compile(r"\bux\d", re.I), "work-item identifier"),
    Rule(re.compile(r"\btask\s*#", re.I), "work-item identifier"),
    # A pin may cite the contract it holds, and those documents are named
    # LANE-CONTRACT-*.md and LANE-ADDENDUM-*.md, so a citation is not a lane
    # name. Everything else that says lane is.
    Rule(re.compile(r"\blanes?\b(?!-[A-Z])", re.I), "lane name"),
    Rule(re.compile(r"\btreatments?\b", re.I), "design-history vocabulary"),
    # An amendment is a change to a DECISION, which is the provenance git carries: "CVD amendment",
    # "as amended by D18", "FROZEN, with its amendments" each name a revision of a design rather
    # than the constraint that holds now, and a cut that takes the item number leaves the reader a
    # preposition with nothing after it. The ordinary English sense (a claim that must be amended)
    # is reworded rather than exempted, for the reason the wave rule gives. A LICENCE is amended by
    # its own instrument and that obligation survives, so the window must carry the licence.
    Rule(re.compile(r"\bamend(?:ment|ments|ed|s|ing)?\b", re.I), "design-amendment language",
         ((None, re.compile(r"CC-?BY|CC0|ODbL|Creative Commons|licen[cs]e", re.I)),)),
    Rule(re.compile(r"old\s*->\s*new", re.I), "old-to-new history"),
    Rule(re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b"), "dated note"),
    # A note dated to the MONTH is the same audit trail with one field dropped.
    # A bare 2026-08 is also a release tag and a version, so the rule wants the
    # grammar of a note around it: a preposition or an article in front, or a
    # word behind it.
    Rule(re.compile(r"\b(?:in|the|since|until|after|before)\s+20\d\d-[01]\d\b"
                    r"|\b20\d\d-[01]\d\b(?=\s+\w)", re.I), "dated note"),
    # A branch is where the work happened, which is provenance git already
    # carries. The slug is required to be hyphenated so that docs/reference and
    # the other ordinary paths stay paths.
    Rule(re.compile(r"\b(?:feat|fix|chore|docs)/[a-z0-9]+(?:-[a-z0-9]+)+(?![\w/-]|\.\w)"),
         "branch name"),
    # A slice, a review round, a numbered or lettered review finding and a numbered audit item are
    # all names for the piece of work a change belonged to. A NAMED review (adversarial, hostile,
    # security, code-health) is the sitting itself; an audit item is that sitting's numbering. The
    # ordinary sense of audit (an audit log, an audit tail) carries no number, which is why the
    # number is what the rule reads.
    Rule(re.compile(r"\bslices?\s*#"
                    r"|\breviews?\s*#\s*\d"
                    r"|\breviews?\s+(?-i:[A-Z]\d)\b"
                    r"|\breviews?\s+findings?\b"
                    r"|\b(?:in|during|from) the review\b"
                    r"|\breview[- ]rounds?\b"
                    r"|\b(?:adversarial|hostile|security|code-health)[- ]reviews?\b"
                    r"|\baudits?\s*#?\s*\d+(?:\.\d+)*\b", re.I), "review or slice identifier"),
    # A ROUND is the run of work a change belonged to, named beside the kind of work it was. The
    # ordinary senses of the word (a retry round, rounding a number) carry none of those words.
    # The numbered form is the audit trail whatever joins the word to its number, so the separator
    # is a hyphen, an underscore or a space: a rule that demanded the hyphen read one spelling.
    # "round 3 OF the retry loop" is the counted sense and is the one shape the number keeps.
    Rule(re.compile(r"\b(?:feedback|fix(?:es|ed)?|review|re-gate|UX|work)\b[^\n]{0,30}?\brounds?\s*#?\s*\d"
                    r"|\brounds?\s*#?\s*\d[^\n]{0,30}?\b(?:feedback|fix(?:es|ed)?|review|re-gate|UX|work)\b"
                    r"|\bround[-_ ]#?\s?\d+(?!\s*of\b)", re.I), "round-of-work identifier"),
    # Who settled the argument, and the sitting it was settled in, are the same provenance the
    # word owner carries. "Operator" alone is a role the console serves and stays.
    # "live session" is also an ordinary HTTP session, so only the provenance grammar is named: a
    # preposition in front of it makes the sitting the place a decision came from.
    Rule(re.compile(r"\boperator\s+decisions?\b|\bchief[- ]architect\b"
                    r"|\b(?:from|in|during|after|at)\s+(?:the\s+|a\s+)?(?:\w+\s+)?live session\b", re.I),
         "decision-owner language"),
    # To ratify is to bless a decision, which is what "approved" and "ruling" already name.
    Rule(re.compile(r"\bratif(?:y|ies|ied|ication)\b", re.I), "ruling language"),
    # A comment may point only at something a reader of this repository can open: a file in the
    # tree, or a docs/ page and its section. A clause number, a SPEC, a design brief and an ADR all
    # name a document that is not here, so the reader is left with an unresolvable reference where
    # the constraint should have been.
    # A numbered CLAUSE with no document in front of it is the same unresolvable reference with the
    # document's name taken off: "SPEC 6" reworded to "clause 6" leaves the reader with a number and
    # nowhere to look it up, which is what this rule exists to prevent rather than to relocate.
    Rule(re.compile(r"\u00a7|\bSPEC\b|(?i:\bdesign brief\b)|\bADR-\d|(?i:\bclause\s+\d)"),
         "design-document citation",
         # A licence's own clause number is the obligation, not a design document, and the legal
         # code it names is public. The window must carry the licence for the exemption to hold.
         ((re.compile(r"^\u00a7$"),
           re.compile(r"CC-?BY|CC0|ODbL|Creative Commons|licen[cs]e", re.I)),
          # An ADR that is a FILE in this tree is a pointer a reader can follow, which is what the
          # rule asks for. The window must carry the path, not merely the name.
          (re.compile(r"^ADR-\d"), re.compile(r"/ADR-\d[\w.-]*\.md\b")),
          # A licence's numbered clause is the same obligation the section mark names, written out.
          (re.compile(r"(?i)^clause\s+\d"),
           re.compile(r"CC-?BY|CC0|ODbL|Creative Commons|licen[cs]e", re.I)))),
    Rule(re.compile(r"YOUR-"), "placeholder"),
    Rule(re.compile(r"TODO\(", re.I), "unowned marker"),
    Rule(re.compile(r"\bFIXME\b", re.I), "unowned marker"),
    # A vocabulary filter alone lets the history through wherever it avoids the
    # banned words, so the two shapes history takes are named as well: what the
    # code used to say, and what a rejected alternative would have done.
    Rule(re.compile(r"\bused to \w+"
                    r"|\bwould have\b"
                    r"|\bpreviously\b"
                    r"|\bno longer\b"
                    r"|\binstead of the old\b"
                    r"|\brather than the (?:old|previous)\b"
                    r"|\bhistorically\b"
                    r"|\boriginally\b", re.I),
         "history or alternatives narrative"),
)

# A pin traces itself by naming the contract it holds, so a test file may cite
# one. Code may not: the contract is a document about a decision, and a decision
# is what a comment may not record.
CONTRACT_CITATION = Rule(
    re.compile(r"\bLANE-(?:CONTRACT|ADDENDUM)-[A-Z0-9-]+"), "contract file name")

# WORK-ITEM TAGS. A tag is one or two capitals, one or two digits and an
# optional letter, and it is lane vocabulary WHEREVER it stands in a comment. It
# is NOT a station or site id, a licence id, a projection, a digest, a
# percentile or a heading level, which is what the exemptions are for.
# Position was the last scoping: a work item named mid-sentence, after a dash or
# inside a list carries the same audit trail as one at the head of a comment, so
# scoping to four positions left the rule reading only where it had already
# looked.
# A work item that cites a CLAUSE of the design it belongs to writes the clause after a dot
# ("D9.1", "T1.2"), and the citation is the same audit trail as the work item alone. The letters
# are what make it one: an enumeration written 1.1 or 2.3 is a comment numbering its own list.
_TAG = r"[A-Z]{1,2}\d{1,2}(?:\.\d{1,2})?[a-z]?"
_TAGS = r"%s(?:\s*[/,]\s*%s)*" % (_TAG, _TAG)

TAG_PATTERN = re.compile(r"(?<![\w#])(?P<any>%s)(?![\w]|\.\d)" % _TAGS)
# A DATAID and a station id are DATA, and this is a repository about stations: two or more letters
# and then digits (with an optional trailing letter or a second letter-digit pair) is the shape the
# corpus publishes, e.g. ST01, MBI21, CP3B21, RD18. A work-item tag carries ONE leading letter and
# a published id carries at least two digits, so the two shapes do not overlap; the two-digit floor
# is what keeps a licence alias like CC0 with the entry that names its meaning instead.
CORPUS_ID = re.compile(r"\A(?:[A-Z]{2,}\d{2,}[a-z]?|[A-Z]{2,}\d+[A-Z]+\d{2,}[a-z]?)\Z")

# The false positives, one entry per MEANING: what the token names, the token
# itself, and the words that must stand beside it for that meaning to be the one
# in play. The context test is what keeps an entry from buying a false negative:
# without it, a genuine work item spelled S3 or H1 would be permanently
# invisible. Every entry is held by a test that the same token in work-item
# position, without those words, is still caught.
TAG_NOT_A_TAG = (
    # Every alternative is word-bounded. Without the boundary an alternative opens on any word
    # that merely CONTAINS it, and "store" inside "restore" and "stored" is enough to excuse a
    # work item called S3 for the life of the pin.
    ("the object store", re.compile(r"^S3$"),
     re.compile(r"\bbuckets?\b|\bobjects?\b|\bstores?\b|\bendpoints?\b|\bMinIO\b|\bR2\b", re.I)),
    ("a heading level", re.compile(r"^H[1-6]$"),
     re.compile(r"heading|<h\d|\btags?\b", re.I)),
    ("a CIE standard illuminant", re.compile(r"^D(?:50|55|65|75)$"),
     re.compile(r"illuminant|CIE|CIELAB|sRGB|white ?point|colou?r|\bLab\b", re.I)),
    # The bare noun is not enough: a clause label written L1 is naturally ABOUT levels, so the
    # word that would excuse it stands beside it by construction. The level must be named.
    # The trailing run of a station id, as the cluster label renders it once the padding is dropped.
    ("an unpadded station id", re.compile(r"^L\d{1,2}$"),
     re.compile(r"unpadded|station ids?|\bCP\d|cluster", re.I)),
    ("a data level", re.compile(r"^L[0-3]$"),
     re.compile(r"\bdata levels?\b|\blevels?\s+[0-3]\b|\bL[0-3]\s+products?\b", re.I)),
    ("a release quarter", re.compile(r"^Q[1-4]$"),
     re.compile(r"Release |20\d\d-Q|quarter", re.I)),
    # The impedance tensor's own quadrants, which the phase maths names constantly.
    ("a complex-plane quadrant", re.compile(r"^Q[1-4]$"),
     re.compile(r"quadrant|Zxy|Zyx|Zxx|Zyy|phase", re.I)),
    # The rotation maths writes its matrices Z0 and T0; neither is a work item.
    ("a rotation-matrix symbol", re.compile(r"^[ZT]0$"),
     re.compile(r"rotation|rotate|matri|theta|\bR\(|tipper|impedance", re.I)),
    # The other licence aliases count as context: a licence id standing in a list of licence ids is
    # the licence sense, and the word "licence" itself is often a clause away.
    ("a public-domain dedication", re.compile(r"^CC0$"),
     re.compile(r"licen[cs]|dedication|public domain|Creative Commons|CC-BY|ODbL|ODC-BY|SPDX", re.I)),
    # Only the single-letter form needs an entry: the two-letter DATAIDs are already data under the
    # corpus-id shape, and an entry that repeated them would excuse them twice.
    ("a DATAID example", re.compile(r"^A\d{1,2}$"),
     re.compile(r"DATAID|data ?id|station id|example|\.edi\b|\bEDI\b", re.I)),
    ("a message digest", re.compile(r"^MD5$"),
     re.compile(r"digest|checksum|hash|manifest|sha\d", re.I)),
    ("a percentile", re.compile(r"^P(?:50|95|99)$"),
     re.compile(r"percentile|median|\btail\b|budget|threshold|profile", re.I)),
)
# ONE MEANING ON THAT TABLE READS THE WHOLE RUN RATHER THAN THE WINDOW. A licence identifier is
# named by the word licence, license or dedication standing anywhere in the prose that carries it:
# a run about licensing names the licence and then uses the alias, and the alias commonly ends the
# sentence while the word that identifies it opened one. A sixty-character window read a message
# that said "licence" twice and still could not see either, and the licence name was traded for a
# paraphrase to get the run green. Every other entry keeps the window, because a station id or a
# quadrant IS its neighbourhood; a licence id is not.
TAG_CONTEXT_IS_THE_WHOLE_RUN = ("a public-domain dedication",)
# A token that IS an id is named by the noun that says so, immediately before it
# with one space between. The test is on the TOKEN. A window wide enough to hold
# a sentence excuses any token standing NEAR the word, and on a corpus about
# stations and surveys those words stand beside everything.
TAG_ID_NOUN = re.compile(
    r"(?:station|site|survey|run|channel|filter|fixture|id)s?:?[ ]['\"`]?\Z", re.I)
_TAG_GROUPS = ("any",)


# THREE STRUCTURAL EXEMPTIONS, each for a place a tag SHAPE occurs that no reader would read as a
# work item. They are structural rather than table entries because what excuses them is where the
# token sits, not the words around it.
# A file name: a published station's own bytes are named after it.
FILE_NAME = re.compile(r"\A[A-Za-z0-9_.%\[\]-]*"
                       r"\.(?:edi|h5|xml|json|zip|csv|txt|md|png|svg|ya?ml|nc)\b")
# A character class inside a regex: "^[a-zA-Z0-9]*$" carries the shape and means nothing by it.
IDENT_RUN = re.compile(r"[A-Za-z0-9_.-]")
RANGE_IN_CLASS = re.compile(r"[A-Za-z0-9]-[A-Za-z0-9]|\\[dwsDWS]")
# A path INTO this repository is a pointer a reader can follow, which is what the rule asks for, and
# the file it names commonly carries a tag in its own name. Held by the pin that resolves them.
REPO_PATH = re.compile(
    r"\A[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+"
    r"\.(?:py|js|md|html|css|ya?ml|json|toml|sh|txt|service|timer|cfg)\Z")


def _in_character_class(text, start, stop):
    head = text.rfind("\n", 0, start) + 1
    tail = text.find("\n", stop)
    tail = len(text) if tail < 0 else tail
    before, after = text[head:start], text[stop:tail]
    open_at = before.rfind("[")
    close_at = after.find("]")
    if open_at < 0 or close_at < 0:
        return False
    inner_before, inner_after = before[open_at:], after[:close_at]
    if "]" in inner_before:
        return False
    inner = inner_before + text[start:stop] + inner_after
    return bool(RANGE_IN_CLASS.search(inner)) and "," not in inner


def _identifier_run(text, start, stop):
    left, right = start, stop
    while left > 0 and IDENT_RUN.match(text[left - 1]):
        left -= 1
    while right < len(text) and IDENT_RUN.match(text[right]):
        right += 1
    return text[left:right]


PATH_RUN = re.compile(r"[A-Za-z0-9_./-]")


def _inside_a_repo_path(text, start, stop):
    """A token inside a path into this tree names a FILE, and a file in the repository is exactly
    what a comment is allowed to point at."""
    left, right = start, stop
    while left > 0 and PATH_RUN.match(text[left - 1]):
        left -= 1
    while right < len(text) and PATH_RUN.match(text[right]):
        right += 1
    run = text[left:right].strip("./,;:")
    return run != text[start:stop] and bool(REPO_PATH.match(run))


# An apostrophe inside a word does not open a quoted run. Read as one it reaches to the next
# apostrophe a sentence away and excuses every tag standing between the two.
QUOTE_RUN = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|(?<![\w'])'[^'\n]*'(?!\w)")


def _inside_a_quoted_literal(text, start, stop):
    """A token inside a quoted run that carries MORE than the token is part of a literal the code
    emits or a file the corpus publishes, and the comment is quoting it, not naming a work item. A
    bare quoted tag is still a tag: the run must carry something besides the token."""
    head = text.rfind("\n", 0, start) + 1
    tail = text.find("\n", stop)
    tail = len(text) if tail < 0 else tail
    line = text[head:tail]
    a, b = start - head, stop - head
    for match in QUOTE_RUN.finditer(line):
        if match.start() < a and b < match.end():
            inner = match.group(0)[1:-1].strip()
            return inner != text[start:stop]
    return False


def _inside_a_corpus_id(text, start, stop):
    """A token standing inside a longer identifier one of whose segments IS a published id is part
    of that id: RD18-084-S1-b is one station's handle, not a work item called S1."""
    run = _identifier_run(text, start, stop)
    if run == text[start:stop]:
        return False
    return any(CORPUS_ID.match(seg) for seg in re.split(r"[-_.]", run))


def work_item_tags(text):
    """Every work-item tag in a bare comment, as (match, tag)."""
    found = []
    for match in TAG_PATTERN.finditer(text):
        group = next(name for name in _TAG_GROUPS if match.group(name))
        tag = match.group(group)
        start, stop = match.span(group)
        if FILE_NAME.match(text[stop:stop + 8]):
            continue
        if _in_character_class(text, start, stop):
            continue
        if (_inside_a_corpus_id(text, start, stop) or _inside_a_repo_path(text, start, stop)
                or _inside_a_quoted_literal(text, start, stop)):
            continue
        window = text[max(0, start - WINDOW):stop + WINDOW]
        parts = [part.strip() for part in re.split(r"[/,]", tag)]
        # A token joined by a hyphen to a LETTER before it is a COMPOUND label ("D-L1", "C35b-D5"),
        # which is the shape a clause or a work item takes and never the shape of the id an
        # exemption exists for; no entry on the table excuses one. A digit before the hyphen is a
        # different thing entirely (2026-Q3 is a release quarter), so the test is on the letter.
        compound = start >= 2 and text[start - 1] == "-" and text[start - 2].isalpha()
        if all(CORPUS_ID.match(part) for part in parts):
            continue
        if not compound and all(
                any(token.match(part)
                    and near.search(text if meaning in TAG_CONTEXT_IS_THE_WHOLE_RUN else window)
                    for meaning, token, near in TAG_NOT_A_TAG)
                for part in parts):
            continue
        if TAG_ID_NOUN.search(text[:start]):
            continue
        found.append((match, tag))
    return found


# COMMENTED-OUT CODE. A comment line that parses as an assignment, a call
# statement, a declaration, a return or a control keyword is code that was
# switched off rather than deleted, and git is where it belongs. One line must
# look like code unambiguously; a run of three or more lines that each END the
# way code ends is caught even when no single line would be, which is how a
# commented-out template literal of markup is found.
# A line that is code whatever else is on it: a declaration, a control keyword, a
# return statement, a script tag, a mapped call.
CODE_LINE = tuple(re.compile(p) for p in (
    r"^(?:const|let|var)\s+[\w$\[\]{},\s]+=\s*\S",
    r"^(?:export\s+)?(?:async\s+)?function\s*[\w$]*\s*\([\w$,\s]*\)\s*\{?\s*$",
    r"^class\s+[\w$]+\s*(?:extends\s+[\w$.]+\s*)?\{",
    r"^(?:\}\s*)?(?:if|for|while|switch|catch)\s*\(",
    r"^(?:\}\s*)?else\s*(?:\{|if\s*\()",
    r"^return\b[^.!?]*;\s*$",
    r"^(?:def\s+\w+\s*\(|import\s+[\w.]+\s*$|from\s+[\w.]+\s+import\s)",
    r"^<script\b[^>]*>\s*(?:</script>)?\s*$",
    r"^(?:L\.map|fetch)\(\s*['\"`\w$]",
))
# A line that is code only because it is TERSE. An assignment or a call statement is also
# the shape of a sentence naming a field ("write_errors = puts dropped after the rename
# retries were exhausted;"), so these fire only on a line short enough to be code rather
# than prose about code.
CODE_LINE_TERSE = tuple(re.compile(p) for p in (
    r"^(?:await\s+|new\s+)?[\w$][\w$.\[\]'\"]*\s*(?:\+|\|\||\?\?)?=[^=~>]\s*\S.*[;{]\s*$",
    r"^(?:await\s+|new\s+)?[\w$][\w$.]*\(.*\)\s*[;,)]\s*$",
    r"^\.[\w$]+\(.*\)",
    # One ELEMENT of an array or object literal, which is the shape a switched-off row takes and
    # the only shape a LIVE literal can carry between two of its own entries.
    r"^\[.*\]\s*,\s*$",
    r"^\{.*\}\s*,\s*$",
    # A term switched off INSIDE a live expression ends on the binary operator that joined it to
    # the next term, so a shape anchored to a statement end cannot reach it. Prose ending on the same
    # operator is excluded by the terse-line limit above and by requiring the call's own brackets.
    r"^(?:await\s+|new\s+)?[\w$][\w$.]*\(.*\)\s*(?:\+|-|\*|/|&&|\|\||\?\?)\s*$",
    r"^(?:\[.*\]|\{.*\})\s*(?:\+|&&|\|\||\?\?)\s*$",
    # A ternary arm switched off inside a live expression ends on the : that joined it to the arm
    # below. Prose is excluded by the terse-line limit and by requiring the ? and the : both.
    r"^[\w$][\w$.\[\]()]*\s*\?[^?:]*:\s*$",
    # A member chain left dangling on its own dot. It must carry a call with ARGUMENTS or a
    # subscript, because the other shapes are prose: a file name closing a sentence
    # ("drawer.js."), an abbreviation, and a sentence that ends by naming a function
    # ("see _preview_env().").
    r"^(?=.{8,}$)[\w$][\w$.]*(?:\((?:[^()]|\([^()]*\))+\)|\[[^\]]*\])[\w$.\[\]]*\.\s*$",
))
TERSE_WORDS = 8
# The looser tell, only ever counted in a run: a terse line that ends the way a statement
# or a block ends AND carries a bracket or an operator, or one that opens a markup tag.
# Prose wraps mid-sentence, and a prose line that ends on a semicolon is still prose.
CODE_RUN_LINE = re.compile(r"^</?[a-zA-Z][\w-]*[\s>]|^\}\)?[;,]?\s*$"
                           r"|(?=[^\n]*[=(){}\[\]])[^\n]*[;{}]\s*$")
CODE_RUN = 3

# A triple quote opens a comment as surely as a # does, so the first line of a docstring is the
# head of a comment and a rule that reads head position must see it there.
LEADERS = ("<!--", "-->", "/*", "*/", "//", '"""', "'''", "*", "#")
# A one-line block comment carries its CLOSER on the same line, and a shape anchored to the end of
# a line can never match while the closer is still sitting there.
TRAILERS = ("-->", "*/", '"""', "'''")


def bare_line(line):
    stripped = line.strip()
    changed = True
    while changed:
        changed = False
        for lead in LEADERS:
            if stripped.startswith(lead):
                stripped = stripped[len(lead):].strip()
                changed = True
        for trail in TRAILERS:
            if stripped.endswith(trail):
                stripped = stripped[:-len(trail)].strip()
                changed = True
    return stripped


def bare(comment):
    """The comment with its leaders stripped, line for line, so a rule reads the
    prose a reader reads and the head of the comment heads line one."""
    return "\n".join(bare_line(line) for line in comment.splitlines())


def looks_like_code(comment):
    run = 0
    for line in bare(comment).splitlines():
        if not line:
            run = 0
            continue
        if any(p.match(line) for p in CODE_LINE):
            return True
        terse = len(line.split()) <= TERSE_WORDS
        if terse and any(p.match(line) for p in CODE_LINE_TERSE):
            return True
        run = run + 1 if (terse and CODE_RUN_LINE.search(line)) else 0
        if run >= CODE_RUN:
            return True
    return False


def flattened(text):
    """One line of prose: every newline and every run of spaces becomes one space. Every rule that
    names two words is otherwise defeated by the line wrap between them, and a comment is not
    cleaner for being wrapped at column 100."""
    return " ".join(text.split())


# A pointer names a file a reader of THIS repository can open. A path whose first segment is a
# directory the repository does not carry names a document that is not here, and the reader is left
# with exactly the unresolvable reference the citation rule exists to remove. The trees are NAMED
# rather than resolved: a working directory beside the checkout exists on the author's machine and
# nowhere else, so existence is not the test, and naming them also lets this rule read the same
# inside the engine image, where only two of the trees are shipped. A first segment carrying a dot
# is a file name, so "LICENSE.md/README.md" is an either-or and not a path.
REPO_TREES = ("portal", "engine", "gateway", "deploy", "contract", "docs", "maintainer", "schema",
              ".github", "tests", "tools", "scripts", "src", "extract", "data", "environments",
              "runner", "docker", "systemd", "frontdoor", "fixtures", "vendor", "ausmt_science",
              "developer", "reference", "architecture", "data-model", "interoperability",
              "introduction", "operations", "rationale", "science")
DOCUMENT_IN_PROSE = re.compile(
    r"(?<![\w/.~-])([A-Za-z_][\w-]*(?:/[\w.-]+)+\.md)(?![\w-])")


# The same rule with no directory in front of it. A document cited by bare name is a pointer a
# reader follows by opening the file, and a directory is not what makes it followable: existence
# is. Two names are not citations of a document. A LANE-CONTRACT or LANE-ADDENDUM document is the
# contract a pin traces itself by, which lives outside the checkout by ruling and is governed by
# the contract-citation rule instead. A name the same file also writes in its CODE is a file the
# code produces or reads, not a document it points a reader at.
BARE_DOCUMENT = re.compile(r"(?<![\w/.~-])([A-Za-z][\w-]*\.md)(?![\w-])")
CONTRACT_DOCUMENT = re.compile(r"\ALANE-(?:CONTRACT|ADDENDUM)-")


def documents_named(text):
    """Every bare <NAME>.md a comment cites with no directory in front of it."""
    return [m.group(1) for m in BARE_DOCUMENT.finditer(text)
            if not CONTRACT_DOCUMENT.match(m.group(1))]


def paths_outside_this_repository(text):
    """Every DOCUMENT a comment cites whose first segment is not a tree of this repository. A
    document is the citation the rule is about; a data path outside the checkout (/srv, out/, a
    sibling repository the deployment mounts) names a place, not a reference to follow."""
    return [m.group(1) for m in DOCUMENT_IN_PROSE.finditer(text)
            if m.group(1).split("/")[0] not in REPO_TREES]


def labels_for(comment, cite_contract=False):
    """Every way one comment breaks the rule, as sorted labels."""
    text = flattened(bare(comment))
    found = {rule.label for rule in RULES if rule.hits(text)}
    if not cite_contract and CONTRACT_CITATION.hits(text):
        found.add(CONTRACT_CITATION.label)
    if work_item_tags(text):
        found.add("work-item identifier")
    if paths_outside_this_repository(text):
        found.add("a path outside this repository")
    if looks_like_code(comment):
        found.add("commented-out code")
    return sorted(found)


# A cut that takes the leading token off a line leaves the marker hard against the punctuation that
# belonged to the words above it ("#. proven failing"), and that line is still the next line of the
# run a reader reads. The lead is read past such a mark so the run the rules read is that run.
PUNCTUATION_LEAD = re.compile(r"\A([#/])[.,;:!?]")


def comment_runs(path, text):
    """(line number, text) for each run of comments a reader reads as one. A block of // or #
    lines is one comment to a reader, and a shape read line by line sees a bracket opened on one
    line and closed on the next as two scars. The gutter says which lines are one comment: two
    consecutive line comments are the same comment when their markers stand in the same COLUMN,
    so a comment trailing a statement is not read as the next line of the block above it, and a
    trailing comment's own continuation, aligned under it, is."""
    lines = text.splitlines()

    def where(lineno, body):
        """(column of the marker, whether code stands in front of it)."""
        if not 0 < lineno <= len(lines):
            return -1, False
        line = lines[lineno - 1]
        at = line.find(body.split("\n", 1)[0])
        return at, at > 0 and bool(line[:at].strip())

    out = []
    for lineno, body in comments(path, text):
        lead, span = PUNCTUATION_LEAD.sub(r"\1 ", body[:2]), body.count("\n")
        at, _ = where(lineno, body)
        if (out and lead in ("//", "# ", "#\n", "#") and out[-1][2] == lead
                and lineno == out[-1][3] + 1 and at >= 0 and at == out[-1][4]):
            out[-1][1] += "\n" + body
            out[-1][3] = lineno + span
            continue
        out.append([lineno, body, lead, lineno + span, at])
    return [entry[0:2] for entry in out]


def offences(files, cite_contract=False, root=None):
    """Every comment that breaks the rule across a set of files, as report lines. The unit is the
    RUN a reader reads, not the line: a phrase wrapped across two // lines is one phrase to a
    reader, and a scan that reads each line alone is defeated by the line break between them."""
    found = []
    for path in files:
        text = source_text(path)
        for lineno, comment in comment_runs(path, text):
            labels = labels_for(comment, cite_contract=cite_contract)
            if labels:
                where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(labels),
                                " ".join(comment.split())[:110]))
    return found
# COMMENT SHAPE. A comment is prose, and a token cut out of the middle of a
# sentence leaves a scar no vocabulary can see: a bracket with no partner, a
# connector left hanging inside one, a space between a word and the punctuation
# that belongs to it, a line carrying nothing but a bracket, a pointer whose file
# token swallowed the fragment of the sentence that was cut. The shapes are read
# on the comment a READER reads, so a run of single-line comments is joined
# first, and a bracket or a punctuation mark the prose is NAMING sits inside a
# quoted run and is blanked before the shape is read.
QUOTED_RUN = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|(?<![\w'])'[^'\n]{1,60}'(?!\w)")
# "2)" opening a line is a list marker; "(-180, 180]" is an interval; a row of a
# definition table carries its colon in a column of its own.
ENUMERATOR = re.compile(r"^[ \t]*(?:\d{1,2}|[a-z])\)")
DEFINITION_ROW = re.compile(r"^\s*\S+[ ]+:[ ]", re.M)
# The gap is the same gap wherever the words ran out, so what stands in front of it is a word
# character OR the bracket that closed the group: "relationships[] ;" is the semicolon of a clause
# whose citation was taken away, and a rule reading only a word character cannot see it.
SPACE_BEFORE_PUNCT = re.compile(r"[\w)\]}][ ]+[.,;!?](?:\s|$)")
SPACE_BEFORE_COLON = re.compile(r"\w[ ]+:(?:\s|$)")
# The same scar read from the other side: a run that OPENS on the punctuation of a sentence whose
# words were taken away. An ellipsis and a decimal point carry a character after the mark.
OPENS_ON_PUNCTUATION = re.compile(r"\A[.,;:!?](?:\s|\Z)")
# A gap between the last word of a bracketed group and the bracket that closes
# it is where the rest of the group stood.
SPACE_BEFORE_BRACKET = re.compile(r"\w[ ]+[)\]](?!\w)")
EMPTY_GROUP = re.compile(r"\([ \t]*[-+:;,|][ \t]*\)")
OPEN_CONNECTOR = re.compile(r"\([ \t]*[-:;,/][ \t]")
# The same scar at the other end of the group. A cut token leaves the character
# that joined it standing: in front of the bracket that closed the group, in
# front of the end of the run, or hard against the connector that preceded it.
# A connector list that reads only the opening side sees half the damage.
CLOSE_CONNECTOR = re.compile(r"[ \t][-:;,/|][ \t]*(?=[)\]]|\Z)")
BRACKET_GROUP = re.compile(r"\([^()]*\)")
CONNECTOR_PAIR = re.compile(r"\w[,;][-/](?=\w)")
# A cut that takes the tail of a sentence off the line above leaves the mark that closed it standing
# at the head of the next line: ")." where the citation stood, "); " and "; " where the clause did,
# "]," where the list item did. A line that is nothing BUT that mark is the narrowest case of the
# same scar, so the line's OPENING is what is read rather than a line of exactly one character. The
# colon is not on the list: a definition row writes one at the head of its continuation on purpose.
LINE_OPENS_ON_STRAY = re.compile(r"\A(?:[)\]}][.,;]?|[.,;])(?:\s|\Z)")
# THE WORD A SUBSTITUTION LEFT STANDING. Where a cut token is replaced by a phrase that opens on the
# word already in front of it, the word is written twice ("NARROWED by the The API docs section",
# "all of them from the the brief"). Only the closed class of function words is read, because they
# are what a substitution strands and no sentence in this tree writes one of them twice in a row;
# the second is read case-insensitively, since the replacement keeps the capital its own line began
# with. The pair straddles the gutter as often as not, so it is read on the JOINED run. A word
# joined by a hyphen to what precedes it is part of a compound and not the first of a pair, which
# is what keeps a header name like "Reply-To to the From address" whole.
DOUBLED_WORD = re.compile(r"(?<![\w-])(the|a|of|to|is|in|and)\s+\1(?![\w-])", re.I)
# THE NOUN A CUT TOOK AWAY. The mirror of the doubled word: where the cut takes the noun and leaves
# the word that introduced it, the sentence ends on a determiner and states nothing ("the exact
# words are the.", "measured dE76 under a."). Only words that CANNOT end an English sentence are
# read: a stranded preposition ends one every day in this tree ("the bucket it falls into.", "the
# meaning of."), so the list is determiners and coordinators alone. Lower case only, because a
# capital letter followed by a full stop is a list marker.
ORPHANED_DETERMINER = re.compile(r"(?<![\w-])(?:the|an|a|and|or|nor|than|per|whose)[ \t]*[.;](?:\s|\Z)")
# THE SUBJECT A CUT TOOK AWAY, which is the same family read at the head of the sentence rather than
# its tail. Where the cut token WAS the subject, the verb is left with nothing doing it: "C40 adds a
# host-side reconcile timer" becomes "adds a host-side reconcile timer". A sentence opening in lower
# case is ordinary in this tree (a thousand of them open on an identifier or a shell variable), so
# what is read is a LIST of finite verbs, none of which can open an English sentence.
#
# THE LIST IS A SAMPLER AND NOT A GRAMMAR, and the measurement says how far short of one it falls.
# The rule a grammar would state is "the/this/that <noun> <verb>", and the only mark of a verb this
# scanner has is the -s: read open, as any lower-case word ending in s, that shape fires 51 times
# over a pristine origin/main export on prose that is whole ("is the incident class", "is the EDI
# files themselves", "is the corpus as a vector layer"), because English writes a plural noun in
# exactly the slot a cut leaves a verb in and nothing short of a lexicon tells the two apart. So
# the list holds the verbs this tree's prose is measured to use this way, one list for both ends of
# the sentence, and a round that adds a verb to it is finding SITES, not closing the class.
#
# Two shapes do not end a sentence and so cannot open the next one: an ellipsis, and the dot of an
# abbreviation ("... routes you straight to the archive", "i.e. proves that pin can fail"). Both
# stand in origin/main prose.
SUBJECT_VERBS = (
    r"accepts|adds|allows|answers|asserts|blocks|breaks|brings|broadened|bumped|carries|catches|"
    r"closes|costs|counts|defends|defines|describes|documents|drives|drops|enforces|ensures|"
    r"exists|extends|feeds|fixes|folds|forbids|gates|gives|guarantees|hides|holds|introduces|"
    r"inverts|invokes|keeps|leaves|lifts|loses|lowers|made|makes|marks|means|moved|moves|names|"
    r"narrows|needs|owns|pins|prevents|protects|proves|puts|raises|reads|refuses|removes|renames|"
    r"repairs|replaces|requires|restores|retargeted|retires|routes|rules|runs|says|sends|serves|"
    r"sets|shows|splits|stands|states|supersedes|takes|trades|treats|turns|uses|widens|wins|"
    r"writes"
)
SUBJECTLESS_SENTENCE = re.compile(
    r"(?<![A-Z0-9])(?<!\.)(?<!\.[a-z])[.!?]\s+(" + SUBJECT_VERBS + r")\b")
# The same cut at the other end of the sentence: where what a bracketed aside was ABOUT is taken
# away, the copula is left with nothing after it ("the sole real-git workflow (curator-e2e) was.").
# A pronoun subject makes that ordinary English ("git carries what was."), so the shape is anchored
# to the bracket that closes hard in front of the verb.
ORPHANED_COPULA = re.compile(r"[)\]][ \t]+(?:was|were|is|are|be|been|being)[ \t]*[.;](?:\s|\Z)")
# TWO SENTENCE MARKS WITH NOTHING BETWEEN THEM, whatever character stands in front of them. Where
# the cut takes the token that stood between a mark and the mark of the clause around it, the two
# are left together and no WORD is missing to a reader: "STAGE-3b FIX ROUND (C)., each
# red-then-green", "and dimensionality.json.: station.json stopped". Read as a CLASS, any of
# . , ; : ! ? against any other, because three rounds of naming the pairs one at a time each
# missed the next one by a single character.
#
# Four shapes this tree writes on purpose are not that, and each is named by the origin/main prose
# that forces it. A decimal and a run of dots: the ellipsis, and the range a comment writes between
# two bounds. A pair belonging to the TOKENS around it rather than to the sentence: standing
# between word characters (the accept list ".edi,.h5,.mth5"), or a mark that CLOSES a word and is
# followed by a list separator ("javascript:, data:," naming two URI schemes, "{name, ror?,
# roles[]}" naming an optional field, "&#x27;, &#x27;" naming an entity), or standing among the
# glyphs a legend lists ("the state for a colour-blind
# READER (check/half/cross/?, not colour alone)"). An operator a comment quotes, which is a mark
# doubled or the question mark against the colon ("conftest.py::resolve_validator_dir", "${VAR:?}",
# "block?:{...}"), or any run of three or more marks that is not dots ("remote_ref:!!undefined").
# And an ABBREVIATION'S dot, which ends a word and not a sentence: "e.g.: if (m.model_doi)",
# "Kay, B.; Heinson, G.", a numbered list's "1., 2.". That last exemption is the widest and it is
# a declared hole: a cut that leaves "e.g.:" standing writes the same two characters origin/main
# writes deliberately, so no shape rule can tell them apart and such a site is read as sense.
MARK_RUN = re.compile(r"[.,;:!?]{2,}")
QUOTED_OPERATOR = ("::", ":?", "?:", "??", "!!")
ABBREVIATION = re.compile(r"(?:\A|[^\w])[A-Za-z0-9]\.\Z")


def marks_together(text):
    """Every pair of sentence marks a cut left standing together, as the matched pairs."""
    found = []
    for run in MARK_RUN.finditer(text):
        body = run.group(0)
        if set(body) == {"."} or len(body) >= 3:
            continue
        for at in range(len(body) - 1):
            pair, start = body[at:at + 2], run.start() + at
            before, after = text[:start], text[start + 2:]
            if before[-1:] == "." or after[:1] in (".", "") or after[:1].isdigit():
                continue
            if pair in QUOTED_OPERATOR:
                continue
            if before[-1:] == "/":
                continue
            if before[-1:].isalnum() and (after[:1].isalnum()
                                          or (pair[0] in ":;?" and pair[1] in ",;")):
                continue
            if pair[0] == "." and ABBREVIATION.search(before + "."):
                continue
            found.append(pair)
    return found
# THE WORD LEFT HARD AGAINST THE BRACKET THAT CLOSED ITS GROUP. Where the cut takes the citation a
# bracketed aside was about, the word that introduced it is left standing against the bracket
# ("as amended by)", "restated for)", "those are)", "(was ro in)"). A stranded preposition closes
# an ordinary relative clause in this tree a hundred times over ("the name it arrived with)",
# "the digest this entry was keyed under)"), so the shapes read are the three that cannot be one:
# a participle carrying its preposition with no auxiliary in front of it, a demonstrative plural
# standing on its copula, and a group that opens on a copula and closes with no complement.
PARTICIPLE_PREPOSITION = re.compile(
    r"(?<!\bwas )(?<!\bwere )(?<!\bis )(?<!\bare )(?<!\bbeen )(?<!\bbe )(?<![\w-])"
    r"(?:amended|extended|restated|retired|superseded|narrowed|widened|introduced|replaced|"
    r"lifted|bumped|renamed|ratified|stated|documented|recorded|granted|reworded|revised|"
    r"relaxed|tightened|reinstated|rescinded|clarified|corrected|deprecated|reinforced)"
    r"[ \t]+(?:in|on|by|for|from|with|as|at|under|over|since|to)\)")
DEMONSTRATIVE_COPULA = re.compile(r"(?<![\w-])(?:those|these)[ \t]+(?:are|is|was|were)\)")
COPULA_GROUP = re.compile(r"\((?:was|were|is|are)[ \t][\w-]+[ \t]"
                          r"(?:in|on|by|for|from|with|as|at|under|over|since|to)\)")
# THE VALUE AN OPERATOR WAS POINTING AT. A docstring that documents a return value writes the
# arrow and then the value ("an absent log => []"), so a cut that takes the value leaves the
# arrow pointing at the full stop and the docstring states a behaviour with nothing to state it
# as. A bare "=" cannot join the class: this tree names a keyword argument or an attribute that
# way ("passing no dir=, so a rollover lands", "no inline block without src=. Mirrors"), which is
# the same shape and correct English, so only the arrows and an "=" the writer spaced off are read.
OPERATOR_ORPHAN = re.compile(r"(?:=>|->|<-)[ \t]*[.,;](?:\s|\Z)|[\w)\]]=[ \t]+[.,;](?:\s|\Z)")
# THE SUBJECT A CUT TOOK OUT OF THE MIDDLE OF A SENTENCE. SUBJECTLESS_SENTENCE is anchored to a
# sentence boundary, so it reads only the cut that took the opening word; where the subject stood
# mid-sentence the copula is left introducing the object of the verb that follows it ("This is the
# guarantee trades the leak-clean-by-construction shape for"). It reads the same sampler, with the
# same hole: "is what <verb>" is ordinary English in this tree at nine origin/main sites ("this is
# what catches a prefix regression", "the canonical block's own map is what answers"), so a cut
# that leaves "is what rules insufficient" behind writes a shape origin/main writes on purpose and
# is read as sense rather than shape.
MIDSENTENCE_SUBJECT = re.compile(
    r"(?<![\w-])is[ \t]+the[ \t]+[\w-]+[ \t]+(?:" + SUBJECT_VERBS + r")(?![\w-])")
# A BRACKET THAT POINTS AT NOTHING. Where the cut takes the record a bracketed aside cited, the
# label that introduced it is left alone between the brackets ("(design)", "(note)"): it names no
# record and states no constraint, so the aside is restated as the constraint it stood for or it
# goes with its bracket.
BARE_LABEL = re.compile(r"\((?:design|note|see|ref|cf)\)")


# THE EXPRESSION A SWEEP MAY NOT REWRITE. A comment that carries mathematics carries signs, bounds
# and exponents, and not one of them is prose: R(-θ) is not R(θ), and a quadrant read from -180 to
# -90 is not one read from 180 to -90. A vocabulary rule that lifts a token out of such a line, or
# a shape rule that restates it, can strip a sign and leave a sentence that still reads, so the
# WORDS are the only thing a sweep may touch. What is held is the multiset of SIGNED TOKENS the
# unit carries: a sign standing where an operand begins (never a hyphen inside a word, and never
# the spaced minus of arithmetic), the power operator, the join of a range between its bounds, and
# a degree mark with its number. Two trees state the same expression when their multisets agree.
GREEK = "\u0370-\u03ff\u1f00-\u1fff"
SIGNED_TOKEN = re.compile(
    r"(?<!\w)[-+][0-9(%s]" % GREEK
    + r"|(?<!\w)[-+][A-Za-z](?![A-Za-z])"
    + r"|\^"
    + r"|(?<=[0-9%s])\.\.(?=[-+]?[0-9%s])" % (GREEK, GREEK)
    + r"|[-+]?\d+(?:\.\d+)?\u00b0")


def signed_tokens(text):
    """The signed tokens one prose unit carries, sorted. The sweep's two-tree guard holds this list
    equal at both trees for every unit it touched: a rewrite that changes it has changed an
    expression, whatever it did to the words around it."""
    return sorted(match.group(0) for match in SIGNED_TOKEN.finditer(text))


# THE RANGE A CUT SIGN LEFT STANDING, which is the half of that guard one tree can hold on its own.
# A quadrant written -180..-90 loses its leading minus to a cut and becomes 180..-90, a range whose
# lower bound stands above its upper: it states no interval at all, and the sentence around it is
# untouched, so no vocabulary or shape rule can see it. Both bounds are read as NUMBERS, so a range
# of identifiers, of commit shas or of column positions is never one.
RANGE_BOUNDS = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)\.\.(-?\d+(?:\.\d+)?)(?![\w.])")


def inverted_ranges(text):
    """Every range in one prose unit whose lower bound stands above its upper, as (low, high)."""
    return [(m.group(1), m.group(2)) for m in RANGE_BOUNDS.finditer(text)
            if float(m.group(1)) > float(m.group(2))]
# A pointer names the docs page, the file it stands for and, where it points at
# one part of that file, the section. Anything else in the file token is the
# fragment of a cut sentence, which the reader is handed as a file name.
# A hyphen that ends a token is the join of a compound whose second half was cut: "PRE-C1c" leaves
# "PRE-", "CONTRIBUTOR-CREDIT-SPEC" leaves "CONTRIBUTOR-CREDIT-:". Read on the LINE, because a
# hyphen at the end of a line is a compound wrapped by the gutter and not a cut. Suspended
# hyphenation ("pre- and post-processing") is the one shape English writes on purpose, and it is
# named by the word that follows it. A dot that opens a file name ("no-.git") is the second half
# of the compound, so only a dot that ends the sentence counts.
DANGLING_HYPHEN = re.compile(r"[A-Za-z0-9]-(?=[ \t](?!(?:and|or|to)\b)|[:;,)\]]|\.(?![A-Za-z0-9]))")
# A pointer that replaced the head of a sentence and left the rest of it standing: the run then
# reads "See docs: ... . like a nameless row (...)", a subject-less fragment in shipped bytes.
POINTER_ORPHAN = re.compile(r"See docs:[^\n]*?\.\s+(?![A-Z(\[`\"'])(\S+)")
POINTER_ANY = re.compile(r"See docs:[^\n]*")
POINTER_GRAMMAR = re.compile(
    r"^See docs: portal internals, ([A-Za-z0-9_-]+\.[A-Za-z0-9]+)"
    r"(?:, ([A-Za-z0-9 ,'-]+))?\.$")


# A comment may open a sentence on a code identifier, and an identifier keeps its own case:
# `ausmt_id`, `tf.json`, `buildState()`, `_tourRestore`. One is told from an ordinary English word
# by the characters no English word carries (an underscore, a dot or a slash inside the token, a
# call's brackets) or by standing as a name the same file declares.
IDENTIFIER_MARK = re.compile(r"[_(\[]|\w[./:]\w")
SYMBOL = re.compile(r"\b(?:def|class|function|const|let|var)\s+([A-Za-z_$][\w$]*)"
                    r"|\b([A-Za-z_$][\w$]*)\s*[:=]\s*(?:function\b|\()")


def symbols_in(text):
    """Every name a file declares, so a sentence that opens on one is naming code, not stammering."""
    found = {a or b for a, b in SYMBOL.findall(text)}
    found.discard("")
    return found


# THE CAPITAL A CUT LEFT BEHIND. A sweep that takes the last token off a comment line leaves the
# word below it standing at the head of the line, and the word was capitalised to make the line
# read: "a substring that must appear in a skip's reason / For that skip to be allowed". The
# sentence now carries a capital in its middle and the reader meets a new sentence that is really
# half of the one above.
#
# The shape is a line INSIDE a run, whose previous line did not finish a sentence, opening on a
# Capitalised-then-lower-case word. Three things are not that: a name the code uses (an
# identifier), a word in all capitals (this tree shouts for emphasis), and a proper noun, which is
# recognised without a list, from the same file writing the same word INSIDE a line.
BANNER = " \t-*=#/+.|<>~_"
# The decoration at the end of a banner line, which is not the end of a sentence.
RULE_OFF = " \t-=*#|~"
SENTENCE_END = re.compile(r"[.!?:;][)\"'`\]]*$")
CAPITALISED = re.compile(r"\A[A-Z][a-z]")
LIST_MARKER = re.compile(r"[*+.o]\s|\d{1,2}[.)]\s|[a-z][.)]\s|-\s|\|")
# The closed class: a word that cannot open a sentence of its own, so a capital on it says
# the sentence in front of it was cut away. An open-class word (a noun, a verb) opens plenty
# of sentences and would make this rule a guess.
#
# THE HOLE THIS LEAVES IS SEVENTY-SEVEN SITES WIDE, and it is a standing hole, not a backlog.
# A sweep that lifts the last token off a comment line leaves the word below it at the head of
# the line still wearing the capital that made the line read, and where that word is open-class
# ("several pins Join against", "a digest their Metadata does not match", "so every data download
# Can carry them") nothing here can see it: the same word opens a sentence honestly on the line
# above and below it. Seventy-seven such sites were measured against origin/main word for word
# and swept BY HAND, one commit, each restored to the spelling origin/main writes. The rule as
# written finds none of them, and a later round that cuts prose will make more.
FUNCTION_WORDS = frozenset(
    "For In On At To From With Without Of By Into Onto Over Under Between Through During "
    "Against Per Via Among Because Although Though Whereas Unless Until Since And But Or "
    "Nor So Yet Which That Who Whom Whose Than Then Also Too Plus Instead Rather".split())
WORDS_IN_LINE = re.compile(r"(?<=\S[ \t])([A-Z][a-z]+)")
# What makes a token a NAME rather than an English word: a digit, a separator, or a dot
# inside it.
NAME_MARK = re.compile(r"_|\w\.\w")


def names_written_inside_a_line(path, text):
    """Every Capitalised word this file writes INSIDE a comment line rather than at its head. A
    proper noun turns up mid-line; a word capitalised only where a cut left it does not."""
    found = set()
    for _, comment in comment_runs(path, text):
        for line in bare(comment).splitlines():
            found.update(WORDS_IN_LINE.findall(line))
    return found


def head_capital_of_a_name(comment, text):
    """The word a run opens on when it is a NAME wearing a capital it does not have: a sweep that
    cut the words in front of it capitalised what was left, and `station.json` became
    `Station.json`, which names no file. A name is told by the characters it carries; the proof is
    that the same file writes the lower-case spelling somewhere else."""
    flat = flattened(bare(comment)).lstrip(BANNER)
    word = flat.split(" ", 1)[0].strip("\"'`(,:;")
    if not word[:1].isupper() or not NAME_MARK.search(word[1:]) or not word[1:].islower():
        return None
    lowered = word[0].lower() + word[1:]
    return word if lowered in text else None


def capitals_mid_sentence(comment, symbols, names):
    """Every word inside one run that opens a line, is capitalised, and continues the sentence the
    line above left unfinished."""
    lines = bare(comment).splitlines()
    found = []
    for before, line in zip(lines, lines[1:]):
        # A blank line, a finished sentence and a list marker all start something new; only a line
        # that carried on is continued by the line under it.
        if not before.strip() or not line.strip():
            continue
        # A line that is nothing but banner decoration is not a sentence and cannot leave one
        # unfinished, so the line under a rule-off opens what follows rather than continuing it.
        # Without this the head of every banner-led block reads as a capital in mid-sentence.
        if not before.strip(BANNER):
            continue
        if SENTENCE_END.search(unquoted(before).rstrip(RULE_OFF)):
            continue
        if LIST_MARKER.match(line.strip()) or LIST_MARKER.match(before.strip()):
            continue
        word = unquoted(line).strip(BANNER).split(" ", 1)[0].strip("\"'`(")
        if not CAPITALISED.match(word or ""):
            continue
        if word not in FUNCTION_WORDS or word in names:
            continue
        found.append(word)
    return found


def reads_as_an_identifier(word, symbols):
    """True when the word a sentence opens on is a name out of the code rather than English."""
    bare_word = word.strip("`\"'*,;:").rstrip(".")
    return not bare_word or bool(IDENTIFIER_MARK.search(bare_word)) or bare_word in symbols


def unquoted(text):
    """The prose with every quoted run blanked to a filler letter of the same length, so a
    bracket or a punctuation mark the comment is quoting is not read as the comment's own."""
    return QUOTED_RUN.sub(lambda m: "q" * len(m.group(0)), text)


def unbalanced(prose):
    """Every unmatched bracket in one comment, as (character, index). An opener pairs with ANY
    closer so interval notation balances, and a closer that opens a line as an enumerator is a
    list marker rather than a bracket. A quoted run wrapped across two comment lines is one
    quoted run to a reader, so the wraps are read as spaces before the quotes are blanked; the
    blanking keeps the text's length, so a bracket still reports where it stands."""
    cleaned = unquoted(prose.replace("\n", " "))
    stack, stray, line_start = [], [], 0
    for i, ch in enumerate(cleaned):
        if prose[i] == "\n":
            line_start = i + 1
        elif ch in "([{":
            stack.append((ch, i))
        elif ch in ")]}":
            if stack:
                stack.pop()
            elif not (ch == ")" and ENUMERATOR.match(cleaned[line_start:i + 1])):
                stray.append((ch, i))
    return stack + stray


def pointer_fragments(flat):
    """Every "See docs:" pointer in one flattened comment, as (fragment, match-or-None)."""
    found = []
    for match in POINTER_ANY.finditer(flat):
        fragment = match.group(0)
        stop = fragment.find(". ")
        fragment = fragment[:stop + 1] if stop >= 0 else fragment
        found.append((fragment, POINTER_GRAMMAR.match(fragment)))
    return found


def shape_offences(files, root=None):
    """Every comment whose SHAPE is broken across a set of files, as report lines."""
    found = []
    for path in files:
        text = source_text(path)
        where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        symbols = symbols_in(text)
        names = names_written_inside_a_line(path, text)
        for lineno, comment in comment_runs(path, text):
            lines = bare(comment).splitlines()
            body = [line for line in lines if line.strip()]
            if not body:
                continue
            joined = "\n".join(lines)
            flat = " ".join(joined.split())
            clean = unquoted(joined)
            table = len(DEFINITION_ROW.findall(clean)) >= 2
            said = []
            # Wherever in the run the stray bracket falls. A reader reads the run, so a bracket
            # left open on an interior line is the same broken shape as one left open on the
            # first; reporting only the head and the tail hides the middle of every long comment.
            for ch, _ in unbalanced(joined):
                said.append("unmatched %s" % ch)
                break
            # On the run a reader reads as well as on each line: a wrap between the last word of a
            # sentence and the full stop that ends it is the gap a cut token left, not a wrap.
            for line in clean.splitlines() + [unquoted(flat)]:
                if SPACE_BEFORE_PUNCT.search(line) or (not table and SPACE_BEFORE_COLON.search(line)):
                    said.append("a space before punctuation")
                    break
            if OPENS_ON_PUNCTUATION.match(unquoted(flat)):
                said.append("a run opening on the punctuation of a cut sentence")
            if SPACE_BEFORE_BRACKET.search(unquoted(flat)):
                said.append("a space before the bracket that closes a group")
            if EMPTY_GROUP.search(unquoted(flat)):
                said.append("an empty bracketed group")
            if OPEN_CONNECTOR.search(unquoted(flat)):
                said.append("a bracket opening on a connector")
            bare_flat = unquoted(flat)
            if (CLOSE_CONNECTOR.search(bare_flat)
                    or any(CONNECTOR_PAIR.search(group.group(0))
                           for group in BRACKET_GROUP.finditer(bare_flat))):
                said.append("a connector left standing where a token was cut")
            if any(LINE_OPENS_ON_STRAY.match(line.strip())
                   for line in unquoted(joined).splitlines() if line.strip()):
                said.append("a line opening on the punctuation a cut left standing")
            doubled = DOUBLED_WORD.search(unquoted(flat))
            if doubled:
                said.append("a word written twice (%s)" % " ".join(doubled.group(0).split()))
            orphaned = ORPHANED_DETERMINER.search(unquoted(flat))
            if orphaned:
                said.append("a sentence ending on the word that introduced its noun (%s)"
                            % orphaned.group(0).strip())
            if ORPHANED_COPULA.search(unquoted(flat)):
                said.append("a sentence ending on the verb whose complement was cut")
            headless = SUBJECTLESS_SENTENCE.search(unquoted(flat))
            if headless:
                said.append("a sentence opening on a verb with no subject (%s)"
                            % headless.group(1))
            pairs = marks_together(unquoted(flat))
            if pairs:
                said.append("two sentence marks with nothing between them (%s)" % pairs[0])
            if (PARTICIPLE_PREPOSITION.search(unquoted(flat))
                    or DEMONSTRATIVE_COPULA.search(unquoted(flat))
                    or COPULA_GROUP.search(unquoted(flat))):
                said.append("a word left hard against the bracket that closed its group")
            if OPERATOR_ORPHAN.search(unquoted(flat)):
                said.append("an operator standing where the value it points at was cut")
            cut = MIDSENTENCE_SUBJECT.search(unquoted(flat))
            if cut:
                said.append("a verb whose subject was cut from the middle of its sentence (%s)"
                            % " ".join(cut.group(0).split()))
            if BARE_LABEL.search(unquoted(flat)):
                said.append("a bracketed aside reduced to the label that introduced it")
            for low, high in inverted_ranges(unquoted(flat)):
                said.append("a range whose lower bound stands above its upper (%s..%s)"
                            % (low, high))
                break
            if any(DANGLING_HYPHEN.search(line) for line in clean.splitlines()):
                said.append("a hyphen with nothing after it")
            orphan = POINTER_ORPHAN.search(bare_flat)
            if orphan and not reads_as_an_identifier(orphan.group(1), symbols):
                said.append("a pointer standing in front of a sentence fragment")
            wrong_case = head_capital_of_a_name(comment, text)
            if wrong_case:
                said.append("a name wearing a capital it does not have (%s)" % wrong_case)
            carried = capitals_mid_sentence(comment, symbols, names)
            if carried:
                said.append("a capital in the middle of a sentence (%s)" % ", ".join(carried[:3]))
            if any(m is None for _, m in pointer_fragments(flat)):
                said.append("a pointer that is not of the pointer grammar")
            if said:
                found.append("%s:%s: %s: %s" % (where, lineno, ", ".join(said), flat[:110]))
    return found


# WHAT IS, NOT WHAT WAS. A comment a visitor downloads is read by someone who cannot open the file
# it talks about, so a sentence about a tile that was removed, a control that was retired or a
# section folded into another leaves that reader holding a fact with nothing behind it. A shipped
# comment states the invariant that holds now; git carries what was.
#
# The same words describe DATA the code handles, and that sense is the code's own behaviour rather
# than its history: "a station is dropped by the gate" says what the gate does. The two are told
# apart by what stands in front of the verb. A thing the code HANDLES is introduced by an
# indefinite article or arrives as a bare plural; a part the page is MADE OF is named, usually in
# quotes, and takes the definite article. A negated clause ("is never folded into") is a constraint
# and not a history at all.
HISTORY_SHAPE = re.compile(
    r"\blived here\b"
    r"|\bfolded into\b"
    r"|\bthe\s+(?:retired|removed|deleted|former)\s+[\w-]+"
    r"|\b(?:is|are|was|were)\s+(?:[\w-]+\s+){0,2}(?:gone|removed|retired|deleted|dropped)\b",
    re.I)
HANDLED_THING = re.compile(
    r"(?:\ba|\ban|\bany|\bevery|\beach|\bno)\s+(?:[\w-]+\s+){0,6}$"
    r"|\b(?:rows|stations|values|entries|slashes|characters|keys|bindings|bytes|ids)"
    r"\s+(?:[\w-]+\s+){0,2}$", re.I)
NEGATED = re.compile(r"\b(?:never|not|cannot|no)\b\s+(?:[\w-]+\s+){0,2}$", re.I)
HISTORY_WINDOW = 60


def history_shapes(comment):
    """Every place one comment says what WAS rather than what is, as matched text."""
    text = flattened(bare(comment))
    found = []
    for match in HISTORY_SHAPE.finditer(text):
        before = text[max(0, match.start() - HISTORY_WINDOW):match.start()]
        if HANDLED_THING.search(before) or NEGATED.search(before):
            continue
        found.append(match.group(0))
    return found


def history_offences(files, root=None):
    """Every shipped comment that narrates what was removed, as report lines."""
    found = []
    for path in files:
        text = source_text(path)
        where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        for lineno, comment in comment_runs(path, text):
            shapes = history_shapes(comment)
            if shapes:
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(sorted(set(shapes))),
                                " ".join(comment.split())[:110]))
    return found


# THE OPERATOR STRINGS. argparse prints help, description and epilog to whoever runs the tool, so
# they are read the way a comment is read and carry the same rule. Two guards miss them by
# construction: a behaviour comparison that blanks docstrings cannot see a description built from
# __doc__, and a framing classification that reads non-docstring literals sees the bytes without
# knowing they reach a person.
ARGPARSE_TEXT = ("help", "description", "epilog")
# THE LINES A TOOL PRINTS. A result printed to a terminal is read by the operator who ran the tool,
# exactly as its --help is, and no guard above sees those bytes: argparse text is a keyword argument
# and a printed line is a bare literal. The operator tools are named, because a print inside a
# library or a test is a diagnostic for whoever is debugging it rather than a line an operator reads.
OPERATOR_TOOLS = ("/deploy/scripts/", "/engine/scripts/", "/engine/tests/ci_check_skips.py")
OPERATOR_SHELL_TREE = "/deploy/"
# echo and printf, their option flags skipped, carrying one quoted argument. A shell script has no
# syntax tree to walk, so the line is read as a line; a here-document or an unquoted word is not
# read, which makes this rule narrower than the Python one rather than wider.
ECHO_STRING = re.compile(r"""(?<![\w./-])(?:echo|printf)(?:\s+-[A-Za-z]+)*\s+"""
                         r"""("([^"\\]*(?:\\.[^"\\]*)*)"|'([^']*)')""")


def is_operator_tool(path):
    """True for a tool whose printed lines an operator reads on a terminal."""
    where = path.as_posix()
    if path.suffix.lower() == ".sh":
        return OPERATOR_SHELL_TREE in where
    return any(tool in where for tool in OPERATOR_TOOLS)


def echo_strings(path):
    """(line number, text) for every literal a shell script echoes to the operator."""
    try:
        lines = source_text(path).splitlines()
    except (UnicodeDecodeError, OSError):
        return []
    found = []
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        for match in ECHO_STRING.finditer(line):
            found.append((lineno, match.group(2) if match.group(2) is not None else match.group(3)))
    return found


def operator_strings(path):
    """(line number, text) for every string a tool prints to whoever ran it: argparse's help,
    description and epilog anywhere a parser is built, and, on the operator tools alone, the lines
    the tool itself prints."""
    if path.suffix.lower() == ".sh":
        return echo_strings(path) if is_operator_tool(path) else []
    if path.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(source_text(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    prints = is_operator_tool(path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if prints and isinstance(node.func, ast.Name) and node.func.id == "print":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((arg.lineno, arg.value))
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("add_argument", "ArgumentParser"):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if (keyword.arg in ARGPARSE_TEXT and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                found.append((value.lineno, value.value))
    return found


# THE MESSAGES A FAILURE PRINTS. An assertion message and a skip reason are read by whoever is
# looking at a red run, which is the same reader a comment has, and no guard above sees them: a
# message is a bare literal and a reason is a keyword argument on a marker. They keep their
# semantics, which is what tells the reader what broke; what they drop is the audit trail. The dash
# rule reaches them because a reason is printed on a terminal, where the glyph is not always legible.
SKIP_CALLS = ("skip", "xfail")
REASON_CALLS = ("skip", "xfail", "skipif")
DASHES = ("\u2014", "\u2013")


def _static_text(node, names=None):
    """The literal text of a string node: an f-string's constant parts included, and a module-level
    constant resolved where a name map is given. A reason held in a NAME is the same reason to the
    reader of a red run, and a rule that reads only literals does not reach it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if names is not None and isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def module_constants(tree):
    """Every module-level NAME = "..." binding, so a message held in a constant is read where it is
    used rather than where it is spelled."""
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            text = _static_text(node.value)
            if text:
                found[node.targets[0].id] = text
    return found


def message_strings(path):
    """(line number, text) for every assertion message and every skip or xfail reason in a module."""
    if path.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(source_text(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    names = module_constants(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.msg is not None:
            text = _static_text(node.msg, names)
            if text:
                found.append((node.msg.lineno, text))
            continue
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in REASON_CALLS:
            continue
        # skipif's first positional argument is the CONDITION, so only skip and xfail are read
        # positionally; all three carry the reason as a keyword.
        if name in SKIP_CALLS:
            for arg in node.args:
                text = _static_text(arg, names)
                if text:
                    found.append((arg.lineno, text))
        for keyword in node.keywords:
            if keyword.arg != "reason":
                continue
            text = _static_text(keyword.value, names)
            if text:
                found.append((keyword.value.lineno, text))
    return found


# A message is held to the AUDIT TRAIL, not to the whole comment vocabulary. A failure message says
# what changed, so "no longer" and "used to" are the finding rather than a history note; a TODO or a
# placeholder inside one is a test's own scaffolding; and a pin may cite the contract it holds. What
# a message may not carry is who decided, when, and under which work item, wave, round or lane.
MESSAGE_LABELS = (
    "decision-owner language", "ruling language", "approval language", "wave identifier",
    "work-item identifier", "lane name", "design-history vocabulary", "old-to-new history",
    "dated note", "branch name", "review or slice identifier", "round-of-work identifier",
    "design-document citation",
)
# A message that NAMES the glyph it is about keeps it: the dash inside a quoted run is the data the
# assertion is talking about, not the message's own punctuation. The run is the one QUOTED_RUN
# pairs, left to right, opening mark to the SAME closing mark. A pattern that let the two marks be
# different characters read the closing mark of one run and the opening mark of the next as a run of
# its own, so a dash standing BETWEEN two backtick runs was excused as though it stood inside one,
# when a dash between two quoted runs is the message's own punctuation.


def message_offences(files, root=None):
    """Every message or reason that carries the audit trail or a typographic dash, as report lines."""
    found = []
    for path in files:
        where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        for lineno, text in message_strings(path):
            labels = [label for label in labels_for(text, cite_contract=True)
                      if label in MESSAGE_LABELS]
            if any(dash in text for dash in DASHES) and any(
                    dash in unquoted(text) for dash in DASHES):
                labels.append("an em or en dash")
            if labels:
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(labels), flattened(text)[:110]))
    return found


def operator_offences(files, root=None):
    """Every operator string that breaks the rule, as report lines."""
    found = []
    for path in files:
        where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        for lineno, text in operator_strings(path):
            labels = [label for label in labels_for(text) if label != "commented-out code"]
            if labels:
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(labels), flattened(text)[:110]))
    return found


# WHAT A TOOL ACTUALLY PUTS IN FRONT OF AN OPERATOR. The rule above reads the literal standing
# inside print() or echo, so a line ASSEMBLED somewhere else and printed later is invisible to it:
# a failure appended to a list and joined at the end, a status detail held in a variable and handed
# to the writer that puts it in the document the serve screen reads. Two surfaces close that. The
# tool is RUN in a mode an operator can run without a box and everything it writes to stdout and
# stderr is read; and, because a passing run does not print its failure lines and a tool that
# reconciles a live box cannot be run here at all, every literal that reaches an output through a
# NAME or a LIST is read where it is written.
#
# The vocabulary is the audit-trail subset, as it is for a message and for the same reason: a
# printed result says what it found, so "no longer a hard guard" is the finding rather than a
# history note. What it may not carry is who decided, when, and under which work item. The glyph
# rule rides with it, because these bytes land on a terminal.
OUTPUT_WRITERS = ("stdout", "stderr")
# The shell function that writes the status document an operator reads on the serve screen. It is
# an output as surely as echo is; the bytes simply reach the reader through a file.
STATUS_WRITER = "write_status"
SHELL_OUTPUT_COMMAND = re.compile(r"(?:\A|[\n;&|(])[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*"
                                  r"(?:echo|printf|write_status)(?![\w./-])")
SHELL_STATUS_CALL = re.compile(r"(?:\A|[\n;&|(])[ \t]*write_status(?![\w./-])")
SHELL_ASSIGNMENT = re.compile(r"(?m)^[ \t]*(_?[A-Za-z_]\w*)=(\"(?:[^\"\\]|\\.)*\"|'[^']*')")


def _quoted_arguments(text, at):
    """Every quoted argument of the command starting at `at`, read to the command's END rather than
    to the end of the line: a status detail is a double-quoted string that runs across a dozen
    lines, and a line-wise reader sees only its first."""
    found = []
    i = at
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            if not (i and text[i - 1] == "\\"):
                break
            i += 1
            continue
        if ch in "'\"":
            j = i + 1
            while j < len(text):
                if text[j] == "\\" and ch == '"':
                    j += 2
                    continue
                if text[j] == ch:
                    break
                j += 1
            found.append((text.count("\n", 0, i) + 1, text[i + 1:j]))
            i = j + 1
            continue
        i += 1
    return found


def status_writer_strings(path):
    """(line number, text) for every literal a shell tool puts in front of an operator other than
    on a terminal line: an argument of the status writer, and a literal held in a NAME that is
    later handed to an output command."""
    try:
        text = source_text(path)
    except (UnicodeDecodeError, OSError):
        return []
    found = []
    for match in SHELL_STATUS_CALL.finditer(text):
        found += _quoted_arguments(text, match.end())
    handed = set()
    for match in SHELL_OUTPUT_COMMAND.finditer(text):
        stop = text.find("\n", match.end())
        line = text[match.end():len(text) if stop < 0 else stop]
        handed.update(re.findall(r"\$\{?(\w+)\}?", line))
    for match in SHELL_ASSIGNMENT.finditer(text):
        if match.group(1) in handed:
            found.append((text.count("\n", 0, match.start()) + 1, match.group(2)[1:-1]))
    return sorted(set(found))


def _names_that_reach_output(tree):
    """Every NAME whose value a tool prints, however it is assembled on the way."""
    reached = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            printed = list(node.args)
        elif (isinstance(node.func, ast.Attribute) and node.func.attr == "write"
              and isinstance(node.func.value, ast.Attribute)
              and node.func.value.attr in OUTPUT_WRITERS):
            printed = list(node.args)
        else:
            continue
        for arg in printed:
            reached.update(inner.id for inner in ast.walk(arg) if isinstance(inner, ast.Name))
    return reached


def _literals_in(node):
    """Every literal inside one expression, each read ONCE: an f-string is one line to the reader,
    not a line per constant part, so the walk stops where it finds text rather than descending
    into it."""
    text = _static_text(node)
    if text is not None:
        return [(node.lineno, text)] if text.strip() else []
    found = []
    for child in ast.iter_child_nodes(node):
        found += _literals_in(child)
    return found


def indirect_operator_strings(path):
    """(line number, text) for every literal that reaches a printed line through a name or a list.
    A failure appended to a list and joined at the end is read by the operator exactly as a literal
    inside print() is."""
    try:
        tree = ast.parse(source_text(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    reached = _names_that_reach_output(tree)
    found = []
    for node in ast.walk(tree):
        names, values = [], []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            values = [node.value]
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            names, values = [node.target.id], [node.value]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("append", "extend", "add")
              and isinstance(node.func.value, ast.Name)):
            names, values = [node.func.value.id], list(node.args)
        if not set(names) & reached:
            continue
        for value in values:
            found += _literals_in(value)
    return sorted(set(found))


def output_labels(text):
    """The audit trail and the glyph a line an operator reads may not carry."""
    labels = [label for label in labels_for(text, cite_contract=True) if label in MESSAGE_LABELS]
    if any(dash in text for dash in DASHES) and any(
            dash in unquoted(text) for dash in DASHES):
        labels.append("an em or en dash")
    return labels


def assembled_output_offences(files, root=None):
    """Every literal a tool assembles and then puts in front of an operator, as report lines."""
    found = []
    for path in files:
        where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        read = (status_writer_strings(path) if path.suffix.lower() == ".sh"
                else indirect_operator_strings(path))
        for lineno, text in read:
            labels = output_labels(text)
            if labels:
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(labels), flattened(text)[:110]))
    return found


def run_output_offences(path, mode, root=None, python=None, cwd=None):
    """Everything the tool writes to stdout and stderr in one mode, held to the same rule. The exit
    code is not read: a tool that reports a real failure is still a tool whose words an operator
    has to read."""
    where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
    got = subprocess.run([python or sys.executable, str(path)] + list(mode),
                         capture_output=True, text=True, encoding="utf-8",
                         cwd=str(cwd) if cwd else None)
    said = (got.stdout or "") + (got.stderr or "")
    labels = output_labels(said)
    if not labels:
        return []
    return ["%s %s: %s: %s" % (where, " ".join(mode), ", ".join(labels), flattened(said)[:160])]


# --- shared extractor and vocabulary: end -----------------------------------


SHARED_BEGIN = "# --- shared extractor and vocabulary: begin"
SHARED_END = "# --- shared extractor and vocabulary: end"

PINS = (ROOT / "portal" / "tests" / SELF,
        ROOT / "engine" / "tests" / SELF,
        DEPLOY / "tests" / SELF)


def under(base, pattern="*"):
    return [
        p for p in sorted(base.rglob(pattern))
        if p.is_file() and p.name != SELF and VENDORED not in p.parts
        and "__pycache__" not in p.parts and "node_modules" not in p.parts
    ]


MARKUP_SUFFIXES = (".py", ".js", ".hujson", ".html", ".css", ".plist")


def deploy_tree():
    """Every commented file under deploy/: the Python, and the shell, YAML, systemd units,
    Caddyfiles, Makefile and Dockerfiles the extractor reads a # comment in."""
    return [p for p in under(DEPLOY)
            if p.suffix.lower() in HASH_SUFFIXES or p.name in HASH_NAMES
            or p.suffix.lower() in MARKUP_SUFFIXES]


def gateway_tree():
    return under(GATEWAY, "*.py")


CONFIG_SUFFIXES = (".toml", ".txt", ".cfg", ".yaml", ".yml")


def gateway_config():
    """The gateway's own declared configuration. gateway_tree() globs *.py, so the requirements
    files and the lock the image installs sat outside every class while carrying prose like any
    module does. deploy/ needs no twin of this: its class is every commented file under the tree."""
    return [p for p in under(GATEWAY) if p.suffix.lower() in CONFIG_SUFFIXES]


SURFACES = {"the deploy tree": deploy_tree, "the gateway tree": gateway_tree,
            "the gateway configuration": gateway_config}


def workflows():
    """The CI workflow files. They are read for SHAPE and never for vocabulary: `lane` there names
    a job on a runner, not a run of work, and 27 of the 28 vocabulary hits over these four files
    are that word in its CI sense. A class left outside the sweep while the sweep's own shape rules
    can find its scars is not an exemption, it is an unswept class."""
    return sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_workflow_comments_are_whole_prose():
    """SHAPE only, for the reason workflows() gives."""
    files = workflows()
    assert files, "the workflow class resolved to no files, so this would pass over nothing"
    hits = shape_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} workflow comment(s) carry the shape a cut token leaves behind:\n"
        + "\n".join(hits))


def test_deploy_comments_state_constraints_only():
    hits = offences([p for p in deploy_tree() if "tests" not in p.parts], root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in deploy/ carry provenance rather than a constraint:\n" + "\n".join(hits)
    )


def test_gateway_comments_state_constraints_only():
    hits = offences([p for p in gateway_tree() if "tests" not in p.parts], root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in gateway/ carry provenance rather than a constraint:\n" + "\n".join(hits)
    )


def test_gateway_configuration_comments_state_constraints_only():
    hits = offences([p for p in gateway_config() if "tests" not in p.parts], root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the gateway's configuration carry provenance rather than a "
        "constraint (the image installs these files):\n" + "\n".join(hits)
    )


def test_guard_test_comments_state_constraints_only():
    files = [p for p in deploy_tree() + gateway_tree() if "tests" in p.parts]
    hits = offences(files, cite_contract=True, root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the deploy and gateway suites carry provenance rather than a "
        "constraint (a pin may cite the contract that it holds; it may not carry dates, decision "
        "provenance or work-item identifiers):\n" + "\n".join(hits)
    )


def test_every_surface_class_is_actually_read():
    empty = []
    for label, files in SURFACES.items():
        found = files()
        assert found, f"{label}: no files matched, so this sweep would pass over nothing"
        seen = sum(len(comments(p, source_text(p))) for p in found)
        if seen == 0:
            empty.append(f"{label}: {len(found)} file(s), zero comments extracted")
    assert not empty, "the extractor read no comments at all on:\n" + "\n".join(empty)


def test_the_non_python_half_of_deploy_is_inside_the_sweep():
    """Shell, YAML, systemd and Caddyfile comments are most of what deploy/ ships. A sweep that
    reads only the Python passes over the operator-facing half of the tree."""
    kinds = {}
    for path in deploy_tree():
        if path.suffix.lower() == ".py":
            continue
        found = comments(path, source_text(path))
        if found:
            kinds.setdefault(path.suffix.lower() or path.name, 0)
            kinds[path.suffix.lower() or path.name] += len(found)
    for want in (".sh", ".yaml", ".service", "Caddyfile"):
        assert kinds.get(want), f"the sweep read no comments in any {want} file: {sorted(kinds)}"


def test_the_three_pins_carry_one_extractor():
    """The block cannot be imported from one place: engine/tests must read nothing outside engine/,
    or the module would skip inside the engine image. Held equal instead, so a fix to the scanner
    cannot land on one tree and leave the other two reading less."""
    blocks = []
    for pin in PINS:
        text = pin.read_text(encoding="utf-8")
        start, end = text.find(SHARED_BEGIN), text.find(SHARED_END)
        assert start >= 0 and end > start, f"{pin.name}: the shared block's markers are missing"
        blocks.append(text[start:end])
    assert blocks[0] == blocks[1] == blocks[2], (
        "the three pins carry different extractors, so one tree is being swept by an older scanner"
    )


def test_the_vendored_validator_is_left_alone():
    vendored = [p for p in GATEWAY.rglob("*.py") if VENDORED in p.parts]
    assert vendored, "the vendored validator is missing, so this exclusion would be silent"
    assert not [p for p in gateway_tree() if VENDORED in p.parts], (
        "the sweep reached into the vendored validator, whose bytes are a pinned third-party copy"
    )


# ---------------------------------------------------------------------------
# The extractor and the vocabulary. The full battery lives in the portal twin;
# these are the cases the deploy tree turns on.
# ---------------------------------------------------------------------------
def test_a_comment_trailing_a_command_is_extracted(tmp_path):
    cases = {
        "trail.sh": ("run_it --now   # the trailing note\n", "# the trailing note"),
        "trail.yaml": ("key: value  # the trailing note\n", "# the trailing note"),
        "trail.service": ("ExecStart=/usr/bin/true  # the trailing note\n", "# the trailing note"),
        "Caddyfile": ("respond 200  # the trailing note\n", "# the trailing note"),
    }
    for name, (body, want) in cases.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        found = [c for _, c in comments(f, body)]
        assert found == [want], f"{name}: expected {want!r}, got {found!r}"


def test_a_hash_inside_an_expansion_a_quote_or_a_heredoc_is_not_a_comment(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text('base="${name#prefix}"\n'
                 'printf "%s\\n" "a # not a comment"\n'
                 "cat > /tmp/out <<'EOF'\n# written into the file, not a comment\nEOF\n"
                 "# the only comment\n", encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ["# the only comment"], found


def test_a_shebang_is_not_commentary(tmp_path):
    f = tmp_path / "tool.sh"
    f.write_text("#!/usr/bin/env bash\nset -eu\n", encoding="utf-8")
    assert comments(f, f.read_text(encoding="utf-8")) == []


def test_a_planted_comment_is_caught(tmp_path):
    for name in ("planted.py", "planted.sh", "planted.yaml", "planted.service"):
        f = tmp_path / name
        f.write_text("# UX6 Wave B: the owner's ruling of 2026-08-19\n", encoding="utf-8")
        assert offences([f]), f"the scanner did not catch a planted comment in {name}"


def test_a_clean_comment_is_not_flagged(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("# The two lists must stay equal; pinned by tests/test_frontdoor_ts_routes.py.\na = 1\n",
                 encoding="utf-8")
    assert not offences([f]), "the scanner flagged a comment that states a constraint and a pin"


def test_a_served_template_is_not_read_as_a_docstring(tmp_path):
    """A triple-quoted page template is content, not commentary, and is not swept as one."""
    f = tmp_path / "page.py"
    f.write_text('def page():\n'
                 '    """Renders the console."""\n'
                 '    return """<p>the owner approved this on 2026-08-19</p>"""\n', encoding="utf-8")
    found = comments(f, f.read_text(encoding="utf-8"))
    assert len(found) == 1 and "Renders the console" in found[0][1], found
    assert not offences([f]), "the sweep reached into a served template"


def test_the_approval_narrowing_targets_a_design_decision_not_the_workflow(tmp_path):
    clean = tmp_path / "clean.py"
    clean.write_text("# Writes a `Curated-by:`/`Approved-by:` trailer once the curator approved the\n"
                     "# submission.\na = 1\n", encoding="utf-8")
    assert not offences([clean]), "the approval rule flagged the gateway's own workflow vocabulary"
    for line in ("# Rebuilt to the approved mockup's structure.",
                 "# The wording here is the approved one.",
                 "# Kept as approved."):
        dirty = tmp_path / "dirty.py"
        dirty.write_text(f"{line}\na = 1\n", encoding="utf-8")
        assert offences([dirty]), f"the approval rule was side-stepped by: {line}"


def test_the_owner_narrowing_reaches_only_the_variable_beside_it(tmp_path):
    named = tmp_path / "named.sh"
    named.write_text("# OWNER is the AUSMT_OWNER variable the compose files read.\nset -eu\n",
                     encoding="utf-8")
    assert not offences([named]), "the narrowing missed the shell variable it exists for"
    far = tmp_path / "far.py"
    far.write_text('"""The panel is the shape the owner asked for.\n\n'
                   + "    Filler that carries the paragraph well past the window.\n" * 4
                   + '    The compose files read AUSMT_OWNER for the same value.\n    """\n',
                   encoding="utf-8")
    assert offences([far]), (
        "a mention of the variable pages away excused decision-owner language, so the narrowing "
        "is a hole rather than an exemption"
    )


def test_a_pin_may_cite_the_contract_it_holds_and_code_may_not(tmp_path):
    cite = tmp_path / "cite.py"
    cite.write_text("# Ranges take the spaced hyphen (LANE-ADDENDUM-HUB-FEEDBACK.md).\na = 1\n",
                    encoding="utf-8")
    assert not offences([cite], cite_contract=True), "the lane rule flagged a contract citation in a pin"
    assert offences([cite]), "code carried a contract file name and the sweep allowed it"
    name = tmp_path / "name.py"
    name.write_text("# The download lane reshaped this panel.\na = 1\n", encoding="utf-8")
    assert offences([name], cite_contract=True), "the lane rule missed a lane name"


def test_an_address_is_not_a_person(tmp_path):
    f = tmp_path / "fixture.py"
    f.write_text('# The DB says Owner@Private.Test and the artifact carries owner@private.test.\na = 1\n',
                 encoding="utf-8")
    assert not offences([f]), "the decision-owner rule flagged an email address in a fixture"


def test_the_commented_out_code_rule_needs_a_call_not_a_mention(tmp_path):
    prose = tmp_path / "prose.js"
    prose.write_text("// fetch() is the scripted healthz probe.\nvar a = 1;\n", encoding="utf-8")
    assert not offences([prose]), "the rule flagged prose that merely names the function"
    code = tmp_path / "code.js"
    code.write_text('// fetch("/api/x").then(r => r.json());\nvar a = 1;\n', encoding="utf-8")
    assert offences([code]), "the rule missed a commented-out call"


def test_a_tag_named_in_prose_is_not_commented_out_markup(tmp_path):
    prose = tmp_path / "prose.py"
    prose.write_text('def f():\n    """The screen must ship no inline\n    <script> block without src=.\n    """\n',
                     encoding="utf-8")
    assert not offences([prose]), "the rule flagged a tag named in a sentence"
    markup = tmp_path / "markup.html"
    markup.write_text('<!--\n<script defer src="https://example.invalid/x.js"></script>\n-->\n', encoding="utf-8")
    assert offences([markup]), "the rule missed a commented-out tag"


# ---------------------------------------------------------------------------
# Comment shape: the scar a removed token leaves is invisible to a vocabulary.
# ---------------------------------------------------------------------------
def test_comment_shapes_are_whole():
    files = []
    for producer in SURFACES.values():
        files += producer()
    hits = shape_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in deploy/ and gateway/ carry the shape a cut token leaves "
        "behind rather than whole prose:\n" + "\n".join(hits))


def test_a_broken_shape_is_caught_and_whole_prose_is_not(tmp_path):
    broken = tmp_path / "broken.sh"
    broken.write_text("# The poll loop (- the one background task).\nrun_it\n", encoding="utf-8")
    assert shape_offences([broken]), "a bracket opening on a connector went unseen"
    whole = tmp_path / "whole.sh"
    whole.write_text("# The cap is enforced mid-stream (per chunk).\nrun_it\n", encoding="utf-8")
    assert not shape_offences([whole]), "whole prose was read as a broken shape"


def test_operator_strings_state_what_the_tool_does():
    """The twin of the engine guard, over deploy/ and gateway/. A --help string is printed to
    whoever runs the tool and is held to the same vocabulary as a comment."""
    files = []
    for producer in SURFACES.values():
        files += producer()
    hits = operator_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} argparse string(s) print provenance to an operator:\n" + "\n".join(hits))


# The deploy operator tools and the mode each one answers on a checkout. A tool is READ instead of
# run when running it proves nothing: reconcile.sh reconciles a LIVE box and cannot be driven here,
# and aggregate_stats.py carries no argparse at all, so "--help" is not a help mode for it and the
# run reads one environment line (73 bytes) rather than any operator prose. Both are still read in
# full by the assembled surface below, which is where every literal they print is guarded.
RUNNABLE_TOOLS = (
    ("scripts/check_compose_guards.py", ("--self-test",)),
    ("scripts/gen_ts_routes.py", ("--check",)),
    ("scripts/prep_au_states.py", ("--help",)),
)
READ_NOT_RUN = ("scripts/reconcile.sh", "scripts/aggregate_stats.py")


def test_every_operator_tool_is_either_run_here_or_named_as_unrunnable():
    """The surface cannot go quiet. Every Python tool under deploy/scripts is on one of the two
    lists, so a tool added later is a failure here rather than a tool nobody reads."""
    on_a_list = {name for name, _ in RUNNABLE_TOOLS} | set(READ_NOT_RUN)
    tools = {"scripts/%s" % p.name for p in sorted((DEPLOY / "scripts").glob("*.py"))}
    assert tools and not tools - on_a_list, sorted(tools - on_a_list)


def test_what_a_tool_prints_when_it_is_run_states_what_it_does():
    """The tool is RUN and everything it writes to stdout and stderr is read. A --help string
    reaches an operator through argparse's own formatting rather than as the literal a rule can
    see, and a module docstring printed as a description is the plainest case of that."""
    hits = []
    for name, mode in RUNNABLE_TOOLS:
        hits += run_output_offences(DEPLOY / name, mode, root=ROOT, cwd=ROOT)
    assert not hits, (
        f"{len(hits)} operator tool(s) print the audit trail or a typographic dash:\n"
        + "\n".join(hits))


def test_what_a_tool_assembles_before_it_prints_it_states_what_it_does():
    """The lines a PASSING run does not print, and the lines of a tool that cannot run here at all.
    A failure appended to a list and joined at the end, and a status detail held in a variable and
    handed to the writer of the document the serve screen shows, both reach an operator; neither is
    a literal standing inside an output call, which is the only place the rule above looks."""
    files = [DEPLOY / name for name, _ in RUNNABLE_TOOLS] + [DEPLOY / name
                                                             for name in READ_NOT_RUN]
    hits = assembled_output_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} assembled operator line(s) carry the audit trail or a typographic dash:\n"
        + "\n".join(hits))


def test_a_line_assembled_out_of_sight_is_still_read(tmp_path):
    """Both halves of the gap, planted. A literal appended to a list that is joined into a print,
    and a shell literal handed to the status writer across several lines."""
    listed = tmp_path / "tool.py"
    listed.write_text(
        "def main():\n"
        "    failures = []\n"
        '    failures.append("FAIL: the gateway var still trips a guard (C33 wanted a default)")\n'
        '    print("\\n".join(failures))\n', encoding="utf-8")
    hits = assembled_output_offences([listed])
    assert hits and "work-item identifier" in hits[0], (
        "a failure line appended to a list went unread: %s" % (hits,))
    written = tmp_path / "tool.sh"
    written.write_text(
        'write_status() { printf %s "$6" > "$1"; }\n'
        'write_status "failed" "" "" "" "" \\\n'
        '"rebuild FAILED; the previous build is still being served.\n'
        'A kernel kill CANNOT BE RULED OUT (incident 2026-08-15: five OOM-killed builds)."\n',
        encoding="utf-8")
    hits = assembled_output_offences([written])
    assert hits and "dated note" in hits[0], (
        "a status detail spanning several lines went unread: %s" % (hits,))
    clean = tmp_path / "clean.sh"
    clean.write_text(
        'write_status() { printf %s "$6" > "$1"; }\n'
        'write_status "failed" "" "" "" "" \\\n'
        '"rebuild FAILED; the previous build is still being served.\n'
        'A kernel out-of-memory kill cannot be excluded from this failure."\n', encoding="utf-8")
    assert not assembled_output_offences([clean]), "a plain status detail was flagged"


def test_every_python_file_in_a_swept_class_parses():
    """A scanner that cannot read a file reports it clean. Half this extractor is the syntax tree,
    so a module ast.parse refuses is swept for its # comments and NOT for its docstrings, and the
    class still reads zero. Python's own loader is more forgiving than ast.parse (a byte-order mark
    is the case that made this real), so the two must be held to agree here."""
    broken = []
    for producer in SURFACES.values():
        for path in producer():
            if path.suffix.lower() != ".py":
                continue
            try:
                ast.parse(source_text(path))
            except SyntaxError as exc:
                broken.append("%s: %s" % (path.relative_to(ROOT), exc))
    assert not broken, (
        "the syntax-tree half of the extractor cannot read these, so their docstrings are swept by "
        "nothing:\n" + "\n".join(sorted(set(broken))))


def test_a_byte_order_mark_does_not_hide_a_module_from_the_extractor(tmp_path):
    """A module carrying a byte-order mark imports and its tests run, because Python's own loader
    strips it. ast.parse does not, so the docstring half of the extractor saw nothing and the class
    reported clean; the # comments in the same file were read the whole time, which is what made it
    invisible rather than obviously broken."""
    f = tmp_path / "marked.py"
    f.write_bytes(b'\xef\xbb\xbf"""The owner ruling of 2026-08-18."""\n# a plain comment\n')
    with pytest.raises(SyntaxError):
        ast.parse(f.read_text(encoding="utf-8"))
    ast.parse(source_text(f))
    hits = offences([f], cite_contract=True)
    assert hits and "dated note" in hits[0], hits


def test_the_messages_a_failure_prints_carry_no_audit_trail():
    """An assertion message and a skip reason are what a reader of a red run is handed, so they are
    held to the audit trail the way a comment is: not who decided, when, or under which work item,
    wave, round or lane. Their SEMANTICS are untouched, because the message is what says which
    invariant broke; and the em and en dash go, because a reason is printed on a terminal where the
    glyph is not always legible. A message may still cite the contract a pin traces itself by."""
    files = [p for p in deploy_tree() + gateway_tree() if "tests" in p.parts]
    hits = message_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} assertion message(s) or skip reason(s) in the deploy and gateway suites carry "
        "the audit trail or a typographic dash:\n" + "\n".join(hits))


def test_a_message_keeps_its_semantics_and_loses_its_audit_trail(tmp_path):
    """What a message may say and what it may not. The finding stays; the provenance goes; the dash
    goes because a reason is printed on a terminal; and a dash the message is NAMING stays, because
    there it is the data the assertion is about."""
    caught = tmp_path / "caught.py"
    caught.write_text(
        'import pytest\n\n\ndef test_a():\n'
        '    assert 1, "the C18 cache flag reached the engine (owner round 2)"\n\n\n'
        '@pytest.mark.skipif(True, reason="dev-box-only real-corpus pins - see the UX6 wave")\n'
        'def test_b():\n    pass\n', encoding="utf-8")
    hits = message_offences([caught])
    assert len(hits) == 2, hits
    assert "work-item identifier" in hits[0] and "decision-owner language" in hits[0], hits[0]
    assert "wave identifier" in hits[1], hits[1]
    kept = tmp_path / "kept.py"
    kept.write_text(
        'import pytest\n\n\ndef test_a():\n'
        '    assert 1, "the cache flag reached the engine; it must stay non-incremental"\n\n\n'
        '@pytest.mark.skipif(True, reason="dev-box-only real-corpus pins")\n'
        'def test_b():\n    pass\n\n\ndef test_c():\n'
        '    assert 1, "a note carrying an `\u2014` explanation must be elided"\n',
        encoding="utf-8")
    assert not message_offences([kept]), message_offences([kept])
    dashed = tmp_path / "dashed.py"
    dashed.write_text('def test_a():\n    assert 1, "the strip is missing \u2014 this is not the hub"\n',
                      encoding="utf-8")
    hits = message_offences([dashed])
    assert hits and "an em or en dash" in hits[0], hits
    # The dash that stands BETWEEN two quoted runs is the message's own punctuation, not the data
    # it is naming, and the run it is read against opens and closes on the same mark.
    between = tmp_path / "between.py"
    between.write_text(
        'def test_a():\n'
        '    assert 1, "Caddy must use `handle /gateway/*` \u2014 `handle_path` strips the prefix"\n',
        encoding="utf-8")
    hits = message_offences([between])
    assert hits and "an em or en dash" in hits[0], (
        "a dash between two quoted runs was read as though it stood inside one: %s" % (hits,))


def test_a_skip_reason_held_in_a_constant_is_still_read(tmp_path):
    """A reason is often bound to a module constant and used as reason=NAME, because two markers
    share it. An extractor that reads only literals sees nothing there, and the class reports clean
    over a reason no rule ever looked at."""
    f = tmp_path / "held.py"
    f.write_text('import pytest\n\n'
                 'REASON = "designed topology; pinned from the UX6 wave"\n\n\n'
                 '@pytest.mark.skipif(True, reason=REASON)\n'
                 'def test_a():\n    pass\n', encoding="utf-8")
    hits = message_offences([f])
    assert hits and "wave identifier" in hits[0], hits
