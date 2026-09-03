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
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start, tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        out = [((text.count("\n", 0, m.start()) + 1, 0), m.group(0))
               for m in re.finditer(r"(?m)^[ \t]*#.*$", text)]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [(where[0], body) for where, body in sorted(out)]
    starts, total = [], 0
    for line in text.splitlines(keepends=True):
        starts.append(total)
        total += len(line)
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if (isinstance(node, ast.Expr) and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            out.append(((value.lineno, value.col_offset),
                        text[starts[value.lineno - 1] + value.col_offset:
                             starts[value.end_lineno - 1] + value.end_col_offset]))
    return [(where[0], body) for where, body in sorted(out)]


HASH_SUFFIXES = {".sh", ".bash", ".yml", ".yaml", ".service", ".timer", ".conf",
                 ".example", ".map", ".dockerfile", ".toml", ".cfg", ".ini"}
HASH_NAMES = {"Caddyfile", "Makefile", "Dockerfile", ".gitignore", ".dockerignore"}


def comments(path, text):
    """Every comment in one file, as (line number, text), each counted once."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return python_comments(text)
    if suffix in (".html", ".htm", ".plist", ".xml", ".svg"):
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
    Rule(re.compile(r"\bwave\s+[a-z]\b", re.I), "wave identifier"),
    Rule(re.compile(r"\bux\d", re.I), "work-item identifier"),
    Rule(re.compile(r"\btask\s*#", re.I), "work-item identifier"),
    # A pin may cite the contract it holds, and those documents are named
    # LANE-CONTRACT-*.md and LANE-ADDENDUM-*.md, so a citation is not a lane
    # name. Everything else that says lane is.
    Rule(re.compile(r"\blanes?\b(?!-[A-Z])", re.I), "lane name"),
    Rule(re.compile(r"\btreatments?\b", re.I), "design-history vocabulary"),
    Rule(re.compile(r"old\s*->\s*new", re.I), "old-to-new history"),
    Rule(re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b"), "dated note"),
    Rule(re.compile(r"YOUR-"), "placeholder"),
    Rule(re.compile(r"TODO\(", re.I), "unowned marker"),
    Rule(re.compile(r"\bFIXME\b", re.I), "unowned marker"),
    # A vocabulary filter alone lets the history through wherever it avoids the
    # banned words, so the two shapes history takes are named as well: what the
    # code used to say, and what a rejected alternative would have done.
    Rule(re.compile(r"\bused to (?:read|be|carry|say)\b"
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

# The false positives, one test per entry: a token shaped like a tag that names
# a licence, a digest, an object store, an address family, a contrast level, a
# projection, a percentile or a heading level is not lane vocabulary.
TAG_NOT_A_TAG = re.compile(
    r"^(?:CC0|MD5|SHA1|S3|IPv4|IPv6|AA|AAA|EPSG|WGS84|GDA94|GDA2020|UTM"
    r"|H1|H2|H3|H4|H5|H6|P50|P95|P99|L1|L2|L3)$")
# A station, site or survey id is data the corpus carries rather than a work
# item, so the words that name one excuse the token beside them.
TAG_NEAR_AN_ID = re.compile(
    r"\b(?:station|stations|site|sites|id|ids|identifier|identifiers|survey"
    r"|surveys|code|codes|Wp|Vulcan)\b|\bau\.[a-z]", re.I)


def work_item_tags(text):
    """Every work-item tag in a bare comment, as (match, tag)."""
    found = []
    for match in TAG_PATTERN.finditer(text):
        tag = next(group for group in match.groups() if group)
        window = text[max(0, match.start() - WINDOW):match.end() + WINDOW]
        if all(TAG_NOT_A_TAG.match(part.strip()) for part in re.split(r"[/,]", tag)):
            continue
        if TAG_NEAR_AN_ID.search(window):
            continue
        found.append((match, tag))
    return found


# COMMENTED-OUT CODE. A comment line that parses as an assignment, a call
# statement, a declaration, a return or a control keyword is code that was
# switched off rather than deleted, and git is where it belongs. One line must
# look like code unambiguously; a run of three or more lines that each END the
# way code ends is caught even when no single line would be, which is how a
# commented-out template literal of markup is found.
CODE_LINE = tuple(re.compile(p) for p in (
    r"^(?:const|let|var)\s+[\w$\[\]{},\s]+=\s*\S",
    r"^(?:export\s+)?(?:async\s+)?function\s*[\w$]*\s*\(",
    r"^class\s+[\w$]+\s*(?:extends\s+[\w$.]+\s*)?\{",
    r"^(?:\}\s*)?(?:if|for|while|switch|catch)\s*\(",
    r"^(?:\}\s*)?else\s*(?:\{|if\s*\()",
    r"^return\b[^.!?]*;\s*$",
    r"^(?:await\s+|new\s+)?[\w$][\w$.\[\]'\"]*\s*(?:\+|\|\||\?\?)?=[^=~>]\s*\S.*[;,{]\s*$",
    r"^(?:await\s+|new\s+)?[\w$][\w$.]*\(.*\)\s*[;,)]\s*$",
    r"^\.[\w$]+\(.*\)",
    r"^(?:def\s+\w+\s*\(|import\s+[\w.]+\s*$|from\s+[\w.]+\s+import\s)",
    r"^<script\b[^>]*>\s*(?:</script>)?\s*$",
    r"^(?:L\.map|fetch)\(\s*['\"`\w$]",
))
# The looser tell, only ever counted in a run: a line that ends the way a
# statement or a block ends, or opens a markup tag. Prose wraps mid-sentence.
CODE_RUN_LINE = re.compile(r"[;{}]\s*$|^</?[a-zA-Z][\w-]*[\s>]|^\}\)?[;,]?\s*$")
CODE_RUN = 3

LEADERS = ("<!--", "-->", "/*", "*/", "//", "*", "#")


def bare_line(line):
    stripped = line.strip()
    changed = True
    while changed:
        changed = False
        for lead in LEADERS:
            if stripped.startswith(lead):
                stripped = stripped[len(lead):].strip()
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
        run = run + 1 if CODE_RUN_LINE.search(line) else 0
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
    "index.html": 18_000,
    "about.html": 8_000,
    "add-survey.html": 8_000,
    "releases.html": 5_000,
    "brand.html": 3_000,
    "404.html": 1_500,
}
SHIPPED_JS_CAP = 232_000


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


def test_each_false_positive_on_the_tag_list_stays_clean(tmp_path):
    """One case per entry on the exemption list: a token shaped like a tag that names a thing."""
    cases = [
        "CC0: a dedication is not a licence with conditions.",
        "MD5: the digest the manifest carries beside the sha256.",
        "S3: the object store the mirror writes to.",
        "IPv4: the address family the edge truncates to /24.",
        "IPv6: the address family the edge truncates to /48.",
        "AA: the contrast floor every text pair must clear.",
        "AAA: the contrast level the large type clears.",
        "EPSG4326: the coordinate reference the corpus publishes in.",
        "WGS84: the datum every published position is on.",
        "GDA94: the datum a custodian record may arrive on.",
        "GDA2020: the datum a custodian record may arrive on.",
        "UTM55: the projected grid a custodian record may arrive on.",
        "H1: one per document, and the page title is it.",
        "H2: the section heading level the pages use.",
        "H3: the subsection heading level the pages use.",
        "H4: a heading level the emitted pages do not reach.",
        "H5: a heading level the emitted pages do not reach.",
        "H6: a heading level the emitted pages do not reach.",
        "P50: the median build time the profile reports.",
        "P95: the tail the build budget is set against.",
        "P99: the tail the alert threshold is set against.",
        "L1: the data level a raw time series is served at.",
        "L2: the data level a processed product is served at.",
        "L3: the data level a model is served at.",
        "The station id RD18-007 rides every row.",
        "Site A1 is the reference the survey record names.",
    ]
    for i, case in enumerate(cases):
        f = tmp_path / f"case{i}.js"
        f.write_text(f"// {case}\nvar a = 1;\n", encoding="utf-8")
        assert not offences([f]), f"the tag rule flagged a false positive: {case}"


def test_history_and_alternatives_narrative_is_caught(tmp_path):
    cases = [
        "The label used to read Sites; the tree is the reason it does not.",
        "The row used to be the survey's, and the station's is the correct home.",
        "A graph would have needed a host per row.",
        "Previously the counter was rebuilt on every keystroke.",
        "The chooser no longer reads the tree state.",
        "The digest is read from the manifest instead of the old per-file scan.",
        "The value is read from the record rather than the old constant.",
        "Historically the badge sat on the card.",
        "Originally the panel carried three tiles.",
    ]
    for i, case in enumerate(cases):
        f = tmp_path / f"hist{i}.js"
        f.write_text(f"// {case}\nvar a = 1;\n", encoding="utf-8")
        hits = offences([f])
        assert hits and "history" in hits[0], f"the history rule missed: {case}"


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
