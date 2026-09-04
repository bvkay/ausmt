"""A module whose docstring IS its user interface cannot be guarded by blanking docstrings.

`python scripts/verify.py --help` and `python tests/ci_check_skips.py --help` print the module's own
prose to an operator, and the usage block inside that prose is meant to be copied and pasted. A
behaviour guard that compares ASTs with docstrings blanked sees none of that, so a sweep over comment
text can silently change what the tool tells its operator: a leading hyphen eaten off a long flag
turns `--data-dir` into `-data-dir`, which names a flag argparse does not have.

Three guards, over engine/ and contract/ (the two trees the engine image ships):
  1. no comment or docstring anywhere spells a long option with ONE hyphen;
  2. every module that builds an argparse parser answers --help, and every long option it declares
     appears in that output with BOTH hyphens;
  3. every usage line inside a module docstring names only options that module's parser declares,
     so a pasted usage line cannot exit 2.
The two operator-facing modules carry their captured text as a pin on top of that.

IMAGE TOPOLOGY. Every path read here is under engine/ or contract/, which deploy/docker/engine.Dockerfile
COPYs to /app/engine and /app/contract, so this module runs identically on a checkout and inside the
engine image. The deploy twin covers deploy/, gateway/ and portal/tools.

Fails if: a long option is spelled with one hyphen in prose, OR a parser stops answering --help, OR a
declared option is missing from its own help, OR a docstring usage line names an undeclared option, OR
the pinned operator text changes.
"""
import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
ROOT = ENGINE.parent
CONTRACT = ROOT / "contract"
SELF = Path(__file__).name

# The trees this module reads, and the suffixes a comment can live in.
TREES = (ENGINE, CONTRACT)
SUFFIXES = (".py", ".sh", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".md", ".conf", ".example")
SKIP_PARTS = {"__pycache__", "node_modules", ".git"}

# A long option is two hyphens and a lower-case name. The universe is every such token written
# anywhere in these trees, prose included: a flag another tool owns (`--incremental`, `--products`)
# is quoted in this tree's prose and loses its hyphen the same way one of our own does.
LONG_OPTION = re.compile(r"--([a-z][a-z0-9]*(?:-[a-z0-9]+)*)")
# The single-hyphen spelling of such a name. Short flags are one or two characters, so a name of
# four or more cannot be one: this reads only the spellings no parser could accept.
MIN_LONG_NAME = 4
DECLARED = re.compile(r"add_argument\(\s*[\"'](--?[A-Za-z][\w-]*)[\"']")
# A single-hyphen spelling is only a scar in PROSE. A shell default expansion (${X:-y}), a quoted
# literal ("-text") and a backticked directive (`-include .env`) all write the same characters and
# mean something else, so quoted runs are blanked and an expansion colon is excluded.
QUOTED_RUN = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|'[^'\n]*'")


def unquoted(line):
    return QUOTED_RUN.sub(lambda m: "q" * len(m.group(0)), line)


# The skip tripwire's argparse description says what the tool is and nothing about where it
# came from; an operator reads this line and nothing else about the tool.
CI_CHECK_SKIPS_DESCRIPTION = "CI skip tripwire."
# verify.py passes __doc__ straight to argparse under RawDescriptionHelpFormatter, so its module
# docstring IS the body an operator reads. The digest pins those bytes; the two lines below are the
# ones a sweep ate a hyphen from, pinned in the clear so a failure names the damage rather than a hash.
VERIFY_DOC_SHA256 = "e3154a7588a10806d6514659b580054f328929bf04175b29b7ce130922f83db4"
VERIFY_DOC_LINES = (
    "--data-dir mode: validate an EXISTING build output dir (e.g. a deploy/Makefile rebuild-data run's",
    "    python scripts/verify.py [--surveys data] [--skip-tests]",
    "    python scripts/verify.py --data-dir /out/builds/20260705T120000Z",
)
# The same module's --data-dir helper names the flag its caller passes; that line lost its hyphen too.
VERIFY_SOURCE_LINES = (
    "    --surveys), ALSO run the cache-INDEPENDENT digest-consistency gate: the served-product digest",
)


def commented_files():
    out = []
    for tree in TREES:
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
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        names.update(LONG_OPTION.findall(text))
    return {n for n in names if len(n) >= MIN_LONG_NAME}


def argparse_modules():
    """Every module in these trees that builds a parser, found by reading the source rather than
    by a hand-kept list, so the next one joins the guard on the commit that adds it."""
    out = []
    for path in commented_files():
        if path.suffix != ".py" or path.name == SELF:
            continue
        if builds_a_parser(path.read_text(encoding="utf-8")):
            out.append(path)
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
    """--help for one module, run the way an operator runs it. COLUMNS is fixed so the wrapping
    argparse chooses cannot depend on the terminal the suite happens to run in."""
    cwd = ENGINE if path.is_relative_to(ENGINE) else ROOT
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ENGINE), env.get("PYTHONPATH", "")])
    env["COLUMNS"] = "100"
    proc = subprocess.run([sys.executable, os.path.relpath(path, cwd), "--help"],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr


def test_no_comment_spells_a_long_option_with_one_hyphen():
    """The regression this module exists for. A long flag written in prose at the head of a line
    is one gutter strip away from `-data-dir`, and the operator is then told a flag that does not
    exist. Read over the source bytes, not only over comments, because a usage block inside a
    docstring is prose the extractor reads and prose the operator copies."""
    names = long_option_universe()
    assert names, "no long option was found, so this guard would pass over nothing"
    pattern = re.compile(r"(?<![-\w:$])-(%s)\b" % "|".join(sorted(map(re.escape, names))))
    hits = []
    for path in commented_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        if path.name == SELF:
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
    broken = []
    for path in modules:
        code, text = run_help(path)
        rel = path.relative_to(ROOT)
        if not text.strip():
            broken.append(f"{rel}: --help printed nothing (exit {code})")
            continue
        for option in sorted(declared_options(path)):
            if option.startswith("--") and option not in text:
                broken.append(f"{rel}: --help does not carry {option}")
    assert not broken, (
        "an argparse module stopped telling an operator what it accepts:\n" + "\n".join(broken))


def test_every_usage_line_in_a_module_docstring_names_declared_options():
    """A usage line inside a module docstring is meant to be pasted. Every option token on one
    must be an option that module's parser declares, or the paste exits 2."""
    modules = argparse_modules()
    checked, broken = 0, []
    for path in modules:
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
            if not token.search(line):
                continue
            argv = line[token.search(line).end():].split("#")[0]
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


def test_the_operator_text_of_the_two_reference_tools_is_pinned():
    """verify.py and the skip tripwire are the two modules whose docstring an operator reads and
    copies. Their text is pinned here: a change to it is a change to a user interface and belongs
    in a commit that says so."""
    verify = ENGINE / "scripts" / "verify.py"
    doc = ast.get_docstring(ast.parse(verify.read_text(encoding="utf-8")))
    for line in VERIFY_DOC_LINES:
        assert line in doc, f"verify.py's operator text no longer carries: {line!r}"
    source = verify.read_text(encoding="utf-8")
    for line in VERIFY_SOURCE_LINES:
        assert line in source, f"verify.py no longer carries: {line!r}"
    got = hashlib.sha256(doc.encode("utf-8")).hexdigest()
    assert got == VERIFY_DOC_SHA256, (
        "verify.py's --help body changed. If that was deliberate, update VERIFY_DOC_SHA256 to "
        f"{got} in the same commit; if it was not, an operator is now reading something else.")
    code, text = run_help(verify)
    assert code == 0, f"verify.py --help exited {code}"
    assert doc in text, (
        "verify.py's --help no longer prints its docstring verbatim, so the pin above no longer "
        "measures what an operator sees")
    tripwire = ENGINE / "tests" / "ci_check_skips.py"
    code, text = run_help(tripwire)
    assert code == 0, f"ci_check_skips.py --help exited {code}"
    assert CI_CHECK_SKIPS_DESCRIPTION in text, (
        f"the skip tripwire's --help no longer carries {CI_CHECK_SKIPS_DESCRIPTION!r}")
    assert "--allow" in text and "\n-allow" not in text, (
        "the skip tripwire's --help names its repeatable flag with one hyphen")


def test_every_path_this_module_reads_is_shipped_in_the_engine_image():
    """engine/ and contract/ are the two trees the image copies, so this module runs identically
    inside the image. Anything else would skip or fail there."""
    outside = [str(p) for p in commented_files()
               if not any(p.resolve().is_relative_to(tree) for tree in TREES)]
    assert not outside, (
        "this module reads outside the trees the engine image ships:\n" + "\n".join(outside))
