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
    """Index just past the } closing a ${ hole, nested strings included."""
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


HASH_SUFFIXES = {".sh", ".bash", ".yml", ".yaml", ".service", ".timer", ".conf",
                 ".example", ".map", ".dockerfile", ".toml", ".cfg", ".ini"}
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
    # A slice, a review round and a lettered review finding are all names for
    # the piece of work a change belonged to.
    Rule(re.compile(r"\bslices?\s*#"
                    r"|\breviews?\s+(?-i:[A-Z]\d)\b"
                    r"|\b(?:in|during|from) the review\b"
                    r"|\breview[- ]rounds?\b"
                    r"|\bcode-health review\b", re.I), "review or slice identifier"),
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
# optional letter, and it is lane vocabulary in four positions: at the head of a
# comment, before a colon, inside parentheses, and beside the words a work item
# is counted with. It is NOT a station or site id, a licence id, a projection, a
# digest, a percentile or a heading level, which is what the exemptions are for.
_TAG = r"[A-Z]{1,2}\d{1,2}[a-z]?"
_TAGS = r"%s(?:\s*[/,]\s*%s)*" % (_TAG, _TAG)
_WORK = r"Amendment|amendment|lanes?|round|wave|gate|follow-up|phase"

TAG_PATTERN = re.compile(
    r"(?:^|(?<=\n))[ \t]*(?P<head>%s)(?![\w]|\.\d)"
    r"|(?<![\w#])(?P<colon>%s)(?![\w]|\.\d)\s*:"
    r"|\(\s*(?P<paren>%s)(?![\w]|\.\d)\s*[,;)]"
    r"|(?:%s)\s+(?P<after>%s)(?![\w]|\.\d)"
    r"|(?<![\w#])(?P<before>%s)(?![\w]|\.\d)\s+(?:%s)\b"
    % (_TAGS, _TAGS, _TAGS, _WORK, _TAGS, _TAGS, _WORK)
)

# The false positives, one entry per MEANING: what the token names, the token
# itself, and the words that must stand beside it for that meaning to be the one
# in play. The context test is what keeps an entry from buying a false negative:
# without it, a genuine work item spelled S3 or H1 would be permanently
# invisible. Every entry is held by a test that the same token in work-item
# position, without those words, is still caught.
TAG_NOT_A_TAG = (
    ("the object store", re.compile(r"^S3$"),
     re.compile(r"bucket|object|store|endpoint|MinIO|\bR2\b", re.I)),
    ("a heading level", re.compile(r"^H[1-6]$"),
     re.compile(r"heading|<h\d|\btags?\b", re.I)),
    ("a CIE standard illuminant", re.compile(r"^D(?:50|55|65|75)$"),
     re.compile(r"illuminant|CIE|CIELAB|sRGB|white ?point|colou?r|\bLab\b", re.I)),
    ("a data level", re.compile(r"^L[0-3]$"),
     re.compile(r"\blevels?\b|\btiers?\b|\bproducts?\b", re.I)),
    ("a release quarter", re.compile(r"^Q[1-4]$"),
     re.compile(r"Release |20\d\d-Q|quarter", re.I)),
    ("a public-domain dedication", re.compile(r"^CC0$"),
     re.compile(r"licen[cs]|dedication|public domain|Creative Commons", re.I)),
    ("a DATAID example", re.compile(r"^(?:ST|A)\d{2}$"),
     re.compile(r"DATAID|data ?id|example", re.I)),
    ("a message digest", re.compile(r"^MD5$"),
     re.compile(r"digest|checksum|hash|manifest|sha\d", re.I)),
    ("a percentile", re.compile(r"^P(?:50|95|99)$"),
     re.compile(r"percentile|median|\btail\b|budget|threshold|profile", re.I)),
)
# A token that IS an id is named by the noun that says so, immediately before it
# with one space between. The test is on the TOKEN. A window wide enough to hold
# a sentence excuses any token standing NEAR the word, and on a corpus about
# stations and surveys those words stand beside everything.
TAG_ID_NOUN = re.compile(r"(?:station|site|survey|run|channel|filter|fixture) \Z", re.I)
_TAG_GROUPS = ("head", "colon", "paren", "after", "before")


def work_item_tags(text):
    """Every work-item tag in a bare comment, as (match, tag)."""
    found = []
    for match in TAG_PATTERN.finditer(text):
        group = next(name for name in _TAG_GROUPS if match.group(name))
        tag = match.group(group)
        start, stop = match.span(group)
        window = text[max(0, start - WINDOW):stop + WINDOW]
        parts = [part.strip() for part in re.split(r"[/,]", tag)]
        if all(any(token.match(part) and near.search(window)
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
    # the next term, so a shape anchored to ; , or ) cannot reach it. Prose ending on the same
    # operator is excluded by the terse-line limit above and by requiring the call's own brackets.
    r"^(?:await\s+|new\s+)?[\w$][\w$.]*\(.*\)\s*(?:\+|-|\*|/|&&|\|\||\?\?)\s*$",
    r"^(?:\[.*\]|\{.*\})\s*(?:\+|&&|\|\||\?\?)\s*$",
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


def labels_for(comment, cite_contract=False):
    """Every way one comment breaks the rule, as sorted labels."""
    text = bare(comment)
    found = {rule.label for rule in RULES if rule.hits(text)}
    if not cite_contract and CONTRACT_CITATION.hits(text):
        found.add(CONTRACT_CITATION.label)
    if work_item_tags(text):
        found.add("work-item identifier")
    if looks_like_code(comment):
        found.add("commented-out code")
    return sorted(found)


def offences(files, cite_contract=False, root=None):
    """Every comment that breaks the rule across a set of files, as report lines."""
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, comment in comments(path, text):
            labels = labels_for(comment, cite_contract=cite_contract)
            if labels:
                where = path.relative_to(root) if root and path.is_relative_to(root) else path.name
                found.append("%s:%s: %s: %s"
                             % (where, lineno, ", ".join(labels),
                                " ".join(comment.split())[:110]))
    return found
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
    "index.html": 16_500,
    "about.html": 6_300,
    "add-survey.html": 35_000,
    "releases.html": 4_800,
    "brand.html": 2_400,
    "404.html": 900,
}
SHIPPED_JS_CAP = 122_000

# THE LENGTH CLAUSE, on the shipped tier alone. A long constraint is stated in one or two sentences
# and anything longer belongs in docs/, so a comment a visitor downloads is at most two sentences
# and at most this many bytes. The pointer that carries a reader to the moved prose is not one of
# the two: it is the pointer, not the constraint.
COMMENT_CAP = 320
COMMENT_SENTENCES = 2
DOCS_POINTER = re.compile(r"\s*See docs: portal internals, [\w.\-]+\.\s*$")
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


def over_length(path, text):
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
            over.append("portal/%s:%d: %d bytes, %d sentence(s): %s"
                        % (path.name, lineno, size, said, prose[:100]))
    return over


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
    hits = offences(shipped_html(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in the shipped HTML carry provenance rather than a constraint:\n"
        + "\n".join(hits)
    )


def test_shipped_js_comments_state_constraints_only():
    hits = offences(shipped_js(), root=ROOT)
    assert not hits, (
        f"{len(hits)} comment(s) in portal/src/*.js carry provenance rather than a constraint:\n"
        + "\n".join(hits)
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
    comment carrying the constraint and the bare pointer to it. The exemptions are a licence or
    attribution obligation, whose wording IS the obligation, and the enumerated list above."""
    over = []
    for path in shipped_html() + shipped_js():
        over += over_length(path, path.read_text(encoding="utf-8"))
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
    for path in shipped_html() + shipped_js():
        body = path.read_text(encoding="utf-8")
        if DOCS_POINTER.search(" ".join(bare(body).split()) + " ") or f"portal internals, {path.name}" in body:
            rel = str(path.relative_to(ROOT))
            if f"## {rel}" not in text:
                missing.append(rel)
    assert not missing, (
        "the shipped tier points at sections this page does not carry:\n" + "\n".join(missing))


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
        seen = sum(len(comments(p, p.read_text(encoding='utf-8'))) for p in found)
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
        ("Q3: Release 2026-Q3 is the snapshot a citation names.",
         "Q3 reshaped the download panel."),
        ("CC0: a public domain dedication is not a licence with conditions.",
         "CC0 reshaped the download panel."),
        ("ST01: the DATAID the dialect note carries.",
         "ST01 reshaped the download panel."),
        ("MD5: the digest the manifest carries beside the sha256.",
         "MD5 reshaped the download panel."),
        ("P95: the percentile the build budget is set against.",
         "P95 reshaped the download panel."),
        ("station A1: the reference this survey record names.",
         "Amendment A1: the colour set is frozen."),
    ]
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
    term, not on a terminator, so a shape anchored to ; , or ) never sees it. That is the shape that
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
    cite.write_text("# Ranges take the spaced hyphen (LANE-ADDENDUM-HUB-FEEDBACK.md R1).\na = 1\n",
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
