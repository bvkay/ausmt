"""The twin of engine/tests/test_cli_help_identity.py, over the trees the engine image does not ship.

A module whose docstring is printed by --help has a user interface no AST guard can see: blanking
docstrings hides exactly the bytes an operator reads, so a sweep over comment text can eat the leading
hyphen off a long flag and leave the tool telling an operator to type a flag argparse will refuse.

Three guards over deploy/, gateway/, portal/ and contract/:
  1. no comment or docstring anywhere spells a long option with ONE hyphen;
  2. every module that builds an argparse parser answers --help, and every long option it declares
     appears in that output with BOTH hyphens;
  3. every usage line inside a module docstring names only options that module's parser declares.

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
MIN_LONG_NAME = 4
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


def test_no_comment_spells_a_long_option_with_one_hyphen():
    names = long_option_universe()
    assert names, "no long option was found, so this guard would pass over nothing"
    pattern = re.compile(r"(?<![-\w:$])-(%s)\b" % "|".join(sorted(map(re.escape, names))))
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
