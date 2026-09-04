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
import tokenize
from pathlib import Path

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
    text = path.read_text(encoding="utf-8")
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
    Rule(re.compile(r"\u00a7|\bSPEC\b|(?i:\bdesign brief\b)|\bADR-\d"),
         "design-document citation",
         # A licence's own clause number is the obligation, not a design document, and the legal
         # code it names is public. The window must carry the licence for the exemption to hold.
         ((re.compile(r"^\u00a7$"),
           re.compile(r"CC-?BY|CC0|ODbL|Creative Commons|licen[cs]e", re.I)),
          # An ADR that is a FILE in this tree is a pointer a reader can follow, which is what the
          # rule asks for. The window must carry the path, not merely the name.
          (re.compile(r"^ADR-\d"), re.compile(r"/ADR-\d[\w.-]*\.md\b")))),
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
        if not compound and all(any(token.match(part) and near.search(window)
                                    for _, token, near in TAG_NOT_A_TAG) for part in parts):
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
        text = path.read_text(encoding="utf-8")
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
SPACE_BEFORE_PUNCT = re.compile(r"\w[ ]+[.,;!?](?:\s|$)")
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
LONE_PUNCTUATION = re.compile(r"^[)\].]$")
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
        text = path.read_text(encoding="utf-8")
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
            if any(LONE_PUNCTUATION.match(line.strip()) for line in body):
                said.append("a line carrying one bracket")
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
        text = path.read_text(encoding="utf-8")
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


def operator_strings(path):
    """(line number, text) for every string an argparse module prints to an operator."""
    if path.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("add_argument", "ArgumentParser"):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if (keyword.arg in ARGPARSE_TEXT and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                found.append((value.lineno, value.value))
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
        seen = sum(len(comments(p, p.read_text(encoding='utf-8'))) for p in found)
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
        found = comments(path, path.read_text(encoding="utf-8"))
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
