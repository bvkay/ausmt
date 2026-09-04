"""The twin of engine/tests/test_cli_help_identity.py, over the trees the engine image does not ship.

A module whose docstring is printed by --help has a user interface no AST guard can see: blanking
docstrings hides exactly the bytes an operator reads, so a sweep over comment text can eat the leading
hyphen off a long flag and leave the tool telling an operator to type a flag argparse will refuse.

Five guards over deploy/, gateway/, portal/ and contract/:
  1. no comment or docstring anywhere spells a long option with ONE hyphen;
  2. every module that builds an argparse parser answers --help, and every long option it declares
     appears in that output with BOTH hyphens;
  3. every usage line inside a module docstring names only options that module's parser declares;
  4. every such usage line is RUN against that module's own parser, with the parse stopped the
     instant it returns, so a line that would exit 2 fails here and not in a terminal;
  5. no usage line writes a value that is a truncation of the example the same module's help
     offers, which is what a cut token leaves when it takes the end off a value.

This module runs on a checkout (it reads sibling trees), which is where the deploy and gateway suites
run. A module whose --help needs a third-party import that this environment does not carry is counted
and passed over rather than skipped, so the stack-less runner never grows a new skip reason; the count
is asserted so the guard cannot go quiet.

Fails if: a long option is spelled with one hyphen in prose, OR a parser stops answering --help, OR a
declared option is missing from its own help, OR a docstring usage line names an undeclared option.
"""
import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent
ROOT = DEPLOY.parent
SELF = Path(__file__).name

TREES = (DEPLOY, ROOT / "gateway", ROOT / "portal", ROOT / "contract")
SUFFIXES = (".py", ".sh", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".md", ".conf", ".example",
            ".service", ".timer", ".js")
SKIP_PARTS = {"__pycache__", "node_modules", ".git", "vendor", "vendored_validation", "site"}

LONG_OPTION = re.compile(r"--([a-z][a-z0-9]*(?:-[a-z0-9]+)*)")
# A short flag is ONE character, so a name of three or more cannot be one. At four, `--tag` written
# `-tag` was invisible here.
MIN_LONG_NAME = 3
DECLARED = re.compile(r"add_argument\(\s*[\"'](--?[A-Za-z][\w-]*)[\"']")
# A single-hyphen spelling is only a scar in PROSE. A shell default expansion (${X:-y}), a quoted
# literal ("-text") and a backticked directive (`-include .env`) all write the same characters and
# mean something else, so quoted runs are blanked and an expansion colon is excluded.
QUOTED_RUN = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|'[^'\n]*'")


def unquoted(line):
    return QUOTED_RUN.sub(lambda m: "q" * len(m.group(0)), line)


# Every module here answers --help from the standard library alone today. The floor is stated so a
# new third-party import cannot quietly empty this guard.
HELP_FLOOR = 5


def commented_files():
    out = []
    for tree in TREES:
        if not tree.exists():
            continue
        for path in sorted(tree.rglob("*")):
            if not path.is_file() or SKIP_PARTS & set(path.parts):
                continue
            if path.suffix.lower() in SUFFIXES:
                out.append(path)
    return out


def long_option_universe():
    names = set()
    for path in commented_files():
        try:
            names.update(LONG_OPTION.findall(path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return {n for n in names if len(n) >= MIN_LONG_NAME}


def argparse_modules():
    out = []
    for path in commented_files():
        if path.suffix != ".py" or path.name == SELF:
            continue
        try:
            if builds_a_parser(path.read_text(encoding="utf-8")):
                out.append(path)
        except (UnicodeDecodeError, OSError, SyntaxError):
            continue
    return out


def builds_a_parser(text):
    """True when the module CALLS argparse.ArgumentParser. Read from the syntax tree, because a
    fixture that WRITES a parser into a string carries the same characters and has no interface."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "ArgumentParser":
                return True
    return False


def declared_options(path):
    return set(DECLARED.findall(path.read_text(encoding="utf-8")))


def run_help(path):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "engine"), env.get("PYTHONPATH", "")])
    env["COLUMNS"] = "100"
    proc = subprocess.run([sys.executable, os.path.relpath(path, ROOT), "--help"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr


def single_hyphen_spelling(names):
    """The pattern that reads a long option written with ONE hyphen, built from the names in play."""
    return re.compile(r"(?<![-\w:$])-(%s)\b" % "|".join(sorted(map(re.escape, names))))


def test_no_comment_spells_a_long_option_with_one_hyphen():
    names = long_option_universe()
    assert names, "no long option was found, so this guard would pass over nothing"
    pattern = single_hyphen_spelling(names)
    hits = []
    for path in commented_files():
        if path.name == SELF:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(lines, 1):
            for match in pattern.finditer(unquoted(line)):
                hits.append("%s:%d: -%s: %s"
                            % (path.relative_to(ROOT), lineno, match.group(1), line.strip()[:100]))
    assert not hits, (
        f"{len(hits)} line(s) spell a long option with one hyphen, which is what an operator is "
        "then told to type:\n" + "\n".join(hits))


def test_every_argparse_module_answers_help_and_names_its_options():
    modules = argparse_modules()
    assert modules, "no argparse module was found, so this guard would pass over nothing"
    ran, broken, unavailable = 0, [], []
    for path in modules:
        code, text = run_help(path)
        rel = path.relative_to(ROOT)
        if "ModuleNotFoundError" in text or "ImportError" in text:
            unavailable.append(str(rel))
            continue
        if not text.strip():
            broken.append(f"{rel}: --help printed nothing (exit {code})")
            continue
        ran += 1
        for option in sorted(declared_options(path)):
            if option.startswith("--") and option not in text:
                broken.append(f"{rel}: --help does not carry {option}")
    assert not broken, (
        "an argparse module stopped telling an operator what it accepts:\n" + "\n".join(broken))
    assert ran >= HELP_FLOOR, (
        f"only {ran} module(s) answered --help here (floor {HELP_FLOOR}); the rest could not import "
        "in this environment, so this guard is measuring almost nothing: " + ", ".join(unavailable))


# THE USAGE LINE, RUN. Reading the option NAMES on a usage line is not enough: a value eaten out
# of one leaves every name intact. So the guard pastes the line. It is tokenised the way a shell
# tokenises it, an optional group's brackets are dropped, a <placeholder> collapses to one token,
# and the module runs with argparse stopped the instant the parse returns: the parser answers
# exactly as it would for an operator and no action runs. The working directory is read off the
# line itself, so `python scripts/verify.py` runs from the directory that makes that path true.
PLACEHOLDER = re.compile(r"<[^<>\n]*>")
DRY_PARSE = (
    "import argparse, runpy, sys\n"
    "_args = argparse.ArgumentParser.parse_args\n"
    "_known = argparse.ArgumentParser.parse_known_args\n"
    "def _dry(self, args=None, namespace=None):\n"
    "    _args(self, args, namespace)\n"
    "    raise SystemExit(0)\n"
    "def _dry_known(self, args=None, namespace=None):\n"
    "    _known(self, args, namespace)\n"
    "    raise SystemExit(0)\n"
    "argparse.ArgumentParser.parse_args = _dry\n"
    "argparse.ArgumentParser.parse_known_args = _dry_known\n"
    "mode, target = sys.argv[1], sys.argv[2]\n"
    "sys.argv = [target] + sys.argv[3:]\n"
    "if mode == 'module':\n"
    "    runpy.run_module(target, run_name='__main__', alter_sys=True)\n"
    "else:\n"
    "    runpy.run_path(target, run_name='__main__')\n")
# An example value a module offers an operator for one of its own options.
EXAMPLE = re.compile(r"\be\.g\.\s+([^\s,;)\]'\"]+)")
# The floor under the usage lines that actually ran, so an import failure cannot empty this guard.
USAGE_FLOOR = 6


def usage_invocations(path):
    """(line, cwd, mode, target, tokens) for every usage line in this module's docstring that
    invokes this module with options."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    if not doc:
        return []
    invoke = re.compile(r"(?:\bpython3?\s+)?(?:-m\s+(?P<module>[\w.]*%s)|(?P<path>[\w./]*%s))"
                        % (re.escape(path.stem), re.escape(path.name)))
    found = []
    for line in doc.splitlines():
        match = invoke.search(line)
        if not match:
            continue
        rest = line[match.end():].split("#")[0]
        if not re.search(r"(?<![\w-])--?[A-Za-z]", rest):
            continue
        text = PLACEHOLDER.sub("1", rest).replace("[", " ").replace("]", " ")
        try:
            tokens = shlex.split(text)
        except ValueError:
            continue
        if match.group("module"):
            mode, target = "module", match.group("module")
            rel = target.replace(".", "/") + ".py"
        else:
            mode, target = "path", match.group("path")
            rel = target
        cwd = path.parents[len(rel.strip("./").split("/")) - 1]
        if (cwd / rel).resolve() != path.resolve():
            continue
        found.append((line.strip(), cwd, mode, target, tokens))
    return found


def dry_parse(cwd, mode, target, tokens):
    """Run one usage line with the parse stopped the instant it returns."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "engine"), env.get("PYTHONPATH", "")])
    env["COLUMNS"] = "100"
    proc = subprocess.run([sys.executable, "-c", DRY_PARSE, mode, target] + tokens,
                          cwd=cwd, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr


def declared_examples(path):
    """option -> the example value this module's OWN help text offers for it."""
    out = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return out
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument":
            continue
        names = [a.value for a in node.args if isinstance(a, ast.Constant)
                 and isinstance(a.value, str) and a.value.startswith("--")]
        for keyword in node.keywords:
            if keyword.arg != "help" or not isinstance(keyword.value, ast.Constant):
                continue
            example = EXAMPLE.search(str(keyword.value.value))
            if names and example:
                out[names[0]] = example.group(1).rstrip(".,;)")
    return out


def truncated_values(path):
    """Every place a module's docstring writes a value for one of its own options that is a
    TRUNCATION of the example its help offers. A cut token takes the end off the value and leaves
    the option name standing, which no name check can see."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    hits = []
    for option, example in sorted(declared_examples(path).items()):
        shell = option.lstrip("-").replace("-", "_").upper()
        patterns = (r"%s[ =]+([^\s'\"]+)" % re.escape(option),
                    r"(?<![\w-])%s=([^\s'\"]+)" % re.escape(shell))
        for pattern in patterns:
            for match in re.finditer(pattern, doc):
                value = match.group(1).rstrip(".,;)")
                if not value or value == example:
                    continue
                if example.startswith(value) or example.endswith(value):
                    hits.append("%s: a usage line writes %s %s, but this module's own help says "
                                "e.g. %s" % (path.name, option, value, example))
    return hits


def test_every_usage_line_in_a_module_docstring_parses():
    """The pasted line, run. A usage line that names only declared options can still exit 2."""
    ran, broken, unavailable = 0, [], []
    for path in argparse_modules():
        for line, cwd, mode, target, tokens in usage_invocations(path):
            code, text = dry_parse(cwd, mode, target, tokens)
            if "ModuleNotFoundError" in text or "ImportError" in text:
                unavailable.append("%s: %s" % (path.relative_to(ROOT), line))
                continue
            ran += 1
            if code != 0:
                broken.append("%s: `%s` exits %d when pasted:\n    %s"
                              % (path.relative_to(ROOT), line, code, text.strip()[-300:]))
    assert not broken, (
        "a documented usage line does not parse against its own module's parser:\n"
        + "\n".join(broken))
    assert ran >= USAGE_FLOOR, (
        "only %d usage line(s) ran here (floor %d), so this guard is measuring almost nothing: %s"
        % (ran, USAGE_FLOOR, ", ".join(unavailable)))


def test_no_usage_line_writes_a_truncation_of_its_own_example():
    """The other half of a usage line: its values. A value that is a prefix or a suffix of the
    example the same module's help offers is what a cut token leaves behind, and an operator who
    pastes it cuts a release directory, a tag or a path named after half a value."""
    hits = []
    for path in argparse_modules():
        hits += truncated_values(path)
    assert not hits, "\n".join(hits)


def test_every_usage_line_in_a_module_docstring_names_declared_options():
    checked, broken = 0, []
    for path in argparse_modules():
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:
            continue
        if not doc:
            continue
        options = declared_options(path)
        token = re.compile(r"\b(?:python3?\s+(?:-m\s+)?)?[\w./]*%s\b|(?:-m\s+)[\w.]*%s\b"
                           % (re.escape(path.name), re.escape(path.stem)))
        for line in doc.splitlines():
            found = token.search(line)
            if not found:
                continue
            argv = line[found.end():].split("#")[0]
            names = re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", argv)
            if not names:
                continue
            checked += 1
            for name in names:
                if name not in options:
                    broken.append("%s: usage line names %s, which its parser does not declare: %s"
                                  % (path.relative_to(ROOT), name, line.strip()[:100]))
    assert checked, "no usage line was read, so this guard would pass over nothing"
    assert not broken, "\n".join(broken)


def test_a_three_character_long_option_written_with_one_hyphen_is_caught(tmp_path):
    """A short flag is one character, so a three-character name spelt with one hyphen is a scar and
    not a flag: `--tag` written `-tag` names an option cut_release.py does not declare, and a
    four-character floor could not see it. Both halves are held here: the floor admits the name, and
    the pattern built from it reads the damaged spelling out of a pasted usage line."""
    assert len({n for n in ("tag",) if len(n) >= MIN_LONG_NAME}) == 1, (
        "the floor no longer admits a three-character long option")
    pattern = single_hyphen_spelling({"tag", "data-dir"})
    f = tmp_path / "usage.md"
    f.write_text("    python scripts/cut_release.py -tag 2026-Q3\n"
                 "    python scripts/cut_release.py --tag 2026-Q3\n", encoding="utf-8")
    hits = [line for line in f.read_text(encoding="utf-8").splitlines()
            if pattern.search(unquoted(line))]
    assert len(hits) == 1 and "-tag 2026-Q3" in hits[0], hits
