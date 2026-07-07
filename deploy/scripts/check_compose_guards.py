#!/usr/bin/env python3
"""C33 compose-guard proof (semantic).

This is NOT a substitute for `docker compose config` — the repo's CI
(.github/workflows/deploy-images.yml) runs the real thing on every push, and an operator with the
compose CLI should run `docker compose -f compose.yaml config` themselves. This script exists so the
C33 `${VAR:?}`->`${VAR:-}` guard change can be proven *deterministically* on a box where the docker
compose CLI is not installed, by implementing compose's documented variable-interpolation rules and
reporting which variables would ABORT config for a given environment.

It reproduces exactly these Compose interpolation forms
(https://docs.docker.com/reference/compose-file/interpolation/):

    ${VAR}            -> value, or "" if unset
    ${VAR:-default}   -> value if set AND non-empty, else `default`
    ${VAR-default}    -> value if set (even if empty), else `default`
    ${VAR:?err}       -> value if set AND non-empty, else ABORT with `err`
    ${VAR?err}        -> value if set (even if empty), else ABORT with `err`
    ${VAR:+repl}      -> `repl` if set AND non-empty, else ""
    ${VAR+repl}       -> `repl` if set, else ""

`docker compose config` fails iff at least one `:?`/`?` guard trips for the given environment (that
is precisely the "required variable is missing" error the 2026-07-06 deploy hit). So: enumerate the
guards in the file, evaluate them against a supplied environment, and report every abort.

Usage:
    python3 check_compose_guards.py <compose.yaml> KEY=VALUE [KEY=VALUE ...]
    python3 check_compose_guards.py --self-test        # runs the C33 assertions, exits non-zero on fail

Exit code: 0 if config would resolve (no guard trips), 1 if any guard trips (or a self-test fails).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ${ NAME [ (:?) (- | ? | +) WORD ] }  — the op group captures an optional leading ':' plus one of
# -/?/+; WORD runs (non-greedy in effect, [^}]) to the matching '}'. Bare ${NAME} => op/word empty.
_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-?+])?([^}]*)\}")


class GuardTrip(Exception):
    def __init__(self, var: str, message: str) -> None:
        super().__init__(message)
        self.var = var
        self.message = message


def _resolve_token(name: str, op: str, word: str, env: dict[str, str]) -> str:
    """Resolve a single ${...} token per compose rules. Raises GuardTrip on a tripped :?/? guard."""
    present = name in env
    value = env.get(name, "")
    nonempty = present and value != ""

    if op in ("", None):
        return value
    colon = op.startswith(":")
    kind = op[-1]
    # `:X` tests set-AND-non-empty; `X` tests merely set.
    satisfied = nonempty if colon else present

    if kind == "-":
        return value if satisfied else word
    if kind == "+":
        return word if satisfied else ""
    if kind == "?":
        if satisfied:
            return value
        raise GuardTrip(name, word or f"required variable {name} is missing")
    raise ValueError(f"unknown interpolation op {op!r}")


def _strip_comments(text: str) -> str:
    """Drop YAML comments so ${VAR:?...} written inside a `#` comment (as documentation) is not
    mistaken for a live guard. Compose interpolates VALUES after YAML parsing, so comments never
    reach the interpolator; this mirrors that. Heuristic (sufficient for this compose file, which
    has no '#' inside a quoted scalar on a guarded line): a '#' preceded by whitespace or at
    line-start starts a comment; a leading-# line is wholly a comment."""
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Inline comment: first ' #' (space-hash) outside the unlikely event of a quoted '#'.
        # This compose file never quotes a '#', so a plain find is faithful.
        idx = line.find(" #")
        if idx != -1:
            line = line[:idx]
        out_lines.append(line)
    return "\n".join(out_lines)


def find_guard_trips(text: str, env: dict[str, str]) -> list[GuardTrip]:
    """Return every :?/? guard in `text` that would trip for `env` (compose aborts if any do).

    Comments are stripped first: compose interpolates parsed VALUES, not raw file text, so a
    ${VAR:?...} appearing in a `#` documentation comment is not a live guard."""
    trips: list[GuardTrip] = []
    for m in _TOKEN.finditer(_strip_comments(text)):
        name, op, word = m.group(1), m.group(2) or "", m.group(3)
        try:
            _resolve_token(name, op, word, env)
        except GuardTrip as g:
            trips.append(g)
    return trips


def _parse_env_args(args: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(f"bad KEY=VALUE arg: {a!r}")
        k, v = a.split("=", 1)
        env[k] = v
    return env


def _self_test() -> int:
    """C33 assertions. Fails if the guard-scoping regressed."""
    here = Path(__file__).resolve().parent
    compose = (here.parent / "compose.yaml").read_text(encoding="utf-8")
    failures: list[str] = []

    # (1) With ONLY the two always-required vars set, the base config must resolve (no guard trips).
    #     This is the C33 fix: portal-only operation needs only AUSMT_DATA_DIR + OWNER.
    minimal = {"AUSMT_DATA_DIR": "/srv/ausmt", "OWNER": "someowner"}
    trips = find_guard_trips(compose, minimal)
    if trips:
        failures.append(
            "FAIL: base config still trips guards with only AUSMT_DATA_DIR+OWNER set: "
            + ", ".join(sorted({t.var for t in trips}))
        )

    # (2) The two always-required vars MUST still be guarded (removing them must still abort). Prove
    #     the guard scoping did not throw the baby out — AUSMT_DATA_DIR and OWNER stay :?.
    for required in ("AUSMT_DATA_DIR", "OWNER"):
        env = dict(minimal)
        del env[required]
        trips = find_guard_trips(compose, env)
        if not any(t.var == required for t in trips):
            failures.append(f"FAIL: {required} is no longer a hard :? guard (should still abort)")

    # (3) The two gateway vars must NOT be hard guards any more (that is the whole fix).
    for softened in ("AUSMT_SUBMIT_KEY", "AUSMT_CODE_DIR"):
        trips = find_guard_trips(compose, minimal)
        if any(t.var == softened for t in trips):
            failures.append(f"FAIL: {softened} still trips a :? guard (C33 wanted :- default)")

    if failures:
        print("\n".join(failures))
        return 1
    print("C33 compose-guard self-test PASS:")
    print("  - base config resolves with only AUSMT_DATA_DIR + OWNER set (no guard trips)")
    print("  - AUSMT_DATA_DIR and OWNER remain hard :? guards (still abort when unset)")
    print("  - AUSMT_SUBMIT_KEY and AUSMT_CODE_DIR are no longer hard guards (softened to :-)")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--self-test":
        return _self_test()

    compose_path = Path(argv[0])
    env = _parse_env_args(argv[1:])
    text = compose_path.read_text(encoding="utf-8")
    trips = find_guard_trips(text, env)
    if trips:
        print(f"{compose_path.name}: config would ABORT — {len(trips)} guard(s) trip:")
        for t in sorted(trips, key=lambda g: g.var):
            print(f"  {t.var}: {t.message}")
        return 1
    print(f"{compose_path.name}: config would RESOLVE (no :?/? guard trips) for the given env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
