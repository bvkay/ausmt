"""contract/generate.py CLI argument handling (Invariant 10).

Before this test: generate.py had no argparse, so `if "--check" in argv:` was the ONLY branch test —
ANY other argv (no args, --write, a typo, or --help) fell through to the unconditional write at the
bottom of main(), silently rewriting engine/extract/_contract.py + portal/src/contract.js. Running
`python contract/generate.py --help` to "just see usage" rewrote the generated files.

Fails if: `--help` (or no args, or an unknown flag) exits 0 and/or touches either generated file. Proven
non-vacuous by asserting BOTH the exit code AND that mtime+bytes of both generated files are byte-for-byte
unchanged after the subprocess call — a regression to the old fall-through-to-write behaviour changes the
mtime even when the bytes end up identical (write always re-writes), so this catches that too.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                # ausmt monorepo root (engine/tests -> engine -> ausmt)
GEN = ROOT / "contract" / "generate.py"
PY_OUT = ROOT / "engine" / "extract" / "_contract.py"
JS_OUT = ROOT / "portal" / "src" / "contract.js"


def _snapshot():
    return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (PY_OUT, JS_OUT)}


def _run(*args):
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True, cwd=str(ROOT))


def test_help_does_not_write():
    before = _snapshot()
    r = _run("--help")
    after = _snapshot()
    assert r.returncode != 0, f"--help must not exit 0 (stdout={r.stdout!r} stderr={r.stderr!r})"
    assert after == before, "generate.py --help must write NOTHING (mtime+bytes unchanged)"


def test_no_args_prints_usage_and_writes_nothing():
    before = _snapshot()
    r = _run()
    after = _snapshot()
    assert r.returncode == 2, f"no-args must exit 2, got {r.returncode} (stderr={r.stderr!r})"
    assert after == before, "generate.py with no args must write NOTHING"


def test_unknown_flag_writes_nothing():
    before = _snapshot()
    r = _run("--bogus")
    after = _snapshot()
    assert r.returncode == 2, f"unknown flag must exit 2, got {r.returncode} (stderr={r.stderr!r})"
    assert after == before, "generate.py --bogus must write NOTHING"


def test_check_mode_exit_codes_unaffected():
    # --check keeps its exact pre-existing behaviour/exit codes (CI calls --check only; see workflows).
    r = _run("--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in sync" in (r.stdout + r.stderr)


def test_write_mode_reproduces_byte_identical_output():
    # --write is the old no-arg behaviour, explicit now. Round-trip: write, then --check must pass,
    # and the CONTENT must be identical to what was already committed (columns.json hasn't changed).
    # Compare with universal newlines: generate.py writes "\n" via Path.write_text regardless of
    # platform, but the committed files may carry CRLF from a Windows checkout — that's a line-ending
    # artifact of the checkout, not something --write is responsible for reproducing byte-for-byte.
    before = _snapshot()
    r = _run("--write")
    assert r.returncode == 0, r.stdout + r.stderr
    after = _snapshot()
    assert after[PY_OUT][1].replace(b"\r\n", b"\n") == before[PY_OUT][1].replace(b"\r\n", b"\n"), \
        "generated _contract.py content drifted"
    assert after[JS_OUT][1].replace(b"\r\n", b"\n") == before[JS_OUT][1].replace(b"\r\n", b"\n"), \
        "generated contract.js content drifted"
    # And --check must now report in-sync (the real invariant this round-trip is guarding).
    r2 = _run("--check")
    assert r2.returncode == 0, r2.stdout + r2.stderr
