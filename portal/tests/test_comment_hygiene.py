"""A comment on a shipped surface states a constraint; git carries the provenance.

Every byte of a comment in portal/*.html and portal/src/*.js is downloaded by every visitor, so
the comments the portal ships are part of the product. This module holds the house rule over them:
a comment may state what must hold and why it would break otherwise, an invariant another file
depends on, a bare pointer to the pin that holds it, or a licence/attribution obligation. It may
not carry design history, decision provenance, work-item identifiers, dates, placeholders,
commented-out code, or the name of a contract document.

The same rule reaches the source that WRITES shipped bytes (engine/extract/_pages.py, which is a
trigger path of this workflow for exactly that reason) and the generators and guard tests under
portal/. Test files keep their pin semantics and may cite a contract path, because that is how a
pin is traced; they are held to the rest of the rule exactly as the shipped surfaces are.

WHAT THE EXTRACTOR MUST SEE, because a scanner that cannot see an offence reports the surface
clean: a comment that TRAILS code on the same line, a // comment inside a page's inline <script>
(which on add-survey.html is the larger half of the page's commentary), a CSS comment inside a
<style> block, a # comment in a shell script, a YAML document, a systemd unit or a Caddyfile, and
a Python docstring, read through the AST. The unit tests at the foot of this module hold each of
those, and hold every comment counted exactly once.

THIS FILE IS EXCLUDED FROM ITS OWN SWEEP, by basename, because the vocabulary it forbids has to be
written down somewhere to be forbidden. The engine and deploy twins carry the same exclusion for
the same reason, and deploy/tests holds the three copies of the shared block equal.

Fails if: any comment on a covered surface breaks the rule, OR a shipped document carries more
comment bytes than its cap, OR the extractor stops seeing comments on a surface class at all (a
scanner that reads nothing must not report PASS over it).
"""
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent      # portal/
ROOT = PORTAL.parent                                 # repo root

SELF = "test_comment_hygiene.py"


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
# what is read is a CLOSED LIST of finite verbs, none of which can open an English sentence. The
# list is a floor rather than a grammar: it holds the verbs this tree's prose actually uses this
# way, and a verb it does not name is a site this rule will not find.
SUBJECTLESS_SENTENCE = re.compile(
    r"(?<![A-Z0-9])[.!?]\s+("
    r"adds|stands|splits|inverts|makes|made|moves|moved|bumped|broadened|retargeted|routes|"
    r"carries|invokes|keeps|holds|removes|replaces|extends|narrows|widens|closes|fixes|"
    r"introduces|retires|supersedes|renames|drops|folds|lifts|raises|lowers|gives|takes|"
    r"turns|puts|sets|reads|writes|runs|leaves|brings|sends|pins|gates|blocks|allows)\b")
# The same cut at the other end of the sentence: where what a bracketed aside was ABOUT is taken
# away, the copula is left with nothing after it ("the sole real-git workflow (curator-e2e) was.").
# A pronoun subject makes that ordinary English ("git carries what was."), so the shape is anchored
# to the bracket that closes hard in front of the verb.
ORPHANED_COPULA = re.compile(r"[)\]][ \t]+(?:was|were|is|are|be|been|being)[ \t]*[.;](?:\s|\Z)")
# Two sentence marks standing together, where the cut took the token that stood between them
# ("must not both build,;"). A decimal and an ellipsis carry a digit or a further dot after the
# mark, so neither is this. The second class carries the COLON: where the cut takes the token
# that introduced a clause, the comma of the phrase in front of it is left hard against that
# colon ("a production regression,:"), and a class of [.,;] misses it by one character in the
# same way a rule reading a line of exactly one bracket missed ")." by one. A group that closed
# before the cut token carries the same scar with its own full stop in between ("anyway).:").
MARKS_TOGETHER = re.compile(r"[\w)\]][,;][.,;:](?![.\d])|[)\]]\.[:;](?![.\d])")
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
# guarantee trades the leak-clean-by-construction shape for"). The verbs are the same floor the
# sentence-opening rule reads, and a verb the list does not name is a site this rule will not find.
MIDSENTENCE_SUBJECT = re.compile(
    r"(?<![\w-])is[ \t]+the[ \t]+[\w-]+[ \t]+"
    r"(?:trades|adds|carries|keeps|holds|removes|replaces|extends|narrows|widens|closes|fixes|"
    r"drops|folds|gives|takes|turns|puts|sets|reads|writes|runs|leaves|brings|sends|pins|gates|"
    r"blocks|allows|names|says|shows|proves|means|needs|uses|treats|counts|marks|stands|splits|"
    r"inverts|makes|moves|routes|invokes|introduces|retires|supersedes|renames|lifts|raises|"
    r"lowers)(?![\w-])")
# A BRACKET THAT POINTS AT NOTHING. Where the cut takes the record a bracketed aside cited, the
# label that introduced it is left alone between the brackets ("(design)", "(note)"): it names no
# record and states no constraint, so the aside is restated as the constraint it stood for or it
# goes with its bracket.
BARE_LABEL = re.compile(r"\((?:design|note|see|ref|cf)\)")
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
            if MARKS_TOGETHER.search(unquoted(flat)):
                said.append("two sentence marks with nothing between them")
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


def listing(*globs):
    out = []
    for base, pattern in globs:
        out += [p for p in sorted(base.glob(pattern)) if p.is_file() and p.name != SELF]
    return out


# The shipped documents, and the cap each one's comments may occupy. A cap is a measurement with
# modest headroom, not an aspiration: it is what stops the sweep being undone one paragraph at a
# time. Every cap counts a page's inline scripts, which is where most of a page's commentary is.
# The corresponding cap for the pages the engine emits lives in the engine twin.
SHIPPED_HTML_CAPS = {
    "index.html": 5_800,
    "about.html": 6_300,
    "add-survey.html": 20_100,
    "releases.html": 4_800,
    "brand.html": 2_400,
    "404.html": 900,
}
SHIPPED_JS_CAP = 122_000
# The page scripts a visitor also downloads: the four at the top of portal/ and the coastline this
# repository generates into vendor/. They are not modules under src/, so a glob anchored there read
# none of them and none of their bytes counted anywhere. Third-party libraries under vendor/ are
# somebody else's prose and stay out. The length clause reads the modules and the pages; these
# scripts are held by the byte cap and by the vocabulary.
SHIPPED_PAGE_SCRIPT_CAP = 9_600

# THE LENGTH CLAUSE, on the shipped tier alone. A long constraint is stated in one or two sentences
# and anything longer belongs in docs/, so a comment a visitor downloads is at most two sentences
# and at most this many bytes. The pointer that carries a reader to the moved prose is not one of
# the two: it is the pointer, not the constraint.
COMMENT_CAP = 320
COMMENT_SENTENCES = 2
# A pointer names the page and, on the two documents whose stylesheets are pointed at as a whole,
# the section of that page it stands for.
DOCS_POINTER = re.compile(r"\s*See docs: portal internals, [\w.\-]+(?:, [\w \-,]+?)?\.\s*$")
STYLE_POINTER = re.compile(r"See docs: portal internals, ([\w.\-]+), ([\w \-,]+?)\.")
# A licence or attribution OBLIGATION is exempt. Its wording is the obligation, and shortening it
# would change what the portal promises rather than where the reasoning lives.
OBLIGATION = re.compile(r"\bcopyright\b|SPDX|CC-BY|Creative Commons|\bNOTICE\b|licence term"
                        r"|attribution (?:obligation|term|requirement|statement)|basemap credit",
                        re.I)
# The enumerated exceptions, at most ten, each naming the file and the reason its comment may run
# long. Empty on purpose: the sweep left nothing that needed one, and an entry here is a claim that
# a constraint could not be stated in two sentences with its reasoning moved.
LENGTH_EXCEPTIONS = ()
# A sentence ends on a full stop that is not part of an abbreviation. The list is short because the
# shipped prose is short; a false split only ever makes this rule stricter.
_ABBREVIATION = re.compile(r"(?:\b(?:e\.g|i\.e|cf|etc|vs|approx|Fig|Sec|no|pp|al)\.|\b[A-Z]\.)$")


def sentences(text):
    """The sentences of one comment, as a reader counts them."""
    said, buf = [], ""
    for chunk in re.split(r"(?<=[.!?])(\s+)", text):
        if chunk and not chunk.strip():
            if _ABBREVIATION.search(buf.strip()):
                buf += chunk
                continue
            said.append(buf)
            buf = ""
            continue
        buf += chunk
    if buf.strip():
        said.append(buf)
    return [s.strip() for s in said if s.strip()]


def comment_blocks(path, text):
    """(line number, joined text) for each RUN of comments a reader reads as one. A block of //
    lines is one comment to a reader and must be measured as one; measured line by line, a fifteen
    line block reads as fifteen comments and no cap can bite."""
    scan = js_comments if path.suffix.lower() == ".js" else html_comments
    out = []
    for off, body in scan(text):
        head = text.rfind("\n", 0, off) + 1
        own_line = not text[head:off].strip()
        if (out and own_line and out[-1]["own"]
                and text[out[-1]["end"]:head].strip() == ""
                and text.count("\n", out[-1]["end"], head) == 1):
            out[-1]["end"] = off + len(body)
            out[-1]["bodies"].append(body)
        else:
            out.append({"start": off, "end": off + len(body), "bodies": [body], "own": own_line})
    return [(text.count("\n", 0, b["start"]) + 1,
             "\n".join(b["bodies"])) for b in out]


def over_length(path, text, root=None):
    """Every comment on a shipped surface that runs past the clause, as report lines."""
    over = []
    for lineno, block in comment_blocks(path, text):
        prose = " ".join(bare(block).split())
        if not prose or OBLIGATION.search(prose):
            continue
        if any(f == path.name and prose.startswith(head) for f, head, _ in LENGTH_EXCEPTIONS):
            continue
        size = len(block.encode("utf-8"))
        said = len(sentences(DOCS_POINTER.sub("", prose)))
        if size > COMMENT_CAP or said > COMMENT_SENTENCES:
            where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
            over.append("%s:%d: %d bytes, %d sentence(s): %s"
                        % (where, lineno, size, said, prose[:100]))
    return over


def shipped_html():
    return [PORTAL / name for name in SHIPPED_HTML_CAPS]


def shipped_js():
    return listing((PORTAL / "src", "*.js"))


AUTHORED_VENDOR_SCRIPTS = ("au-outline.js",)


def shipped_page_scripts():
    """The scripts a page loads by name rather than as a module of src/. au-outline.js is generated
    by engine/extract/_au_outline_build.py, so its comments are the generator's template."""
    return (listing((PORTAL, "*.js"))
            + [PORTAL / "vendor" / name for name in AUTHORED_VENDOR_SCRIPTS])


def emitter():
    return [ROOT / "engine" / "extract" / "_pages.py"]


def generators():
    return listing((PORTAL / "tools", "*.py"), (PORTAL / "tools", "*.js"))


def guard_tests():
    """Every module under portal/tests, subdirectories included. A one-level glob leaves a fixture
    builder outside every class, and a comment is no cleaner for sitting one directory down."""
    return [p for p in sorted(PORTAL.joinpath("tests").rglob("*"))
            if p.is_file() and p.suffix.lower() in (".py", ".js")
            and p.name != SELF and "__pycache__" not in p.parts]


CONFIG_SUFFIXES = (".toml", ".txt", ".cfg", ".yaml", ".yml")


def config_files():
    """The portal's own declared configuration, which gen_config.py reads to write the served
    config.js. It carries prose like any module does and sat outside every class."""
    return [p for p in sorted(PORTAL.glob("*"))
            if p.is_file() and p.suffix.lower() in CONFIG_SUFFIXES]


SURFACES = {
    "shipped HTML": shipped_html,
    "shipped JS": shipped_js,
    "the shipped page scripts": shipped_page_scripts,
    "the page emitter": emitter,
    "the generators": generators,
    "the guard tests": guard_tests,
    "the portal configuration": config_files,
}


# ---------------------------------------------------------------------------
# The rule, per surface class.
# ---------------------------------------------------------------------------
def test_shipped_html_comments_state_constraints_only():
    hits = offences(shipped_html(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the shipped HTML carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_shipped_page_script_comments_state_constraints_only():
    hits = offences(shipped_page_scripts(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the page scripts every visitor downloads carry provenance "
        "rather than a constraint:\n" + "\n".join(hits)
    )


def test_shipped_page_scripts_stay_under_their_comment_cap():
    got = sum(comment_bytes(p) for p in shipped_page_scripts())
    assert got <= SHIPPED_PAGE_SCRIPT_CAP, (
        f"the page scripts carry {got:,} bytes of comments, cap {SHIPPED_PAGE_SCRIPT_CAP:,}; "
        "every one of them is downloaded by a visitor"
    )


def test_the_vendored_third_party_libraries_are_left_alone():
    """vendor/ holds two kinds of file: what this repository generates and what it copies in.
    Only the first is ours to sweep, and naming it by file keeps the second out."""
    ours = {p.name for p in shipped_page_scripts() if p.parent.name == "vendor"}
    assert ours == set(AUTHORED_VENDOR_SCRIPTS), ours
    third_party = [p.name for p in sorted((PORTAL / "vendor").glob("*.js"))
                   if p.name not in AUTHORED_VENDOR_SCRIPTS]
    assert third_party, "vendor/ carries no third-party library, so this exclusion would be silent"


def test_shipped_js_comments_state_constraints_only():
    hits = offences(shipped_js(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in portal/src/*.js carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_portal_configuration_comments_state_constraints_only():
    hits = offences(config_files(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the portal's configuration carry provenance rather than a "
        "constraint:\n" + "\n".join(hits)
    )


def test_page_emitter_comments_state_constraints_only():
    hits = offences(emitter(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the page emitter carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_generator_comments_state_constraints_only():
    hits = offences(generators(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in portal/tools carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_guard_test_comments_state_constraints_only():
    hits = offences(guard_tests(), cite_contract=True, root=ROOT)
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


def test_a_shipped_comment_is_two_sentences_long_at_most():
    """H1's length clause, on the tier every visitor downloads: a long constraint is stated in one or
    two sentences, and anything longer lives in docs/docs/reference/portal-internals.md with the
    comment carrying the constraint and the bare pointer to it. It reads the page scripts a visitor
    loads by name as well as the pages and the modules: a script is not shorter for sitting at the top
    of portal/ rather than under src/, and one of them carries the longest comment the portal ships.
    The exemptions are a licence or attribution obligation, whose wording IS the obligation, and the
    enumerated list above."""
    over = []
    for path in shipped_html() + shipped_js() + shipped_page_scripts():
        over += over_length(path, source_text(path), root=ROOT)
    assert not over, (
        f"{len(over)} comment(s) on the shipped tier run past the length clause "
        f"({COMMENT_SENTENCES} sentences, {COMMENT_CAP} bytes); move the reasoning to "
        "docs/docs/reference/portal-internals.md and leave the constraint with a pointer:\n"
        + "\n".join(over)
    )


def test_a_licence_obligation_may_run_past_the_length_clause(tmp_path):
    """The wording of a licence or attribution obligation IS the obligation, so shortening it changes
    what the portal promises rather than where the reasoning lives. Ordinary prose of the same length
    is not exempt."""
    obligation = ("// The basemap credit is a licence term and travels with the layer that draws it, "
                  "because only that layer knows which provider to name. It is rendered on every map "
                  "surface the portal ships, at the size the provider's own terms ask for, on every "
                  "viewport width, and the 240px cap keeps the opened text clear of the legend at "
                  "560px of map, which is the narrowest map the layout allows.\n")
    plain = obligation.replace("The basemap credit is a licence term and", "The credit line").replace(
        "the provider's own terms ask for", "the design asks for")
    f = tmp_path / "obligation.js"
    f.write_text(obligation + "var a = 1;\n", encoding="utf-8")
    assert not over_length(f, f.read_text(encoding="utf-8")), "a licence obligation was cut short"
    g = tmp_path / "plain.js"
    g.write_text(plain + "var a = 1;\n", encoding="utf-8")
    assert over_length(g, g.read_text(encoding="utf-8")), (
        "prose of the same length that states no obligation was excused"
    )


def test_a_run_of_line_comments_is_measured_as_one_comment(tmp_path):
    """A block of // lines is ONE comment to the reader. Measured line by line, a fifteen-line block
    reads as fifteen comments and no length clause can ever bite."""
    f = tmp_path / "run.js"
    f.write_text("// one line.\n// two lines.\n// three lines.\nvar a = 1;\n// apart.\n", encoding="utf-8")
    found = comment_blocks(f, f.read_text(encoding="utf-8"))
    assert [n for n, _ in found] == [1, 5], found
    assert found[0][1] == "// one line.\n// two lines.\n// three lines."


def test_the_length_clause_carries_at_most_ten_enumerated_exceptions():
    """An exception is a claim that a constraint cannot be stated in two sentences with its
    reasoning moved. Ten is the ceiling, and each entry names its file and its reason."""
    assert len(LENGTH_EXCEPTIONS) <= 10, LENGTH_EXCEPTIONS
    for entry in LENGTH_EXCEPTIONS:
        name, head, why = entry
        assert name in SHIPPED_HTML_CAPS or (PORTAL / "src" / name).exists(), name
        assert head and why, entry


def test_the_docs_page_the_pointers_name_exists_and_carries_a_section_per_file():
    """A pointer to a page that does not carry the file's section is a dead pointer."""
    page = ROOT / "docs" / "docs" / "reference" / "portal-internals.md"
    assert page.exists(), f"{page} is missing and every pointer on the shipped tier is dead"
    text = page.read_text(encoding="utf-8")
    missing = []
    for path in shipped_html() + shipped_js() + shipped_page_scripts():
        body = source_text(path)
        if DOCS_POINTER.search(" ".join(bare(body).split()) + " ") or f"portal internals, {path.name}" in body:
            rel = str(path.relative_to(ROOT))
            if f"## {rel}" not in text:
                missing.append(rel)
    assert not missing, (
        "the shipped tier points at sections this page does not carry:\n" + "\n".join(missing))


# A pointer may name a docs/ page and a section on it. The page is resolved by slug under
# docs/docs, so a pointer at a page that does not exist fails here rather than in a reader's hands.
DOCS_PAGE_POINTER = re.compile(r"\bdocs:\s*([a-z][a-z0-9]*(?:[ -][a-z0-9]+)*)\s*,", re.I)
POINTER_SUFFIXES = (".py", ".js", ".html", ".css", ".sh", ".yaml", ".yml", ".toml", ".txt",
                    ".cfg", ".service", ".timer", ".md")
SKIP_DIRS = {".git", "node_modules", "site", "__pycache__", ".venv"}


def commented_tree():
    """Every file in the repository the extractor reads a comment in. The pointer rule is repo-wide
    because a dead pointer is dead wherever it is written, and the three sweeps between them do not
    cover the whole tree."""
    out = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        if path.suffix.lower() in POINTER_SUFFIXES or path.name in HASH_NAMES:
            out.append(path)
    return out


REPO_PATH_IN_PROSE = re.compile(
    r"(?<![\w/.-])((?:portal|engine|gateway|deploy|contract|docs|maintainer|schema|\.github)"
    r"/[A-Za-z0-9_./-]*\.(?:py|js|md|html|css|ya?ml|json|toml|sh|txt|service|timer|cfg))"
    r"(?![\w.-])")


def test_every_repository_path_a_comment_names_exists():
    """A comment may point at a file in this repository, and a tag inside such a path is excused
    BECAUSE the path resolves. A path that does not resolve is the same dead reference the citation
    rule removes, and it would also be excusing a tag for nothing."""
    dangling, resolved = [], 0
    for path in commented_tree():
        if path.name == SELF or "vendored_validation" in path.parts:
            continue
        try:
            text = source_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, comment in comments(path, text):
            for match in REPO_PATH_IN_PROSE.finditer(bare(comment)):
                named = match.group(1)
                if "*" in named or "<" in named or "..." in named:
                    continue
                if (ROOT / named).exists():
                    resolved += 1
                else:
                    dangling.append("%s:%d: %s" % (path.relative_to(ROOT), lineno, named))
    assert resolved, "no repository path resolved, so this test would pass over nothing"
    assert not dangling, (
        f"{len(dangling)} comment(s) point at a repository path that does not exist:\n"
        + "\n".join(sorted(set(dangling))))


def test_every_document_a_comment_names_is_in_this_repository():
    """The bare form of the same rule. A comment that cites `SOMETHING.md` with no directory in
    front of it points a reader at a document, and a reader of this repository resolves it by
    opening the file. When the tree carries no such file the reference is unresolvable wherever it
    is written, and the constraint the citation stood in for was never stated."""
    known = {path.name for path in ROOT.rglob("*.md") if not SKIP_DIRS & set(path.parts)}
    dangling, resolved = [], 0
    for path in commented_tree():
        if path.name == SELF or "vendored_validation" in path.parts:
            continue
        try:
            text = source_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        commentary = "\n".join(body for _, body in comments(path, text))
        for lineno, comment in comment_runs(path, text):
            for named in documents_named(flattened(bare(comment))):
                if named in known:
                    resolved += 1
                elif text.count(named) > commentary.count(named):
                    resolved += 1
                else:
                    dangling.append("%s:%d: %s" % (path.relative_to(ROOT), lineno, named))
    assert resolved, "no document name resolved, so this test would pass over nothing"
    assert not dangling, (
        f"{len(dangling)} comment(s) cite a document this repository does not carry:\n"
        + "\n".join(sorted(set(dangling))))


def test_a_bare_document_name_is_read_and_its_three_exemptions_hold(tmp_path):
    """The token, and what is not one: a contract document a pin traces itself by (it lives outside
    the checkout by ruling), a name carrying a directory (the path rule reads that one), and a
    document this repository does carry."""
    assert documents_named("the model (AUSMT-DATA-CITATION-MODEL.md section 9)") \
        == ["AUSMT-DATA-CITATION-MODEL.md"]
    assert documents_named("pinned by LANE-CONTRACT-PAGE-HIERARCHY.md section 2") == []
    assert documents_named("see docs/docs/developer/data-files.md") == []
    assert documents_named("README.md is in the tree") == ["README.md"]


def test_every_docs_pointer_names_a_page_that_exists():
    """A comment may point only at something a reader of this repository can open. A pointer that
    names a docs/ page resolves to a file under docs/docs; a dangling one is exactly the
    unresolvable reference the citation rule exists to stop."""
    pages = {p.stem: p for p in (ROOT / "docs" / "docs").rglob("*.md")}
    assert pages, "docs/docs carries no pages, so this resolution would pass over nothing"
    dangling, resolved = [], 0
    for path in commented_tree():
        if path.name == SELF or path.is_relative_to(ROOT / "docs"):
            continue
        try:
            text = source_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        if "docs:" not in text:
            continue
        for lineno, comment in comments(path, text):
            for match in DOCS_PAGE_POINTER.finditer(bare(comment)):
                slug = re.sub(r"[ ]+", "-", match.group(1).strip().lower())
                if slug in pages:
                    resolved += 1
                else:
                    dangling.append("%s:%d: docs: %s" % (path.relative_to(ROOT), lineno, match.group(1)))
    assert resolved, "no docs pointer resolved, so this test would pass over nothing"
    assert not dangling, (
        f"{len(dangling)} comment pointer(s) name a docs/ page that does not exist under "
        "docs/docs:\n" + "\n".join(dangling))


def test_every_stylesheet_pointer_names_a_section_the_docs_page_carries():
    """A stylesheet is pointed at one section at a time, so each pointer must find its section on
    the page. A pointer at a section that does not exist is the dead reference the rule forbids."""
    page = ROOT / "docs" / "docs" / "reference" / "portal-internals.md"
    text = page.read_text(encoding="utf-8")
    missing, found = [], 0
    for path in shipped_html():
        body = source_text(path)
        for match in STYLE_POINTER.finditer(body):
            found += 1
            if f"#### {match.group(2)}" not in text:
                missing.append("%s: %s, %s" % (path.name, match.group(1), match.group(2)))
    assert found, "no stylesheet pointer was read, so this test would pass over nothing"
    assert not missing, (
        "the shipped stylesheets point at sections this page does not carry:\n" + "\n".join(missing))


def test_shipped_scripts_stay_under_their_comment_cap():
    got = sum(comment_bytes(p) for p in shipped_js())
    assert got <= SHIPPED_JS_CAP, (
        f"portal/src/*.js carries {got:,} bytes of comments, cap {SHIPPED_JS_CAP:,}; "
        "the scripts are served to every visitor"
    )


# ---------------------------------------------------------------------------
# Non-vacuity: the scanner must be reading something.
# ---------------------------------------------------------------------------
def test_every_surface_class_is_actually_read():
    empty = []
    for label, files in SURFACES.items():
        found = files()
        assert found, f"{label}: no files matched, so this sweep would pass over nothing"
        seen = sum(len(comments(p, source_text(p))) for p in found)
        if seen == 0:
            empty.append(f"{label}: {len(found)} file(s), zero comments extracted")
    assert not empty, "the extractor read no comments at all on:\n" + "\n".join(empty)


def test_the_inline_scripts_of_a_shipped_page_are_inside_the_sweep():
    """add-survey.html keeps its logic in an inline <script>, so a scanner that reads only
    <!-- --> reports the page on a fraction of its commentary and its cap measures a fraction."""
    page = PORTAL / "add-survey.html"
    text = page.read_text(encoding="utf-8")
    markup = sum(len(c.encode("utf-8")) for _, c in comments(page, text) if c.startswith("<!--"))
    assert comment_bytes(page) > 2 * markup, (
        "the shipped-page extractor is reading little more than the markup comments, so the "
        "inline scripts are outside the sweep"
    )


# ---------------------------------------------------------------------------
# The extractor, held to what it must see.
# ---------------------------------------------------------------------------
def test_a_comment_trailing_code_is_extracted(tmp_path):
    cases = {
        "trail.js": ("var a = 1; // the trailing note\n", "// the trailing note"),
        "trail.py": ("a = 1  # the trailing note\n", "# the trailing note"),
        "trail.sh": ("run_it --now   # the trailing note\n", "# the trailing note"),
        "trail.yaml": ("key: value  # the trailing note\n", "# the trailing note"),
    }
    for name, (body, want) in cases.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        found = [c for _, c in comments(f, body)]
        assert found == [want], f"{name}: expected {want!r}, got {found!r}"


def test_an_inline_script_and_style_comment_are_extracted(tmp_path):
    f = tmp_path / "page.html"
    f.write_text('<!-- markup note -->\n<style>a{color:red} /* style note */</style>\n'
                 '<script>\nvar a = 1; // script note\n/* block note */\n</script>\n',
                 encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ["<!-- markup note -->", "/* style note */", "// script note",
                     "/* block note */"], found


def test_a_json_ld_block_is_not_read_as_script(tmp_path):
    f = tmp_path / "ld.html"
    f.write_text('<script type="application/ld+json">\n'
                 '{"url": "https://example.invalid/x", "sameAs": "https://example.invalid/y"}\n'
                 '</script>\n', encoding="utf-8")
    assert comments(f, f.read_text(encoding="utf-8")) == [], (
        "the // of a URL inside a JSON-LD block was read as a comment"
    )


def test_a_slash_inside_a_string_a_template_or_a_regex_is_not_a_comment(tmp_path):
    f = tmp_path / "slashes.js"
    f.write_text('var u = "https://example.invalid/x";\n'
                 'var t = `<a href="//host/p">/* not a comment */</a>`;\n'
                 'var r = /https?:\\/\\//;\n'
                 'if (r.test(u)) { u = u.replace(/\\/\\//, "/"); }\n'
                 '// the only comment\n', encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ["// the only comment"], found


def test_a_hash_inside_an_expansion_a_quote_or_a_heredoc_is_not_a_comment(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text('base="${name#prefix}"\n'
                 'printf "%s\\n" "a # not a comment"\n'
                 "cat > /tmp/out <<'EOF'\n# written into the file, not a comment\nEOF\n"
                 "# the only comment\n", encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ["# the only comment"], found


def test_a_heredoc_that_feeds_an_interpreter_is_scanned_as_that_language(tmp_path):
    """A heredoc body is DATA the script writes, EXCEPT where it is the source an interpreter on the
    same line is about to run. Then it is code on a surface this sweep covers, and its comments are
    comments. These scripts reach their interpreter through a probed variable, so the variable is
    resolved from the file: both kinds are held here."""
    f = tmp_path / "both.sh"
    f.write_text(
        "cat > /tmp/out <<'EOF'\n"
        "# written into the file, not a comment\n"
        "EOF\n"
        "python3 - <<'PYEOF'\n"
        "# the incident of 2026-08-15 is why this retries\n"
        "print(1)\n"
        "PYEOF\n"
        'PY=""\n'
        "for _cand in python3 python; do\n"
        '  PY="$_cand"\n'
        "done\n"
        '"$PY" - <<\'PYEOF\'\n'
        "# the owner ruled the retry count\n"
        "print(2)\n"
        "PYEOF\n", encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ["# the incident of 2026-08-15 is why this retries",
                     "# the owner ruled the retry count"], found
    hits = offences([f])
    assert len(hits) == 2, hits


def test_a_shebang_is_not_commentary(tmp_path):
    f = tmp_path / "tool.sh"
    f.write_text("#!/usr/bin/env bash\nset -eu\n", encoding="utf-8")
    assert comments(f, f.read_text(encoding="utf-8")) == []


def test_a_docstring_and_a_floating_string_are_both_commentary(tmp_path):
    """A triple-quoted paragraph in the middle of a function is a comment written with quotes.
    Reading only the four docstring positions leaves that as the way around the rule."""
    f = tmp_path / "mod.py"
    f.write_text('"""The module note."""\n\n\ndef f():\n    """The function note."""\n'
                 '    a = 1\n    """The floating note."""\n    return """served content"""\n',
                 encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ['"""The module note."""', '"""The function note."""',
                     '"""The floating note."""'], found


def test_a_comment_is_counted_once(tmp_path):
    """The two overlaps a per-syntax scan double-counts, each counted once here."""
    f = tmp_path / "overlap.js"
    f.write_text("/* a block\n// a line inside it\n*/\n// a glob such as contract/*.json\nvar a = 1;\n",
                 encoding="utf-8")
    found = comments(f, f.read_text(encoding="utf-8"))
    assert len(found) == 2, f"expected two comments, got {len(found)}: {found}"
    assert comment_bytes(f) == sum(len(c.encode('utf-8')) for _, c in found)


# ---------------------------------------------------------------------------
# The vocabulary, held to what it must catch and what it must leave alone.
# ---------------------------------------------------------------------------
def test_a_planted_comment_is_caught_in_every_comment_syntax(tmp_path):
    plants = {
        "planted.html": "<p>x</p>\n<!-- UX6 Wave B: the owner's ruling of 2026-08-19 -->\n",
        "planted.js": "var a = 1;\n// UX6 Wave B: the owner's ruling of 2026-08-19\n",
        "planted.css": "a{color:red}\n/* UX6 Wave B: the owner's ruling of 2026-08-19 */\n",
        "planted.py": "a = 1\n# UX6 Wave B: the owner's ruling of 2026-08-19\n",
        "planted.sh": "set -eu\n# UX6 Wave B: the owner's ruling of 2026-08-19\n",
        "planted.yaml": "key: value\n# UX6 Wave B: the owner's ruling of 2026-08-19\n",
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


def test_a_work_item_tag_is_caught_in_each_position_it_takes(tmp_path):
    plants = {
        "head.js": "// C18 the cache seam is here.\nvar a = 1;\n",
        "colon.js": "// The cache seam. C6/C46: the licence instrument rides with it.\nvar a = 1;\n",
        "paren.js": "// The licence instrument rides with the bytes (C46).\nvar a = 1;\n",
        "amend.js": "// The colour set is frozen by Amendment A1.\nvar a = 1;\n",
        "before.js": "// The B4 wave reshaped this panel.\nvar a = 1;\n",
    }
    for name, body in plants.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        hits = offences([f])
        assert hits and "work-item identifier" in hits[0], f"{name}: a work-item tag went unseen"


def test_the_work_item_rule_does_not_flag_ordinary_prose(tmp_path):
    f = tmp_path / "prose.css"
    f.write_text("/* IPv4 addresses are truncated to /24; WCAG AA (4.5:1) is the floor. */\na{color:red}\n",
                 encoding="utf-8")
    assert not offences([f]), "the work-item rule flagged ordinary prose"


def test_each_false_positive_names_its_meaning_and_is_caught_without_it(tmp_path):
    """One entry per meaning on the exemption list. The token standing beside the words that give
    it that meaning is clean; the SAME token in work-item position, without them, is caught."""
    cases = [
        ("S3: the object store the mirror writes to.",
         "S3 reshaped the download panel."),
        ("H1: the heading level a document carries once.",
         "H1 reshaped the download panel."),
        ("D65: the CIE illuminant the colour maths is computed under.",
         "D65 reshaped the download panel."),
        ("L2: the data level a processed product is served at.",
         "L2 reshaped the download panel."),
        ("The unpadded station ids render CP1L02 as L2 and CP1L05 as L15.",
         "L15 reshaped the download panel."),
        ("Q3: Release 2026-Q3 is the snapshot a citation names.",
         "Q3 reshaped the download panel."),
        ("CC0: a public domain dedication is not a licence with conditions.",
         "CC0 reshaped the download panel."),
        ("A01: the DATAID the dialect note carries.",
         "A01 reshaped the download panel."),
        ("The fixture's DATAID is A1 and its file name is not.",
         "A1 reshaped the download panel."),
        ("MD5: the digest the manifest carries beside the sha256.",
         "MD5 reshaped the download panel."),
        ("P95: the percentile the build budget is set against.",
         "P95 reshaped the download panel."),
        ("The quadrant walk is Zxy Q1 -> Q4 and Zyx Q3 -> Q2.",
         "Q1 reshaped the download panel."),
        ("The rotation maths is Z0(i) = R(theta) Z(i) R(theta) transposed.",
         "Z0 reshaped the download panel."),
        ("stations: S01, S02 are the two the fixture serves.",
         "S01, S02 reshaped the download panel."),
        ("station A1: the reference this survey record names.",
         "Amendment A1: the colour set is frozen."),
    ]
    # A context test without a word boundary opens on any word that CONTAINS one of its
    # alternatives, and a context test on a bare noun opens on the ordinary sense of that noun.
    # These are the two shapes that turn an exemption into a permanent blind spot.
    incidental = [
        "S3 PIN. If staging the restore tmp FAILS after the gateway is stopped, the run aborts.",
        "S3 round 2: the value is stored on disk before the swap.",
        "D-L1: label by the data LEVEL when identifies is present.",
        "L1 gate: the level a reader picks is not the one the file was written at.",
    ]
    for i, line in enumerate(incidental):
        f = tmp_path / f"incidental{i}.js"
        f.write_text(f"// {line}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([f])
        assert hits and "work-item identifier" in hits[0], (
            f"a work-item tag was excused by a word that merely CONTAINS its context: {line}"
        )
    for i, (clean, work_item) in enumerate(cases):
        ok = tmp_path / f"ok{i}.js"
        ok.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([ok]), f"the tag rule flagged a false positive: {clean}"
        bad = tmp_path / f"bad{i}.js"
        bad.write_text(f"// {work_item}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([bad])
        assert hits and "work-item identifier" in hits[0], (
            f"the same token in work-item position was excused: {work_item}"
        )


def test_a_licence_id_is_named_by_its_licence_anywhere_in_the_run(tmp_path):
    """The one exemption whose context is the whole run. A message about licensing names the
    licence and then uses the alias, and the alias regularly ends a sentence the word opened, so a
    window measured in characters cannot reach from one to the other. The token still has to be
    NAMED: the same alias in work-item position, in prose that says nothing about licensing, is
    still an audit trail."""
    far = ('def test_a():\n'
           '    assert 1, ("the metadata licence must be scoped explicitly: it is not the '
           'per-survey data licence, "\n'
           '               "and a harvester that conflates the two republishes restricted data '
           'under CC0")\n')
    f = tmp_path / "far.py"
    f.write_text(far, encoding="utf-8")
    assert not message_offences([f]), (
        "a licence id was read as a work item because the word licence stood outside the window")
    near = tmp_path / "near.py"
    near.write_text('def test_a():\n    assert 1, "CC0 reshaped the download panel"\n',
                    encoding="utf-8")
    hits = message_offences([near])
    assert hits and "work-item identifier" in hits[0], (
        "the alias in work-item position, in prose about nothing licensed, was excused")


def test_a_tag_is_a_tag_wherever_it_stands(tmp_path):
    """Position scoping was the last hole: a work item named mid-sentence, after a dash or inside a
    list is the same audit trail as one at the head of a comment, and the shipped tier was only
    clean because the sweep had already reached it."""
    cases = [
        "The panel was reshaped under C43 and the vocabulary froze with it.",
        "The two seams were split by D5-C, R1 in the same pass.",
        "Kept for A4 - the producer stayed disabled.",
        "The queue drains in the order C18 set.",
    ]
    for i, line in enumerate(cases):
        f = tmp_path / f"pos{i}.js"
        f.write_text(f"// {line}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([f])
        assert hits and "work-item identifier" in hits[0], (
            f"a work-item tag standing outside the old four positions was missed: {line}"
        )
    # A corpus id is DATA: two or more letters and then digits is a DATAID or a station id, which is
    # what this repository is about, and it is never a work item.
    for clean in ("The record keys on ST01 and MBI21 alike.",
                  "CP3B21 and RD18-053a are both real published ids.",
                  "station A1 is the reference this record names.",
                  "fixture G1 seeds the withheld arm."):
        f = tmp_path / "cleanpos.js"
        f.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([f]), f"the tag rule flagged a corpus id: {clean}"


def test_a_work_item_that_cites_a_clause_is_still_a_work_item(tmp_path):
    """A work item that cites a clause of the design it belongs to writes the clause after a dot,
    and the citation is the same audit trail as the work item alone. The LETTERS are what make it
    one: a comment that numbers its own list writes 1.1 and 2.3, which name nothing outside it."""
    for line in ("The four privileged intent files are a fixed enum (D9.1).",
                 "The rotation guard and the quadrant check (T1.1, T1.2) share a fixture.",
                 "A key note lives only in sqlite (D2.5), never in the git-bound tree."):
        f = tmp_path / "dotted.js"
        f.write_text(f"// {line}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([f])
        assert hits and "work-item identifier" in hits[0], f"a dotted work item was missed: {line}"
    for clean in ("The refusal order is 1.1 the charset, then 1.2 the inventory.",
                  "A rate limit of 2.5 seconds is the floor the agent honours.",
                  "The served payload is version 3.1 of the state document."):
        f = tmp_path / "enum.js"
        f.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([f]), f"an enumeration a comment defines itself was read as a tag: {clean}"


def test_an_apostrophe_inside_a_word_does_not_open_a_quoted_run(tmp_path):
    """The quoted-literal exemption excuses a tag the comment is QUOTING. Read with an apostrophe
    inside a word as its opening quote, the run reaches to the next apostrophe a sentence away and
    excuses every tag standing between the two."""
    f = tmp_path / "apostrophe.js"
    f.write_text("// The tripwire's own pins: two tests skip through one helper (the D3.1 validator\n"
                 "// seam was the first), and the tripwire's cross-check keeps both halves honest.\n"
                 "var a = 1;\n", encoding="utf-8")
    hits = offences([f])
    assert hits and "work-item identifier" in hits[0], hits
    quoted = tmp_path / "quoted.js"
    quoted.write_text("// The corpus already ships 'C5 [REMOTE].zip', so the encoder must hold.\n"
                      "var a = 1;\n", encoding="utf-8")
    assert not offences([quoted]), "a tag inside a genuine quoted literal was no longer excused"


def test_the_three_structural_exemptions_and_what_they_do_not_excuse(tmp_path):
    """A file name, a regex character class and a longer published id each carry the tag SHAPE in a
    place no reader reads as a work item. Each is held by the same token in work-item position."""
    cases = [
        ('The leg names the manifest row ("h5/gamma/G1.h5"), not the data base.',
         "G1 reshaped the download panel."),
        ("Site.id is sanitised on write (^[a-zA-Z0-9]*$), so the id must be recovered.",
         "Z0 reshaped the download panel."),
        ('The published handle is "RD18-084-S1-b" and the file follows it.',
         "S1 reshaped the download panel."),
        ("The design it implements is maintainer/C18-BuildCacheDesign.md.",
         "C18 reshaped the download panel."),
        ("Site.project is ^[a-zA-Z0-9-_]*$, so a space is rejected on write.",
         "Z0 reshaped the download panel."),
        ('The corpus-total "C18 cache [...]" line is what the tests pin.',
         '"C18" reshaped the download panel.'),
        ("The corpus already ships `C5 [REMOTE].zip`, so the encoder must hold.",
         "`C5` reshaped the download panel."),
    ]
    for i, (clean, work_item) in enumerate(cases):
        ok = tmp_path / f"struct{i}.js"
        ok.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([ok]), f"the tag rule flagged a structural false positive: {clean}"
        bad = tmp_path / f"structbad{i}.js"
        bad.write_text(f"// {work_item}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([bad])
        assert hits and "work-item identifier" in hits[0], (
            f"the same token in work-item position was excused: {work_item}"
        )


def test_a_round_of_work_is_provenance(tmp_path):
    """A round is the run of work a change belonged to, which is the same audit trail as a wave or
    a slice. So is the person or the sitting that settled the argument, and so is the verb that
    says a decision was blessed."""
    cases = [
        '"Go to place" was removed in UX feedback round 1.',
        "The frame is fixed (fix round 2).",
        "ROUND-2 RE-GATE: the record is read once.",
        "The panel was reshaped during the work round 3.",
        "The list is short: operator decision, and the long one was slow.",
        "Never published to PyPI (chief-architect ruling).",
        "The chief-architect design freezes the editor shape.",
        "The eight roles are held in the ratified order.",
        "The reading the reviewers ratify is the narrow one.",
        "This ratifies the narrow reading.",
        "Removed as redundant, an operator decision from the first live session.",
    ]
    for i, line in enumerate(cases):
        f = tmp_path / f"round{i}.js"
        f.write_text(f"// {line}\nvar a = 1;\n", encoding="utf-8")
        assert offences([f]), f"a round of work went unseen: {line}"
    for clean in ("The ramp rounds to two decimal places.",
                  "Round 3 of the retry loop is the last one the budget allows.",
                  "The operator sees the failure on the console.",
                  "SameSite=Strict means a cross-site form cannot send it even while a session is live.",
                  "A session cookie is never set."):
        f = tmp_path / "clean.js"
        f.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([f]), f"the round rule flagged ordinary prose: {clean}"


def test_the_id_exemption_tests_the_token_and_not_its_neighbourhood(tmp_path):
    """The exemption exists to protect a token that IS an id. A window wide enough to hold a
    sentence excuses any token standing NEAR the word, and on a portal about stations and surveys
    those words stand beside everything."""
    for line in ("C42: only POSITIONED stations reach the layer.",
                 "C46: the recognised licence-id vocabulary."):
        near = tmp_path / "near.js"
        near.write_text(f"// {line}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([near])
        assert hits and "work-item identifier" in hits[0], (
            f"a work-item tag was excused by a word standing near it: {line}"
        )


def test_history_and_alternatives_narrative_is_caught(tmp_path):
    """The vocabulary filter clears the words on the list and leaves the SHAPES off it, so each
    shape history takes is named here as well as each word."""
    cases = [
        "The label used to read Sites; the tree is the reason it does not.",
        "The row used to be the survey's, and the station's is the correct home.",
        "The trailing pointer used to send a reader to the API section.",
        "artifactsFor used to filter the whole files array on every call.",
        "A graph would have needed a host per row.",
        "Previously the counter was rebuilt on every keystroke.",
        "The chooser no longer reads the tree state.",
        "The digest is read from the manifest instead of the old per-file scan.",
        "The value is read from the record rather than the old constant.",
        "Historically the badge sat on the card.",
        "Originally the panel carried three tiles.",
        "Cleanup wave (D): the backdrop behind the drawer.",
        "Wave-1 carried the shallow identifier only.",
        "The editor gained this field in wave 1.",
        "DOCS WAVE, STAGE 3: the interface page moved to the docs site.",
        "The regex extractor was retired in 2026-06.",
        "The 2026-08 fallback is the one this reads.",
        "Two independent defects (fix/gateway-silent-success) sat in the fetch.",
        "The listing page landed on feat/release-machinery.",
        "The extractor was retired in slice #3d.",
        "The single source for this default (code-health review M5).",
        "Deliberately ungated (review C2): the login page loads it.",
        "Three consecutive review rounds each found another default.",
        "The bucket was flagged missing in the review.",
    ]
    for i, case in enumerate(cases):
        f = tmp_path / f"hist{i}.js"
        f.write_text(f"// {case}\nvar a = 1;\n", encoding="utf-8")
        assert offences([f]), f"the history rule missed: {case}"


def test_commented_out_code_is_caught_in_its_shapes(tmp_path):
    plants = {
        "assign.js": "// const screening = buildScreening(row, level);\nvar a = 1;\n",
        "call.js": '// fetch("/api/x").then(r => r.json());\nvar a = 1;\n',
        "control.js": "// if (m.model_doi) { level3 = row(m); }\nvar a = 1;\n",
        "declare.py": "# def build_row(station, level):\na = 1\n",
        "block.js": ("/* const html = `<div class=\"a\">`;\n"
                     "   const more = `</div>`;\n"
                     "   panel.innerHTML = html + more; */\nvar a = 1;\n"),
    }
    for name, body in plants.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        hits = offences([f])
        assert hits and "commented-out code" in hits[0], f"{name}: commented-out code went unseen"


def test_a_one_line_block_comment_is_read_without_its_closer():
    """A comment shape anchored to the end of a line cannot match while the comment's own closer is
    still sitting on it, so a one-line /* */ or <!-- --> hides every terse code shape there is."""
    for source in ('/* rows.push(["x", y]); */',
                   '/* level3 = row(m); */',
                   '<!-- panel.innerHTML = html; -->'):
        assert looks_like_code(source), f"a one-line block comment hid the code inside it: {source}"


def test_a_switched_off_array_or_object_element_is_commented_out_code():
    """A row lifted out of an array or an object literal is code switched off rather than deleted,
    and it is the shape a live literal can carry INLINE, between two of its own entries."""
    for source in ('/* ["screening parameters", params], */',
                   '/*["screening","Screening"],*/',
                   '// { label: "Screening", key: "screening" },'):
        assert looks_like_code(source), f"a switched-off literal element went unseen: {source}"


def test_a_switched_off_fragment_ending_on_an_operator_is_commented_out_code():
    """A call switched off INSIDE a live expression ends on the operator that joined it to the next
    term, not on a terminator, so a shape anchored to a statement end never sees it. That is the
    shape that
    survives longest, because the live code around it still reads as one statement."""
    for source in ('/* drawerPanel("screening",screeningHtml,false)+ */',
                   '// drawerPanel("screening",screeningHtml,false) +',
                   '/* buildRow(m) && */',
                   '// widths.push(w) ??',
                   '/* map.getPane("markers"). */'):
        assert looks_like_code(source), f"a switched-off fragment ended on an operator: {source}"
    for prose in ("The panel is built by drawerPanel(name, html, open) and",
                  "each row is one station.",
                  "See docs: portal internals, drawer.js.",
                  "drawer.js.",
                  "statusUrlSafe() guards (non-vacuous).",
                  "_preview_env().",
                  "e.g."):
        assert not looks_like_code(prose), f"prose was read as code: {prose}"


def test_a_tag_at_the_head_of_a_docstring_is_in_head_position(tmp_path):
    """The triple quote is a comment leader like any other. Without it the first line of a docstring
    never sits in head position, and a work-item tag written there is unreachable."""
    f = tmp_path / "tagged.py"
    f.write_text('"""C32 the ONE source."""\n', encoding="utf-8")
    hits = offences([f])
    assert hits and "work-item identifier" in hits[0], (
        "a work-item tag at the head of a docstring went unseen"
    )


def test_prose_that_names_a_function_is_not_commented_out_code(tmp_path):
    prose = tmp_path / "prose.js"
    prose.write_text("// fetch() is the scripted healthz probe.\n"
                     "// from the source, the tile is gone (it lives in the Response tab).\n"
                     "// return the first row whose level matches.\nvar a = 1;\n", encoding="utf-8")
    assert not offences([prose]), "the rule flagged prose that merely names a function or a keyword"


# ---------------------------------------------------------------------------
# The three narrowings, each held to the exact case it was written for.
# ---------------------------------------------------------------------------
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


def test_the_approval_narrowing_targets_a_design_decision_not_the_workflow(tmp_path):
    clean = tmp_path / "clean.py"
    clean.write_text("# Writes a `Curated-by:`/`Approved-by:` trailer once the curator approved the\n"
                     "# submission.\na = 1\n", encoding="utf-8")
    assert not offences([clean]), "the approval rule flagged the gateway's own workflow vocabulary"
    for line in ("# Rebuilt to the approved mockup's structure.",
                 "# The wording here is the approved one.",
                 "# Kept as approved.",
                 "# The panel's shape has approval."):
        dirty = tmp_path / "dirty.py"
        dirty.write_text(f"{line}\na = 1\n", encoding="utf-8")
        assert offences([dirty]), f"the approval rule was side-stepped by: {line}"


def test_a_pin_may_cite_the_contract_it_holds_and_code_may_not(tmp_path):
    cite = tmp_path / "cite.py"
    cite.write_text("# Ranges take the spaced hyphen (LANE-ADDENDUM-HUB-FEEDBACK.md).\na = 1\n",
                    encoding="utf-8")
    assert not offences([cite], cite_contract=True), "the lane rule flagged a contract citation in a pin"
    assert offences([cite]), "code carried a contract file name and the sweep allowed it"
    name = tmp_path / "name.py"
    name.write_text("# The download lane reshaped this panel.\na = 1\n", encoding="utf-8")
    assert offences([name], cite_contract=True), "the lane rule missed a lane name"


def test_a_served_template_is_not_read_as_a_docstring(tmp_path):
    f = tmp_path / "page.py"
    f.write_text('def page():\n'
                 '    """Renders the console."""\n'
                 '    return """<p>the owner approved this on 2026-08-19</p>"""\n', encoding="utf-8")
    found = comments(f, f.read_text(encoding="utf-8"))
    assert len(found) == 1 and "Renders the console" in found[0][1], found
    assert not offences([f]), "the sweep reached into a served template"


def test_an_address_is_not_a_person(tmp_path):
    f = tmp_path / "fixture.py"
    f.write_text('# The DB says Owner@Private.Test and the artifact carries owner@private.test.\na = 1\n',
                 encoding="utf-8")
    assert not offences([f]), "the decision-owner rule flagged an email address in a fixture"


def test_a_docstring_with_a_non_ascii_character_is_extracted_exactly(tmp_path):
    """An AST column offset counts bytes; slicing the source string by it overshoots one position
    per non-ASCII character on the line, and the comment the sweep reads is then not the comment.
    A rewrite driven off that slice eats the character after the docstring, which is code."""
    f = tmp_path / "wide.py"
    body = 'def f():\n    """A note about 0.1\u00b0 and \u03b2, ending here."""\n    a = 1\n    return a\n'
    f.write_text(body, encoding="utf-8")
    found = [c for _, c in comments(f, f.read_text(encoding="utf-8"))]
    assert found == ['"""A note about 0.1\u00b0 and \u03b2, ending here."""'], found


def test_prose_about_code_is_not_commented_out_code(tmp_path):
    """An assignment and a semicolon are also the shape of a sentence naming a field, so the rule
    reads terseness as well: a wordy line is prose about code, not code."""
    f = tmp_path / "prose.py"
    f.write_text("# write_errors = puts dropped after the rename retries were exhausted (a lock class);\n"
                 "# read_errors = present-but-unreadable entries, counted as misses for the arithmetic;\n"
                 "# corrupt = entries whose embedded payload checksum failed on read, then recomputed;\n"
                 "a = 1\n", encoding="utf-8")
    assert not offences([f]), "the rule read three sentences about counters as commented-out code"


def test_a_standard_illuminant_is_not_a_work_item_tag(tmp_path):
    """D65 names the CIE daylight illuminant the colour maths is computed under."""
    f = tmp_path / "lab.py"
    f.write_text('def lab(hex_):\n    """CIELAB (D65, 2 deg) for an sRGB hex."""\n    return hex_\n',
                 encoding="utf-8")
    assert not offences([f]), "the tag rule flagged a standard illuminant"


def test_prose_opening_on_a_keyword_is_not_a_declaration(tmp_path):
    """A docstring line may begin with the word "function" and go on in English. The declaration
    shapes want a parameter list of identifiers and nothing after the closing paren."""
    f = tmp_path / "prose.py"
    f.write_text('def f():\n    """The pin reads the value through the loader\n'
                 '    function (its own regex over the source, so it cannot agree with itself):\n'
                 '    """\n', encoding="utf-8")
    assert not offences([f]), "the rule read an English sentence as a function declaration"


# ---------------------------------------------------------------------------
# Comment shape: the scar a removed token leaves is invisible to a vocabulary.
# ---------------------------------------------------------------------------
def test_comment_shapes_are_whole():
    files = []
    for producer in SURFACES.values():
        files += producer()
    hits = shape_offences(files, root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) carry the shape a cut token leaves behind rather than whole "
        "prose:\n" + "\n".join(hits))


def test_every_pointer_section_names_a_heading_the_docs_page_carries():
    """A pointer that carries a section clause must find that section on the page. The
    stylesheet pin below reads the shipped pages; this reads every pointer in the tree, at any
    heading level, so a pointer into a subsection is resolved too."""
    page = ROOT / "docs" / "docs" / "reference" / "portal-internals.md"
    headings = {h.strip() for h in re.findall(r"^#{2,6}\s+(.+)$",
                                              page.read_text(encoding="utf-8"), re.M)}
    assert headings, "the docs page carries no headings, so this resolution would pass over nothing"
    missing, found = [], 0
    for path in commented_tree():
        if path.name == SELF or path.is_relative_to(ROOT / "docs"):
            continue
        try:
            text = source_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        if "See docs:" not in text:
            continue
        for lineno, comment in comment_runs(path, text):
            for fragment, match in pointer_fragments(" ".join(bare(comment).split())):
                if match is None or not match.group(2):
                    continue
                found += 1
                if match.group(2) not in headings:
                    missing.append("%s:%d: %s" % (path.relative_to(ROOT), lineno, fragment))
    assert found, "no pointer carried a section, so this resolution would pass over nothing"
    assert not missing, (
        "pointers name a section the docs page does not carry:\n" + "\n".join(missing))


def test_each_broken_shape_is_caught(tmp_path):
    """One case per shape, each written the way the sweep actually broke a comment. A shape whose
    scar comes at several widths carries one case per width, so the list is a sequence of pairs
    rather than a mapping and the LABEL is the text the report must carry."""
    cases = (
        ("unmatched )", '"""The identifiers design ): the instrument PID."""\n'),
        ("a space before punctuation", '"""The suppression kill : a survey carrying both."""\n'),
        # The gap in front of the mark, with the bracket that closed the group standing where the
        # word would be: the shape the cut citation in a mapping table leaves.
        ("a space before punctuation",
         '"""Every related_identifiers row goes to relationships[] ; activities[] follows."""\n'),
        ("an empty bracketed group", '"""Blocking-FAIL guard (+): re-check server-side."""\n'),
        ("a bracket opening on a connector",
         '"""The single poll loop (- the one background task)."""\n'),
        # The line that opens on a stray mark, at its four widths: the bracket alone, which is the
        # narrowest case and the only one a single-character rule could see; the bracket carrying
        # the full stop of the sentence whose citation was cut; the bracket carrying the semicolon
        # of the clause; and the mark standing on its own at the head of the continuation.
        ("a line opening on the punctuation a cut left standing",
         '"""The identifiers model\n)\n"""\n'),
        ("a line opening on the punctuation a cut left standing",
         '"""The submission that already carries these exact bytes (duplicate-content 409,\n'
         ').\n\nThe rule is about CONTENT."""\n'),
        ("a line opening on the punctuation a cut left standing",
         '"""The DOI is injected because it is absent from every EDI (read doi=None,\n'
         '); the journal citation is single-sourced too."""\n'),
        ("a line opening on the punctuation a cut left standing",
         '"""Every related_identifiers row goes to relationships[]\n'
         '; activities[] comes from project_raid only."""\n'),
        # The word a substitution left standing, in the run and across the gutter.
        ("a word written twice",
         '"""NARROWED by the The API docs section: the ban does not reach the class."""\n'),
        ("a word written twice",
         '# The rules these pins hold, all of them from the\n# the brief.\nRULES = ()\n'),
        # The noun the cut took away, in the two places it happened: a shipped measurement with
        # nothing to measure it against, and a pinned string with nothing to be.
        ("a sentence ending on the word that introduced its noun",
         "# The old endpoints measured dE76 under a. See docs: portal internals, state.js.\n"
         "RAMP = ()\n"),
        ("a sentence ending on the word that introduced its noun",
         '"""Parsed structurally, and by exact string where the exact words are the."""\n'),
        # The same cut read at the head of the sentence, where the token WAS the subject, and at
        # the tail, where the bracketed aside was what the copula was about.
        ("a sentence opening on a verb with no subject",
         '# The portal serves the old build until a rebuild runs. adds a host-side timer.\n'
         "TIMER = ()\n"),
        ("a sentence ending on the verb whose complement was cut",
         '"""All coverage went through the fake. The sole real-git lane (curator-e2e) was."""\n'),
        ("two sentence marks with nothing between them",
         '# Two overlapping ticks must not both build,; the second is a no-op.\n'
         "LOCK = ()\n"),
        # The same shape at the two widths the colon gives it: the comma of the phrase against
        # the colon that introduced the clause, and a group that closed before the cut token.
        ("two sentence marks with nothing between them",
         '# A production regression,: no station on the deployed portal could be opened.\n'
         "OPENED = ()\n"),
        ("two sentence marks with nothing between them",
         '"""The raw entries are cache-excluded anyway).: the digest is carried, never re-read."""\n'),
        # The word left against the bracket that closed its group, at its three widths: a
        # participle carrying its preposition, a demonstrative on its copula, and a group that
        # opens on a copula and closes with no complement.
        ("a word left hard against the bracket that closed its group",
         '"""The row indices the contributor-credit model, extended in) names."""\n'),
        ("a word left hard against the bracket that closed its group",
         '"""Drive it to VALIDATED past the scan pipeline - those are), and materialise a tree."""\n'),
        ("a word left hard against the bracket that closed its group",
         '# The site-data mount is read-WRITE here now (was ro in). The reconcile step needs it.\n'
         "MOUNT = ()\n"),
        # The value an operator was pointing at, taken out of a documented return and out of a
        # documented expectation.
        ("an operator standing where the value it points at was cut",
         '"""Read the log rows. Never raises; an absent log => ."""\n'),
        ("an operator standing where the value it points at was cut",
         '"""Two entries in first-appearance order. B: count 1, stations= ."""\n'),
        # The subject taken out of the MIDDLE of a sentence, where the copula is left introducing
        # the object of the verb behind it.
        ("a verb whose subject was cut from the middle of its sentence",
         '"""This is the guarantee trades the leak-clean-by-construction shape for."""\n'),
        # The aside reduced to the label that introduced it.
        ("a bracketed aside reduced to the label that introduced it",
         '"""The README skeleton (design): one heading per served product."""\n'),
        ("a bracketed aside reduced to the label that introduced it",
         '# The engine keeps reading sources[] (note), so nothing served changes.\n'
         "SOURCES = ()\n"),
        ("a pointer that is not of the pointer grammar",
         '"""The rows worth writing. See docs: portal internals, add-survey.html.tml."""\n'),
        # The closing half of the connector family: before a bracket, before a square bracket,
        # at the end of the run, and hard against the connector in front of it.
        ("a connector left standing where a token was cut",
         '"""The rollup (the runner is the only place YAML is parsed -)."""\n'),
        ("a space before the bracket that closes a group",
         '"""A 26-char string from the Crockford-base32 id charset (design )."""\n'),
        ("a hyphen with nothing after it",
         '"""Reconstruct the PRE- per-station station.json shape."""\n'),
        ("a pointer standing in front of a sentence fragment",
         '"""See docs: portal internals, add-survey.html. like a nameless row."""\n'),
        ("a run opening on the punctuation of a cut sentence",
         '""": the export appends the hosting institution to every record."""\n'),
    )
    for label, body in cases:
        f = tmp_path / "broken.py"
        f.write_text(body, encoding="utf-8")
        hits = shape_offences([f])
        assert hits and label in hits[0], f"{label} went unseen in {body!r}: {hits}"


def test_a_capital_a_cut_left_behind_is_caught(tmp_path):
    """The two halves of the capitalisation scar. A sweep that takes the words in front of a name
    capitalises what is left, so `station.json` becomes `Station.json` and names no file; a sweep
    that takes the end off a line leaves the word below it standing at the head of a line, and the
    capital it was given puts a new sentence in the middle of an old one."""
    cases = {
        "a name wearing a capital it does not have":
            '"""Station.json emission semantics, pinned against the real emitter."""\n'
            'STATION = "station.json"\n',
        "a capital in the middle of a sentence":
            "# Each entry is a substring that must appear in a skip's reason\n"
            "# For that skip to be allowed.\nALLOWED = []\n",
    }
    for label, body in cases.items():
        f = tmp_path / "broken.py"
        f.write_text(body, encoding="utf-8")
        hits = shape_offences([f])
        assert hits and label in hits[0], f"{label} went unseen in {body!r}: {hits}"


def test_whole_prose_is_not_a_broken_shape(tmp_path):
    """The negatives, one per exemption the shape rules carry: an interval, an enumerated list, a
    definition table, a bracket the prose quotes, a well-formed pointer, and a bracket a run of
    line comments opens on one line and closes on the next."""
    cases = {
        "interval.py": '"""Normalise an angle to (-180, 180] for reporting."""\n',
        "enumerated.py": '"""The recovery:\n\n    1) the publish FAILED closed.\n'
                         '    2) the tree is the pre-state.\n    """\n',
        "table.py": '"""The handshake.\n\n    engine_commit : short HEAD of this repo.\n'
                    '    source_commit : short HEAD of the surveys checkout.\n    """\n',
        "quoted.py": '"""Index just past the `}` closing a `${` hole."""\n',
        "pointer.py": '"""The first-paint set. See docs: portal internals, data.js."""\n',
        "run.py": "# The manifest is the index of every downloadable artifact (per-station\n"
                  "# EDI and per-survey bundles), each carrying size and sha256.\na = 1\n",
        # A shell default expansion and an scp-style target both carry a connector against a
        # word, and neither is a cut token.
        "shell.sh": "# The image tag defaults where the operator sets none (${TAG:-latest}).\n",
        "remote.sh": "# The pull target is user@host:/path/to/backups, split on the first colon.\n",
        # A quoted run wrapped across two comment lines closes the bracket it opened.
        "wrapped.js": '// Pinned separately (tests/test_entity_pages.py, "the survey blurb\n'
                      '// prose must render"). The card carries no description block.\nvar a = 1;\n',
        # A compound wrapped by the gutter keeps its hyphen at the end of the LINE, and suspended
        # hyphenation names the word it is suspended in front of.
        "wrap.js": "// The drawer is the densest consumer of the PHASE 2 products and of the section-\n"
                   "// agnostic combined-post machinery.\nvar a = 1;\n",
        "suspended.py": '"""The pre- and post-processing notes both ride the same conditioning field."""\n',
        # A pointer followed by a code identifier is naming code, not stammering.
        "identifier.js": "// See docs: portal internals, state.js. buildState() folds the policy onto\n"
                         "// each station.\nvar a = 1;\n",
        # A capital that belongs: a proper noun the same file writes inside a line, a finished
        # sentence, a blank line between paragraphs, and a list item.
        "proper.py": '"""The coastline is generated from the Australian outline the build ships.\n'
                     "    Australian state boundaries ride the same file.\n    \"\"\"\n",
        "para.py": '"""The served stylesheet is inlined into every emitted page.\n\n'
                   '    Because it is paid once per page, its comment bytes carry a cap."""\n',
        "list.py": '"""The recovery:\n\n    * the publish FAILED closed;\n'
                   "    * the tree is the pre-state.\n    \"\"\"\n",
        # A word joined by a hyphen to what precedes it is the tail of a compound, so a header
        # name that ends on a function word is not the first half of a doubled pair.
        "header.py": '"""The message sets Reply-To to the From address, and carries no dash."""\n',
        # A definition row writes the colon of its continuation at the head of a line on purpose,
        # which is why the colon is off the stray-opening list.
        "rows.py": '"""The fields:\n    access   : the normalised access state\n'
                   "    embargo  : the date the hold lifts\n    \"\"\"\n",
        # An enumerator opens on its number, not on the bracket that follows it.
        "enum.py": '"""The two passes:\n    1) read every record;\n'
                   "    2) write the index.\n    \"\"\"\n",
        # A preposition ends an English sentence every day, and a capital letter in front of a full
        # stop is a list marker; neither is a noun a cut took away.
        "stranded.py": '"""The bucket the tile falls into. The meaning a missing value has none of."""\n',
        # The same preposition closes a relative clause hard against the bracket that holds it,
        # which is why the bracket rule reads a participle with no auxiliary rather than any
        # preposition: the head noun of each of these stands outside the group.
        "relative.py": '"""It is copied byte for byte (under the name it arrived with), and an\n'
                       "    XML-sourced station carries (the digest this entry was keyed under).\n"
                       '    A panel (that was renamed from) keeps the id (it was folded in)."""\n',
        # A keyword argument and an attribute are named with a bare "=" in this tree, so only an
        # arrow, or an "=" the writer spaced off, reads as an operator with its value cut away.
        "kwarg.py": '"""It uses a plain dump with no default=, so a date object would raise, and\n'
                    '    it rejects an inline block without src=. Both are named, not called."""\n',
        # A demonstrative singular takes a complement outside the group, and a copula group that
        # closes on its own complement is whole.
        "copula.py": '"""A 302 is not hosting (and this page never claims it is), which is the\n'
                     '    half the reader needs (it was ro in the first release)."""\n',
        # A label that carries the record it cites is an aside, not a bracket pointing at nothing.
        "labelled.py": '"""The skeleton (design record 37) names one heading per served product."""\n',
        "marker.py": '"""Two shapes:\n\n    A. the curated survey;\n'
                     "    B. the raw survey.\n    \"\"\"\n",
        # A sentence opening in lower case is ordinary here: on an identifier, on a path, on a
        # word the sentence before it was still spelling. Only a finite verb with no subject is a
        # cut, and a pronoun subject keeps a copula ordinary at the end of one.
        "opens.py": '"""The manifest is read once. releases/ is a SIBLING of builds/, so the two\n'
                    "    never collide. The label says which of the two it is.\"\"\"\n",
        # A decimal and an ellipsis put a digit or a further dot after the mark.
        "marks.py": '"""The alpha steps rgba(168,84,84,.22) to rgba(226,147,139,.14).\n'
                    "    The rows are {field: [{value, members:[slug,...]}, ...]}.\"\"\"\n",
    }
    for name, body in cases.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        assert not shape_offences([f]), f"{name}: whole prose was read as a broken shape"


def test_a_bracket_left_open_inside_a_run_is_caught(tmp_path):
    """A reader reads the run, so a bracket left open on an interior line is the same broken
    shape as one left open on the first. Reporting only the head and the tail hides the middle
    of every long comment, which is where a sweep does most of its cutting."""
    f = tmp_path / "interior.js"
    f.write_text("// The drawer renders the response curves from tf.json.\n"
                 "// The screening rows come from sci.json (processing software,\n"
                 "// then the maturity stars and the provenance table.\nvar a = 1;\n",
                 encoding="utf-8")
    hits = shape_offences([f])
    assert hits and "unmatched (" in hits[0], hits


def test_the_gutter_says_which_lines_are_one_comment(tmp_path):
    """A comment trailing a statement is its own comment: joining it to the block above merges two
    people's sentences and reports a bracket one of them never opened. A trailing comment's own
    continuation, aligned under it in the same column, IS the same comment."""
    f = tmp_path / "gutter.js"
    f.write_text("// The citation rendered inside the Cite box.\n"
                 "function cite(m){const base=apa(m);   // the sentence WITHOUT the DOI suffix\n"
                 "  if(!m) return base;                 // an unknown record renders nothing\n"
                 "}\n", encoding="utf-8")
    runs = comment_runs(f, f.read_text(encoding="utf-8"))
    assert len(runs) == 2, runs
    assert runs[0][0] == 1 and "Cite box" in runs[0][1]
    assert runs[1][0] == 2 and "DOI suffix" in runs[1][1] and "unknown record" in runs[1][1]


def test_a_connector_at_the_end_of_a_run_is_caught(tmp_path):
    """The run itself ends where the cut token stood, with no bracket to report it."""
    f = tmp_path / "tail.py"
    f.write_text('"""The rollup the portal shows readers, first-declarer -"""\n', encoding="utf-8")
    hits = shape_offences([f])
    assert hits and "a connector left standing" in hits[0], hits


def test_a_marker_against_punctuation_is_still_the_next_line_of_its_run(tmp_path):
    """A cut that takes the leading token off a line leaves the marker hard against the punctuation
    that belonged to the words above it. The line is still the next line of the run a reader reads,
    and read as a run of its own it carries no scar at all."""
    f = tmp_path / "lead.py"
    f.write_text("# A done-file with an unknown outcome must NOT drive any transition\n"
                 "#. proven failing: read_done returned a DoneFile\n"
                 "# and _apply_done attempted a transition.\nX = 1\n", encoding="utf-8")
    runs = comment_runs(f, f.read_text(encoding="utf-8"))
    assert len(runs) == 1, runs
    hits = shape_offences([f])
    assert hits and "a space before punctuation" in hits[0], hits


def test_a_run_may_open_on_a_decimal_or_an_ellipsis(tmp_path):
    """The head rule reads punctuation a cut left standing, which is followed by a space. A decimal
    point and an ellipsis carry a character after the mark, and neither is a scar."""
    for body in ('"""...and the remainder of the sentence is the comment."""\n',
                 '""".25 of the header budget is the type block."""\n'):
        f = tmp_path / "whole.py"
        f.write_text(body, encoding="utf-8")
        assert not shape_offences([f]), body


def test_a_run_of_line_comments_is_one_shape(tmp_path):
    """Read line by line, a bracket opened on one line and closed on the next is two scars. The
    run is the comment a reader reads, so it is the unit the shape rules read."""
    f = tmp_path / "run.js"
    f.write_text("// The cap fires as bytes arrive (chunked-safe, no\n"
                 "// Content-Length dependency).\nvar a = 1;\n", encoding="utf-8")
    assert len(comment_runs(f, f.read_text(encoding="utf-8"))) == 1
    assert not shape_offences([f])


# ---------------------------------------------------------------------------
# The instrument reaches what the classes declare.
# ---------------------------------------------------------------------------
def test_every_declared_configuration_suffix_is_read_by_the_extractor(tmp_path):
    """A class that LISTS a suffix the extractor cannot dispatch on reads zero comments and
    reports green over whatever is written in those files. Every suffix a configuration class
    names must reach a scanner."""
    unread = []
    for suffix in CONFIG_SUFFIXES:
        f = tmp_path / ("declared" + suffix)
        f.write_text("# the only comment\nname==1.0\n", encoding="utf-8")
        if [c for _, c in comments(f, f.read_text(encoding="utf-8"))] != ["# the only comment"]:
            unread.append(suffix)
    assert not unread, (
        "the configuration classes list suffixes the extractor does not read, so those files are "
        "inside the sweep and outside the scanner: " + ", ".join(unread))


def test_a_wrapped_phrase_is_still_the_phrase(tmp_path):
    """Every multi-word rule is defeated by the line wrap between its words unless the prose is
    flattened first. A comment is not cleaner for being wrapped at column 100."""
    cases = {
        "design-document citation":
            '"""FAILS IF the card carries the whole rollup (the tall card the design\n'
            '    brief 12 names) or cuts it mid-word."""\n',
        "review or slice identifier":
            '"""The ONE canonical argv for the validator subprocess (code-health\n'
            '    review). Both runners go through this."""\n',
        "history or alternatives narrative":
            '"""Every shipped header is five items. Releases carries a sixth that About no\n'
            '    longer has."""\n',
    }
    for label, body in cases.items():
        f = tmp_path / "wrapped.py"
        f.write_text(body, encoding="utf-8")
        hits = offences([f])
        assert hits and label in hits[0], f"a line wrap hid {label}: {hits}"
        one_line = tmp_path / "oneline.py"
        one_line.write_text(" ".join(body.split()) + "\n", encoding="utf-8")
        assert offences([one_line]), f"{label} was not caught unwrapped either"


def test_a_round_of_work_is_provenance_in_every_spelling(tmp_path):
    """The numbered round is the audit trail whatever joins the word to its number."""
    for i, spelling in enumerate(("ROUND-2", "ROUND 2", "ROUND_2", "Round 3", "round 2")):
        f = tmp_path / f"round{i}.js"
        f.write_text(f"// {spelling}: slug-collision awareness, zip-path visibility\nvar a = 1;\n",
                     encoding="utf-8")
        hits = offences([f])
        assert hits and "round-of-work identifier" in hits[0], f"{spelling} was not read as one"
    for clean in ("the retry loop rounds the value up before the compare",
                  "Round 3 of the retry loop is the last one the budget allows.",
                  "a round trip through the encoder must be lossless"):
        f = tmp_path / "cleanround.js"
        f.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([f]), f"the round rule flagged ordinary prose: {clean}"


def test_a_numbered_review_finding_is_provenance(tmp_path):
    """A numbered review finding names the sitting a change came out of, which is what the slice
    and task numbers already name."""
    f = tmp_path / "finding.py"
    f.write_text('"""Duplicate member names (review #13): a zip may carry two entries."""\n',
                 encoding="utf-8")
    hits = offences([f])
    assert hits and "review or slice identifier" in hits[0], "a numbered review finding went unseen"
    clean = tmp_path / "clean.py"
    clean.write_text('"""The curator reviews the submission before it is published."""\n',
                     encoding="utf-8")
    assert not offences([clean]), "the rule flagged the ordinary verb"


def test_every_spelling_of_a_review_finding_and_an_audit_item_is_provenance(tmp_path):
    """The sitting a change came out of, in each spelling the tree actually used: the finding
    numbered or named, the review named after its kind, and the audit item numbered. The ordinary
    senses (an audit log, an audit tail, a curator reviewing a submission) carry no number and no
    kind, which is what keeps them out."""
    caught = {
        "numbered.py": '"""The states whose note renders publicly (review finding 2)."""\n',
        "named.py": '"""The list numbering (adversarial-review finding, LOW)."""\n',
        "hostile.py": '"""Citation honesty (pre-release hostile-review finding)."""\n',
        "audit.py": '"""Submission paths, honest to the infrastructure (audit 5.1)."""\n',
        "audit_flat.py": '"""Library defaults asserted as fact (final hostile audit 4.2)."""\n',
    }
    for name, body in caught.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        hits = offences([f])
        assert hits and "review or slice identifier" in hits[0], f"{name} went unseen: {hits}"
    allowed = {
        "log.py": '"""Publish-cycle reasons are curator and audit text, never public."""\n',
        "tail.py": '"""The pending intents and the actions audit tail are read-only."""\n',
        "verb.py": '"""The curator reviews the submission before it is published."""\n',
    }
    for name, body in allowed.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        assert not offences([f]), f"{name}: the ordinary sense was flagged"


def test_a_switched_off_ternary_arm_is_commented_out_code(tmp_path):
    """A ternary arm switched off inside a live expression ends on the colon that joined it to the
    arm below, so a shape anchored to a statement end never reaches it."""
    f = tmp_path / "ternary.js"
    f.write_text("var a = cond\n  // screeningPanel ? drawerPanel(\"screening\") :\n"
                 "  otherPanel ? other() : none();\n", encoding="utf-8")
    hits = offences([f])
    assert hits and "commented-out code" in hits[0], "a switched-off ternary arm went unseen"
    for clean in ("the two seams must agree:",
                  "a station is dropped by the gate, so the row is absent.",
                  "either shape is accepted: bare or quoted."):
        c = tmp_path / "cleanternary.js"
        c.write_text(f"// {clean}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([c]), f"the ternary shape ate prose: {clean}"


def test_a_phrase_wrapped_across_two_line_comments_is_still_the_phrase(tmp_path):
    """The unit a rule reads is the comment a READER reads. A run of // or # lines is one comment
    to a reader, and a phrase that wraps between two of them is one phrase; a scan that reads each
    line alone is defeated by the break, which is the same hole a wrap inside one comment opened."""
    f = tmp_path / "wrapped.js"
    f.write_text("// The rollup no\n// longer duplicates them here.\nvar a = 1;\n", encoding="utf-8")
    assert len(comment_runs(f, f.read_text(encoding="utf-8"))) == 1
    hits = offences([f])
    assert hits and "history or alternatives narrative" in hits[0], (
        "a phrase wrapped across two line comments escaped the vocabulary")
    whole = tmp_path / "whole.js"
    whole.write_text("// The rollup names them once.\n// The card carries the grant ids.\nvar a = 1;\n",
                     encoding="utf-8")
    assert not offences([whole]), "the run rule flagged two ordinary sentences"


# ---------------------------------------------------------------------------
# What IS, not what was: the shipped tier and the tier the engine emits.
# ---------------------------------------------------------------------------
def test_a_shipped_comment_states_what_is():
    hits = history_offences(shipped_html() + shipped_js() + shipped_page_scripts(), root=ROOT)
    assert not hits, (
        f"{len(hits)} shipped comment(s) narrate what was there rather than what is; a visitor "
        "cannot open the file they talk about:\n" + "\n".join(hits))


def test_each_history_shape_is_caught_in_its_own_sense(tmp_path):
    """One case per shape, each in the sense that makes it history: a part the page is MADE OF,
    named and definite."""
    cases = {
        "is gone": '// The #tfAvail CHECKBOX is gone.\nvar a = 1;\n',
        "lived here": "// mth5BundleFor lived here, looked up by slug.\nvar a = 1;\n",
        "was removed": '// The "dimensionality mix" row was removed from this table.\nvar a = 1;\n',
        "folded into": '// The checkbox is folded into the Browse single-select.\nvar a = 1;\n',
        "retired": "// the retired tickbox's flag, read by the exports.\nvar a = 1;\n",
        "is dropped": "// The Organisation ROR row is dropped from the rollup.\nvar a = 1;\n",
    }
    for label, body in cases.items():
        f = tmp_path / "was.js"
        f.write_text(body, encoding="utf-8")
        hits = history_offences([f])
        assert hits and label in hits[0], f"{label} went unseen: {hits}"


def test_the_same_words_about_data_are_the_code_speaking(tmp_path):
    """The negative for each shape. A thing the code HANDLES arrives with an indefinite article or
    as a bare plural, and a negated clause is a constraint rather than a history; both stay."""
    cases = {
        "a row": "// A textless row is dropped before the type guard runs.\nvar a = 1;\n",
        "bare plural": "// Trailing slashes are dropped so the bare id is the key.\nvar a = 1;\n",
        "every entry": "// Every entry whose payload checksum fails is deleted on read.\nvar a = 1;\n",
        "a negation": "// The acknowledgement is never folded into the citation.\nvar a = 1;\n",
        "no station": "// No station is removed by the projection; only its routes are.\nvar a = 1;\n",
        "an element": "// null when an element is gone from the document.\nvar a = 1;\n",
    }
    for label, body in cases.items():
        f = tmp_path / "data.js"
        f.write_text(body, encoding="utf-8")
        assert not history_offences([f]), f"the rule read the data sense as history: {label}"


def test_a_path_outside_this_repository_is_an_unresolvable_pointer(tmp_path):
    """A pointer names something a reader of this repository can open. A working directory beside
    the checkout exists on one machine, so a document cited through it is dead for everyone else;
    a document under one of the repository's own trees resolves for every reader."""
    outside = tmp_path / "outside.py"
    outside.write_text('"""The rule: AusMT_2026/LANE-CONTRACT-FOOTER-AUSCOPE.md."""\n', encoding="utf-8")
    hits = offences([outside], cite_contract=True)
    assert hits and "a path outside this repository" in hits[0], "a dead citation went unseen"
    inside = tmp_path / "inside.py"
    inside.write_text('"""The rule: maintainer/ADR-001-repo-structure.md."""\n', encoding="utf-8")
    assert not offences([inside]), "a document under a tree of this repository was flagged"
    either = tmp_path / "either.py"
    either.write_text('"""One of LICENSE.md/README.md must be present."""\n', encoding="utf-8")
    assert not offences([either]), "an either-or list of file names was read as a path"


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


def test_the_messages_a_failure_prints_carry_no_audit_trail():
    """An assertion message and a skip reason are what a reader of a red run is handed, so they are
    held to the audit trail the way a comment is: not who decided, when, or under which work item,
    wave, round or lane. Their SEMANTICS are untouched, because the message is what says which
    invariant broke; and the em and en dash go, because a reason is printed on a terminal where the
    glyph is not always legible. A message may still cite the contract a pin traces itself by."""
    hits = message_offences(guard_tests(), root=ROOT)
    assert not hits, (
        f"{len(hits)} assertion message(s) or skip reason(s) under portal/tests carry the audit "
        "trail or a typographic dash:\n" + "\n".join(hits))
