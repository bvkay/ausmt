"""M7 (code-health review §6): the ONE canonical validator argv is single-sourced.

Both the C10 submission runner (runner._run_validator) and the C31 metadata-edit runner
(edit._run_validator) invoke `validate_survey.py` as a subprocess. Before M7 each assembled its own
argv — one positional-first, one --json-first — the exact class of seam whose argv bug quarantined
every real submission on 2026-07-06. M7 routes both through runner.validator_argv().

These tests pin:
  1. the canonical SHAPE (positional-first: <folder> then --json <file>);
  2. that edit.py actually calls the shared helper (mutate the helper -> the edit argv moves too);
  3. that neither call site hand-builds its own argv (a source-text pin so a future revert to a
     bespoke argv goes RED here).

The real-vendored-validator oracles (test_runner.py / test_edit_runner.py) prove this canonical
shape against the ACTUAL validate_survey.py CLI; these tests pin the single-source property itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

from gateway.runner import edit, runner


def test_validator_argv_canonical_shape():
    # FAILS IF the canonical argv shape changes: [python, <validator>, <folder positional>, --json,
    # <report file>]. This is the positional-first form argparse pins the `folder` positional to; the
    # 2026-07-06 ship-blocker was exactly a wrong order (folder consumed as the --json value, the
    # required positional missing, argparse exit 2, every submission quarantined).
    vfile = Path("/srv/surveys/_validation/validate_survey.py")
    target = Path("/gw/quarantine/abc/package/demo-survey")
    report = Path("/gw/quarantine/abc/reports/validate.json")
    argv = runner.validator_argv(vfile, target, report)
    assert argv == [sys.executable, str(vfile), str(target), "--json", str(report)]
    # The report file is the --json VALUE, the folder is the positional BEFORE it (never swapped).
    assert argv[2] == str(target), "folder must be the positional, not the --json value"
    assert argv[3] == "--json" and argv[4] == str(report)


def test_runner_and_edit_share_one_argv_builder():
    # Single-source proof: edit.py imports validator_argv FROM runner (not a private copy). This is the
    # symbol identity that makes the whole seam single-sourced — if a refactor gave edit.py its own
    # builder, this identity check goes RED. (edit._run_validator does `from .runner import
    # ..., validator_argv`, so the name it binds must BE runner.validator_argv.)
    from gateway.runner.runner import validator_argv as runner_builder

    src = Path(edit.__file__).read_text(encoding="utf-8")
    assert "validator_argv" in src, "edit.py no longer references the shared validator_argv helper"
    # And the two modules resolve the SAME function object (edit imports it lazily inside
    # _run_validator; re-run that import here to bind the exact symbol edit uses).
    from gateway.runner.runner import validator_argv as edit_sees
    assert edit_sees is runner_builder


def test_neither_call_site_hand_builds_a_validator_argv():
    # Source-text pin (M7): a future edit that reverts to an inline `[sys.executable, ..., "--json",
    # ...]` argv at either call site — re-opening the drift M7 closed — goes RED here. We assert the
    # tell-tale inline-argv literal is absent from BOTH runner._run_validator and edit._run_validator.
    for mod in (runner, edit):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        # The only sanctioned place `sys.executable, str(...validate` may appear is INSIDE
        # validator_argv (runner.py). Everywhere else it would be a re-introduced bespoke argv.
        bespoke = 'sys.executable, str(vfile)' in src or 'sys.executable, str(validator_file), str(target), "--json"' in src.replace(
            "return [sys.executable, str(validator_file), str(target_dir), \"--json\", str(report_path)]", "")
        assert not bespoke, (
            f"{Path(mod.__file__).name} hand-builds a validator argv again — route it through "
            "runner.validator_argv (M7 single-source).")
