"""C31 runner-side edit tests (design §3.1/§3.2 + adversarial-review fixes). These exercise
gateway.runner.edit DIRECTLY — the same in-suite-reaches-the-runner pattern as test_runner.py.
ruamel.yaml is a runner (engine-image) dependency; these tests run wherever ruamel is installed
(the ausmt env locally; the engine lock in CI's full lane).

Load-bearing tests here:
  - the §3.1 round-trip fidelity proof (comments + unknown key byte-identical across an edit);
  - review FIX 3, the parser differential (patched "on"/"no"/"12:34:56" must re-read as STRINGS
    under PyYAML safe_load — the reader the validator and build_portal use);
  - review FIX 2, scratch containment (nothing the merge does may touch the surveys tree);
  - the jobs/edit/ queue mechanics (claim-by-rename, done-file results) that FIX 1 moved the
    transport onto.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.runner import edit
from gateway.runner.runner import RunnerConfig

# A well-formed block-style survey.yaml with comments, an UNKNOWN custom key the form never models,
# a null field, and a block-scalar abstract. Mirrors the legitimate fidelity challenges of the real
# vulcan-2022 exemplar (comments + unknown keys + null + block scalar) WITHOUT its two source-level
# quirks that no YAML round-tripper preserves (manual intra-flow-map column alignment, and a
# pre-existing unquoted `LEMI (LC ISR, Lviv)` flow value whose internal comma any conformant parser —
# ruamel AND the PyYAML the validator uses — splits into a spurious key). See the residual note in
# edit._yaml() and the C31 report.
EXEMPLAR = """\
schema_version: "0.2"
slug: demo-survey-2026
project_name: Demo Survey            # human-readable name
version: 1.0.0
country: Australia
region: South Australia

organisation:
  name: University of Example
  ror: null                          # ROR URL when known

abstract: >
  A short paragraph describing the survey that a naive emitter would re-wrap but which
  must stay exactly as written, word for word, across the round trip.

identifiers:
  dataset_doi: null                  # none minted yet
  survey_pid: null

access:
  level: open
  embargo_until: null
  contact: null

license: CC-BY-4.0

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def _write_package(root: Path, slug: str = "demo-survey-2026",
                   yaml_text: str = EXEMPLAR) -> Path:
    pkg = root / "surveys" / slug
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    with open(pkg / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(yaml_text)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45\n  LONG=136:58:12\n>FREQ\n", encoding="utf-8")
    return pkg


def _cfg(tmp_path: Path, *, validator_path: str = "") -> RunnerConfig:
    """A RunnerConfig whose surveys_root is the tmp surveys-live and whose jobs dir (scratch home)
    is OUTSIDE it — the same topology as the real gw-runner container."""
    return RunnerConfig(
        incoming_dir=tmp_path / "gw" / "incoming",
        quarantine_dir=tmp_path / "gw" / "quarantine",
        jobs_dir=tmp_path / "gw" / "jobs",
        validator_path=validator_path,
        surveys_root=tmp_path / "surveys-live",
    )


def _merge(cfg: RunnerConfig, slug: str = "demo-survey-2026", **overrides) -> dict:
    job = {"kind": "merge", "slug": slug, "patch": {"region": "Northern Territory"},
           "bump": "patch", "note": "Corrected region.", "today": "2026-07-06"}
    job.update(overrides)
    scratch = cfg.jobs_dir / "edit" / "scratch" / "t"
    return edit._dispatch_edit(cfg, job, scratch)


# --------------------------------------------------------------------------------------------------
# §0.2 / §3.1 round-trip fidelity
# --------------------------------------------------------------------------------------------------
def test_noop_round_trip_is_byte_identical():
    # The floor the whole design rests on: loading and re-emitting an UNEDITED well-formed
    # survey.yaml is byte-for-byte identical (comments, null tokens, block scalar, unknown key all
    # preserved). FAILS IF the ruamel config drops the `null` token, re-wraps, or reindents.
    raw = EXEMPLAR.encode("utf-8")
    assert edit._dump_bytes(edit._load_bytes(raw)) == raw


def test_round_trip_fidelity_edit_touches_only_field_version_notes(tmp_path):
    # §3.1: edit ONE field (region); the emitted diff touches ONLY region + version + the appended
    # release_notes entry. The comment lines and the unknown custom key are byte-identical.
    # proven-failing 2026-07-06 (design phase): with ruamel defaults the no-op diff already showed
    # spurious null->empty and re-wrap changes — the tuned _yaml() config is what makes this hold.
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path))
    assert result["ok"] is True
    assert result["changed"] == ["region"]
    assert "-region: South Australia" in result["diff"]
    assert "+region: Northern Territory" in result["diff"]
    assert result["new_version"] == "1.0.1"
    new = result["new_yaml"]
    assert "release_notes:" in new
    assert "Corrected region." in new
    assert "# an unknown custom key the editor form does not model — must survive verbatim" in new
    assert 'custom_local_note: "keep me byte-for-byte"' in new
    assert "# human-readable name" in new
    assert "must stay exactly as written, word for word, across the round trip." in new
    # Nothing else changed: every original line EXCEPT the edited field (region) and the managed
    # version line is still present byte-for-byte.
    for line in EXEMPLAR.splitlines():
        if line.startswith(("region:", "version:")) or not line.strip():
            continue
        assert line in new, f"edit disturbed an untouched line: {line!r}"


def test_unknown_key_and_comments_survive_a_map_edit(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = _merge(
        _cfg(tmp_path),
        patch={"organisation": {"name": "University of Example",
                                "ror": "https://ror.org/00892tw58"}},
        bump="minor", note="Added ROR.")
    assert result["ok"] is True
    assert result["new_version"] == "1.1.0"
    assert "https://ror.org/00892tw58" in result["new_yaml"]
    assert 'custom_local_note: "keep me byte-for-byte"' in result["new_yaml"]


# --------------------------------------------------------------------------------------------------
# [FC-4] C43 Stage-1 diff-minimality pins (record D13). The editor submits WHOLE sections as plain
# JSON dicts; the pre-C43 apply_patch replaced the section's CommentedMap wholesale, so editing ONE
# sub-field re-emitted every sibling line and dropped intra-section comments. These pin the surgical
# in-place map merge (edit._merge_map_into). Proven RED against the pre-fix emitter 2026-07-10 (a
# single organisation.ror edit rewrote organisation.name and lost its trailing comment); see the C43
# report's red-then-green evidence.
# --------------------------------------------------------------------------------------------------

# A survey whose sections carry INTRA-section comments — the exact fidelity the wholesale replace
# destroyed. It deliberately carries every shape the FC-4 diff pins need to exercise:
#   * organisation — a map with a standalone leading comment (before `ror`), an inline trailing
#     comment (on `name`), and a DELETABLE sub-key (`legacy_code`, removed via the advanced-JSON path);
#   * processing — a map that carries BOTH a nested map-in-map (`software.name`/`software.version`,
#     each with its own comment) AND a list-valued member (`steps`), so a scalar/nested edit can be
#     proven not to disturb the untouched nested leaf's comment or the list block's bytes;
#   * lead_investigator (section B) — present purely to prove editing another section never rewrites
#     its bytes (the per-section patch pin).
_COMMENTED_SECTIONS_YAML = """\
schema_version: "0.2"
slug: demo-survey-2026
version: 1.0.0
region: South Australia

organisation:
  name: University of Example        # the lead org
  # a standalone comment before ror
  ror: null                          # ROR URL when known
  legacy_code: OLD-123               # removed via the advanced-JSON path

processing:
  software:
    name: Aurora                     # the processing software
    version: "1.2"                   # untouched nested leaf
  steps:
    - despike                        # first-pass despiking
    - rotate
    - decimate

lead_investigator:
  name: Ada Lovelace                 # PI of record
  orcid: "0000-0002-1825-0097"

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def test_single_field_edit_diff_touches_only_that_field(tmp_path):
    """[FC-4] DIFF-MINIMALITY PIN (record D13). Change ONE sub-field of a map section
    (organisation.ror null -> a URL) and the emitted survey.yaml diff must touch ONLY that field's
    line(s) plus the managed version/release_notes — never the untouched sibling (organisation.name)
    and never its comment. FAILS IF editing one sub-field re-emits a sibling line or strips an
    intra-section comment (the pre-C43 wholesale-replace behaviour, proven RED 2026-07-10)."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    # A pure single-field edit: submit the WHOLE organisation section back with only `ror` changed
    # (name + legacy_code carried through unchanged, so nothing is deleted — the add/delete case is
    # test_editing_section_a_never_rewrites_section_b_bytes / the F3 pins below).
    result = _merge(_cfg(tmp_path),
                    patch={"organisation": {"name": "University of Example",
                                            "ror": "https://ror.org/03yghzc09",
                                            "legacy_code": "OLD-123"}},
                    note="add ROR")
    assert result["ok"] is True
    assert result["changed"] == ["organisation"]
    diff = result["diff"]
    # The ONLY changed body lines (excluding managed version/release_notes) are the ror line pair.
    added = [ln for ln in diff.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in diff.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    # organisation.name (unchanged) must NOT appear as a +/- line — it kept its bytes AND comment.
    assert not any("name: University of Example" in ln for ln in added + removed), \
        f"an untouched sibling field moved in the diff:\n{diff}"
    # The ror line changed; its neighbours (name + the section comment) are byte-stable.
    assert any("ror: null" in ln for ln in removed)
    assert any("ror: https://ror.org/03yghzc09" in ln for ln in added)
    new = result["new_yaml"]
    assert "name: University of Example        # the lead org" in new, \
        "the untouched sibling lost its trailing comment"
    assert "# ROR URL when known" in new, "the edited field's own comment was dropped"


def test_editing_section_a_never_rewrites_section_b_bytes(tmp_path):
    """[FC-4] PER-SECTION PATCH PIN (record D13). Submitting a change to section A (organisation)
    that BOTH adds a sub-key AND deletes a sub-key (via the advanced-JSON path — the section is
    submitted without `legacy_code`, so _merge_map_into's deletion loop drops it) must leave section
    B (lead_investigator) byte-for-byte identical — every one of its lines, comment included, survives
    with no +/- diff line.

    Review F2: the PREVIOUS form of this test submitted only a scalar change and asserted section B
    was untouched — but the pre-C43 wholesale emitter ALSO never touched a sibling SECTION (it
    rebuilt only the edited section's node), so that assertion passed against every implementation
    that ever existed and could not fail (Invariant 10). The add+delete here goes through the exact
    deletion loop whose failability was PROVEN by mutation (evidence in the C43 fix-round report):
    pointing that loop at the ROOT document instead of the section node makes it delete top-level
    keys, which rewrites section B and reds this test. That mutation is evidence only, reverted, never
    committed. FAILS IF an add+delete in one section disturbs a sibling section's bytes."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    result = _merge(_cfg(tmp_path),
                    # ADD `contact` (new sub-key) + DELETE `legacy_code` (omitted from the submitted
                    # section) while keeping name/ror. This is the advanced-JSON override shape.
                    patch={"organisation": {"name": "University of Example",
                                            "ror": "https://ror.org/03yghzc09",
                                            "contact": "ops@example.edu"}},
                    note="add ROR + contact, drop legacy_code")
    assert result["ok"] is True
    assert result["changed"] == ["organisation"]
    diff = result["diff"]
    body = [ln for ln in diff.splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    # The add and the delete both landed in the diff (this is a REAL add+delete, not a no-op).
    assert any("contact: ops@example.edu" in ln and ln.startswith("+") for ln in body), \
        f"the added sub-key did not appear in the diff:\n{diff}"
    assert any("legacy_code: OLD-123" in ln and ln.startswith("-") for ln in body), \
        f"the deleted sub-key did not appear in the diff:\n{diff}"
    # No lead_investigator line (name, orcid, or its comment) appears among the changed lines.
    for needle in ("Ada Lovelace", "# PI of record", "0000-0002-1825-0097", "lead_investigator:"):
        assert not any(needle in ln for ln in body), \
            f"editing organisation disturbed section B ({needle!r}):\n{diff}"
    # And section B survives verbatim in the emitted bytes.
    new = result["new_yaml"]
    assert "name: Ada Lovelace                 # PI of record" in new
    assert 'orcid: "0000-0002-1825-0097"' in new


def _body_diff_lines(diff: str) -> list[str]:
    """The +/- body lines of a unified diff (the file-header ---/+++ lines excluded)."""
    return [ln for ln in diff.splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


# --------------------------------------------------------------------------------------------------
# [FC-4] F3 diff pins on the REAL emitted diff. Each pins one guarantee of the surgical map merge AND
# is failable by a NAMED mutation (temporary, evidence captured in the C43 fix-round report, reverted
# — never committed): a pin nothing can fail is not a pin (Invariant 10). The mutation for each is
# stated in its docstring so a future reader can reproduce the red.
# --------------------------------------------------------------------------------------------------
def test_added_subkey_with_ambiguous_value_is_quoted_no_sibling_moves(tmp_path):
    """F3(a). Adding a sub-key whose value is FIX-3-ambiguous ('NO', a YAML-1.1 bool) must emit it
    DOUBLE-QUOTED (so the PyYAML readers downstream read the string 'NO', not False) AND move no
    sibling line. Failable by bypassing quote_ambiguous on the added-key branch of _merge_map_into
    (`node[subkey] = new_val` instead of `= quote_ambiguous(new_val)`): the added value then emits
    bare `contact: NO` and PyYAML retypes it to False — proven RED in the fix-round report."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    result = _merge(_cfg(tmp_path),
                    patch={"organisation": {"name": "University of Example", "ror": None,
                                            "legacy_code": "OLD-123", "contact": "NO"}},
                    note="add ambiguous contact")
    assert result["ok"] is True
    body = _body_diff_lines(result["diff"])
    added = [ln for ln in body if ln.startswith("+")]
    # The added key is emitted double-quoted.
    assert any('contact: "NO"' in ln for ln in added), \
        f"the added ambiguous value was not double-quoted:\n{result['diff']}"
    assert not any("contact: NO" in ln and '"NO"' not in ln for ln in added), \
        f"the added ambiguous value emitted BARE (PyYAML would read False):\n{result['diff']}"
    # No sibling line moved: name/ror/legacy_code never appear as +/- lines.
    for sib in ("name: University of Example", "ror: null", "legacy_code: OLD-123"):
        assert not any(sib in ln for ln in body), \
            f"adding a sub-key moved an untouched sibling {sib!r}:\n{result['diff']}"
    # And PyYAML really reads the added value back as the string 'NO'.
    import base64

    import yaml as pyyaml
    reread = pyyaml.safe_load(base64.b64decode(result["new_yaml_b64"]))
    assert reread["organisation"]["contact"] == "NO"
    assert isinstance(reread["organisation"]["contact"], str)


def test_deleting_subkey_removes_only_that_line_neighbours_byte_stable(tmp_path):
    """F3(b). Deleting a sub-key (advanced-JSON: the section is submitted without `legacy_code`)
    removes ONLY that key's line; its neighbours' comments stay byte-stable. Failable via the F2
    mutation (deletion loop iterating the root document rather than the section node) — which deletes
    the wrong nodes and rewrites neighbouring lines; proven RED in the fix-round report."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    result = _merge(_cfg(tmp_path),
                    # legacy_code omitted => deleted; name/ror carried unchanged.
                    patch={"organisation": {"name": "University of Example", "ror": None}},
                    note="remove the retired identifier")  # note text avoids the key name substring
    assert result["ok"] is True
    assert result["changed"] == ["organisation"]
    body = _body_diff_lines(result["diff"])
    removed = [ln for ln in body if ln.startswith("-")]
    added = [ln for ln in body if ln.startswith("+")]
    # The deleted key's line is removed...
    assert any("legacy_code: OLD-123" in ln for ln in removed), \
        f"the deleted key's line was not removed:\n{result['diff']}"
    # ...and it is a pure DELETION: the key is never re-emitted as a `+` line (a wholesale rewrite
    # would delete-then-re-add it).
    assert not any("legacy_code" in ln for ln in added), \
        f"the deleted key was re-emitted as an added line (wholesale rewrite):\n{result['diff']}"
    # name + ror (the neighbours) are untouched — not in the diff body at all.
    for sib in ("name: University of Example", "ror: null"):
        assert not any(sib in ln for ln in body), \
            f"a neighbour of the deleted key moved:\n{result['diff']}"
    # The neighbours' comments survive byte-for-byte in the emitted bytes.
    new = result["new_yaml"]
    assert "name: University of Example        # the lead org" in new
    assert "# ROR URL when known" in new


def test_editing_nested_map_leaf_leaves_untouched_nested_leaf_comment(tmp_path):
    """F3(c). Editing ONE leaf of a nested map-in-map (processing.software.name) must leave the
    UNTOUCHED nested leaf (processing.software.version) and its comment byte-stable. Failable by
    making the recursion replace the nested map wholesale (e.g. `node[subkey] = quote_ambiguous(
    new_val)` for a dict new_val instead of recursing) — which re-emits the whole software block and
    drops the version comment; proven RED in the fix-round report."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    result = _merge(_cfg(tmp_path),
                    patch={"processing": {"software": {"name": "Aurora 2", "version": "1.2"},
                                          "steps": ["despike", "rotate", "decimate"]}},
                    note="bump software name")
    assert result["ok"] is True
    assert result["changed"] == ["processing"]
    body = _body_diff_lines(result["diff"])
    # Only the software.name leaf moved.
    assert any("name: Aurora" in ln and ln.startswith("-") for ln in body)
    assert any("name: Aurora 2" in ln and ln.startswith("+") for ln in body)
    # The untouched nested leaf (software.version) never appears as a +/- line. (Scope the needle to
    # the leaf's exact value so it does not collide with the managed top-level `version:` line or the
    # release-notes `version:` entries, which legitimately change.)
    assert not any('version: "1.2"' in ln for ln in body), \
        f"the untouched nested leaf moved:\n{result['diff']}"
    # And its comment survives byte-for-byte.
    assert 'version: "1.2"                   # untouched nested leaf' in result["new_yaml"], \
        "the untouched nested leaf's comment was dropped"


def test_scalar_edit_in_section_with_list_member_leaves_list_block_stable(tmp_path):
    """F3(d). A scalar edit in a map section that ALSO carries a list-valued member (processing.steps)
    must leave the list block byte-stable — the list is not reassigned just because a sibling scalar
    changed. Failable by forcing list reassignment on an unchanged list (e.g. dropping the
    `_plain(old_val) == new_val` short-circuit so an equal list is reassigned via quote_ambiguous and
    re-emits its own block); proven RED in the fix-round report."""
    _write_package(tmp_path / "surveys-live", yaml_text=_COMMENTED_SECTIONS_YAML)
    result = _merge(_cfg(tmp_path),
                    # Change software.name (a scalar leaf) but carry `steps` back UNCHANGED.
                    patch={"processing": {"software": {"name": "Aurora 2", "version": "1.2"},
                                          "steps": ["despike", "rotate", "decimate"]}},
                    note="scalar edit, list unchanged")
    assert result["ok"] is True
    body = _body_diff_lines(result["diff"])
    # No element of the unchanged list block appears as a +/- line.
    for elem in ("- despike", "- rotate", "- decimate", "steps:"):
        assert not any(elem in ln for ln in body), \
            f"an unchanged list block line moved on a sibling scalar edit ({elem!r}):\n{result['diff']}"
    # The list block survives verbatim in the emitted bytes — including the inline comment on its
    # first element, which a reassignment of the (comment-free-data) list would silently drop even
    # though the element data round-trips byte-identically. This comment is the observable that makes
    # the pin FAILABLE: the mutation "force list reassignment on unchanged lists" strips it.
    new = result["new_yaml"]
    assert ("  steps:\n    - despike                        # first-pass despiking\n"
            "    - rotate\n    - decimate\n") in new, \
        "the unchanged list block (or its element comment) was re-emitted / disturbed"


# --------------------------------------------------------------------------------------------------
# review FIX 3: the parser differential (ruamel emits, PyYAML reads)
# --------------------------------------------------------------------------------------------------
def test_patched_ambiguous_strings_reread_as_strings_under_pyyaml(tmp_path):
    # proven failing 2026-07-06 (pre-fix HEAD 4f4e999..a31fc8e): patched region "on" emitted as bare
    # `region: on` -> PyYAML safe_load read True (bool); name "no" -> False; abstract "12:34:56" ->
    # 45296 (YAML-1.1 sexagesimal int). ruamel's own re-read kept them strings, so the diff, the
    # §0.6 sha pin, and the confirm re-run all agreed and NO guard fired — the portal would have
    # served a bool/int the curator never wrote. FAILS IF quote_ambiguous stops quoting the
    # YAML-1.1-retypeable tokens.
    import base64

    import yaml as pyyaml

    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path),
                    patch={"region": "on", "name": "no", "abstract": "12:34:56"},
                    note="ambiguous scalars")
    assert result["ok"] is True
    emitted = base64.b64decode(result["new_yaml_b64"])
    reread = pyyaml.safe_load(emitted)
    assert reread["region"] == "on" and isinstance(reread["region"], str)
    assert reread["name"] == "no" and isinstance(reread["name"], str)
    assert reread["abstract"] == "12:34:56" and isinstance(reread["abstract"], str)
    # The release-note date is exactly the ISO shape PyYAML retypes to datetime.date — it must stay
    # a string too (the documented survey.yaml convention quotes it).
    entry = reread["release_notes"][-1]
    assert entry["date"] == "2026-07-06" and isinstance(entry["date"], str)
    assert isinstance(entry["version"], str)


def test_patched_ambiguous_map_keys_reread_as_strings_under_pyyaml(tmp_path):
    # Re-review finding (2026-07-06): quote_ambiguous recursed only over dict VALUES, so a curator-
    # supplied ambiguous KEY in a JSON-edited map ('on'/'no'/'12:34:56') emitted bare and PyYAML
    # retyped it (key True / False / 45296) while ruamel's re-read kept it a string — the same
    # differential as FIX 3, one axis over, with diff/sha-pin/confirm all self-consistently blind.
    # proven failing 2026-07-06 on pre-fix HEAD 0b7d386 (evidence in the fix commit).
    # FAILS IF the dict branch stops applying the quoting oracle to keys.
    import base64

    import yaml as pyyaml

    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path),
                    patch={"collection": {"on": "x", "no": "y", "12:34:56": "z",
                                          "id": "auslamp"}},
                    note="ambiguous keys")
    assert result["ok"] is True
    emitted = base64.b64decode(result["new_yaml_b64"])
    reread = pyyaml.safe_load(emitted)
    keys = set(reread["collection"].keys())
    assert keys == {"on", "no", "12:34:56", "id"}, keys
    for k in keys:
        assert isinstance(k, str)


def test_unambiguous_strings_stay_unquoted(tmp_path):
    # The quoting is surgical: a plain string that PyYAML reads back identically is NOT quoted, so
    # the diff stays minimal and matches the file's prevailing bare style.
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path))  # region -> Northern Territory
    assert "+region: Northern Territory" in result["diff"]  # bare, not "+region: \"Northern...\""


def test_needs_quoting_semantics():
    # Quote iff PyYAML would NOT read the bare token back as the identical string. The oracle is
    # PyYAML itself (the downstream reader), not the YAML-1.1 spec: PyYAML deliberately does NOT
    # implement the spec's single-letter y/n booleans, so "y"/"n" correctly stay unquoted.
    for ambiguous in ("on", "off", "yes", "no", "true", "False", "null", "~",
                      "12:34:56", "2026-07-06", "1.5", "007", "", " padded ", "a: b", "x #c",
                      "line1\nline2"):
        assert edit._needs_quoting(ambiguous), ambiguous
    for plain in ("Northern Territory", "CC-BY-4.0", "University of Example", "1.0.1",
                  "LEMI-423", "open", "y", "n"):
        assert not edit._needs_quoting(plain), plain


# --------------------------------------------------------------------------------------------------
# review FIX 2: scratch containment — nothing the merge does may touch the surveys tree
# --------------------------------------------------------------------------------------------------
def test_merge_scratch_never_touches_surveys_tree(tmp_path):
    # proven failing 2026-07-06 (pre-fix HEAD): during validation the scratch copy lived at
    # surveys-live/surveys/_edit_patched/** (6 paths created inside the live tree; a concurrent
    # publish's `git add surveys` would stage them, and a leaked scratch would dirty every later
    # publish preflight — and the gw-runner's /srv/surveys mount is READ-ONLY, so it would also have
    # crashed outright in production). FAILS IF any file/dir is created OR left under surveys-live
    # by a merge, at validation time or after.
    surveys_live = tmp_path / "surveys-live"
    _write_package(surveys_live)
    cfg = _cfg(tmp_path, validator_path=str(tmp_path / "validator"))  # non-empty -> scratch machinery runs

    before = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
    seen = {}
    orig = edit._run_validator

    def spy(validator_path, package_root):
        # Snapshot the surveys tree AT VALIDATION TIME (when the scratch copy exists) and record
        # where the copy actually lives.
        seen["during"] = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
        seen["scratch_package"] = Path(package_root)
        return {"items": []}

    edit._run_validator = spy
    try:
        result = _merge(cfg)
    finally:
        edit._run_validator = orig

    assert result["ok"] is True
    after = sorted(str(p.relative_to(surveys_live)) for p in surveys_live.rglob("*"))
    assert seen["during"] == before, "scratch files appeared INSIDE surveys-live during validation"
    assert after == before, "the merge left files behind under surveys-live"
    # And the scratch copy lived where it belongs: under the runner's jobs/edit/scratch tree.
    scratch = seen["scratch_package"].resolve()
    assert (cfg.jobs_dir / "edit" / "scratch").resolve() in scratch.parents
    assert surveys_live.resolve() not in scratch.parents


def test_scratch_under_surveys_tree_is_refused(tmp_path):
    # Belt-and-braces: even if a caller wired a scratch dir under the surveys tree, the dispatch
    # refuses before any copy happens.
    surveys_live = tmp_path / "surveys-live"
    _write_package(surveys_live)
    cfg = _cfg(tmp_path, validator_path="x")
    with pytest.raises(edit.EditError) as exc:
        edit._dispatch_edit(cfg, {"kind": "merge", "slug": "demo-survey-2026",
                                  "patch": {"region": "X"}, "bump": "patch", "note": "n",
                                  "today": "2026-07-06"},
                            surveys_live / "surveys" / "scratch-here")
    assert "scratch" in str(exc.value)


def test_trailing_newline_slug_refused_at_edit_gate(tmp_path):
    # Task #18: the single-slug edit gate uses FULLMATCH, not match — an anchored `$` matches before
    # a trailing newline, so `.match` let "slug\n" through and it became a path component. Proven
    # failing first against .match, where it reached "survey.yaml not found under demo-survey-2026\n".
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    with pytest.raises(edit.EditError, match="invalid slug"):
        _merge(cfg, slug="demo-survey-2026\n")


# --------------------------------------------------------------------------------------------------
# §3.2 semver + no-op gates
# --------------------------------------------------------------------------------------------------
def test_non_semver_current_version_refused(tmp_path):
    # The semver-greater gate (C31 §0.3) fires when the CURRENT version is not strict semver: the
    # bump cannot be proven greater, so the merge refuses (fail closed) with a fix-it-via-PR hint.
    # (The explicit version override was removed per review FIX 6, so lower/equal targets are no
    # longer constructible through the interface; the comparator itself is pinned below.)
    _write_package(tmp_path / "surveys-live",
                   yaml_text=EXEMPLAR.replace("version: 1.0.0", "version: v2022-final"))
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path))
    assert "semver" in str(exc.value).lower() or "MAJOR.MINOR.PATCH" in str(exc.value)


def test_missing_bump_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), bump="")
    assert "bump" in str(exc.value)


def test_noop_edit_refused(tmp_path):
    # §3.2: submitting the SAME values (no content change) is refused outright.
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), patch={"region": "South Australia"})
    assert "no changes" in str(exc.value)


def test_valid_patch_bump_appends_release_note(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = _merge(_cfg(tmp_path), patch={"abstract": "A revised abstract paragraph."},
                    note="Clarified the abstract.")
    assert result["ok"] is True
    new = result["new_yaml"]
    assert "1.0.1" in new
    assert "Clarified the abstract." in new


def test_semver_helpers():
    # §3.2 comparator semantics: lower/equal/non-semver are all NOT greater (the merge-side gate).
    assert edit.parse_semver("1.2.3") == (1, 2, 3)
    assert edit.parse_semver("1.2") is None
    assert edit.parse_semver("1.2.x") is None
    assert edit.parse_semver("v1.2.3") is None
    assert edit.semver_greater("1.0.1", "1.0.0") is True
    assert edit.semver_greater("1.0.0", "1.0.0") is False   # equal => refused
    assert edit.semver_greater("0.9.9", "1.0.0") is False   # lower => refused
    assert edit.semver_greater("2.0.0", "1.9.9") is True
    assert edit.suggest_bump("1.2.3", "patch") == "1.2.4"
    assert edit.suggest_bump("1.2.3", "minor") == "1.3.0"
    assert edit.suggest_bump("1.2.3", "major") == "2.0.0"
    assert edit.suggest_bump("garbage", "patch") == "1.0.1"


# --------------------------------------------------------------------------------------------------
# read job + patch guards
# --------------------------------------------------------------------------------------------------
def test_read_job_returns_editable_subset(tmp_path):
    _write_package(tmp_path / "surveys-live")
    result = edit._dispatch_edit(_cfg(tmp_path), {"kind": "read", "slug": "demo-survey-2026"},
                                 tmp_path / "gw" / "jobs" / "edit" / "scratch" / "t")
    assert result["ok"] is True
    assert result["version"] == "1.0.0"
    assert result["fields"]["region"] == "South Australia"
    assert result["fields"]["organisation"]["name"] == "University of Example"
    # The unknown key is NOT in the editable subset (the form never models it) but survives on disk.
    assert "custom_local_note" not in result["fields"]


def test_unknown_slug_and_bad_slug_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    scratch = cfg.jobs_dir / "edit" / "scratch" / "t"
    with pytest.raises(edit.EditError):
        edit._dispatch_edit(cfg, {"kind": "read", "slug": "no-such-survey"}, scratch)
    with pytest.raises(edit.EditError) as exc:
        edit._dispatch_edit(cfg, {"kind": "read", "slug": "../escape"}, scratch)
    assert "slug" in str(exc.value)


def test_non_editable_field_in_patch_refused(tmp_path):
    _write_package(tmp_path / "surveys-live")
    with pytest.raises(edit.EditError) as exc:
        _merge(_cfg(tmp_path), patch={"slug": "hijacked"})
    assert "non-editable" in str(exc.value)


# --------------------------------------------------------------------------------------------------
# the jobs/edit/ file queue (review FIX 1's transport)
# --------------------------------------------------------------------------------------------------
def test_claim_edit_job_atomic_lock(tmp_path):
    # Mirror of runner.claim_one: exactly one claim succeeds; the file moves pending -> running.
    dirs = edit.edit_dirs(tmp_path / "jobs")
    (dirs["pending"] / "j1.json").write_text(json.dumps({"kind": "read", "slug": "s"}),
                                             encoding="utf-8")
    first = edit.claim_edit_job(tmp_path / "jobs")
    second = edit.claim_edit_job(tmp_path / "jobs")
    assert first is not None and first.parent.name == "running"
    assert second is None


def test_process_edit_job_writes_done_result(tmp_path):
    # A claimed read job produces a done/<id>.json result and removes the running file — the file
    # protocol the gateway's default seam polls (FIX 1).
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    dirs = edit.edit_dirs(cfg.jobs_dir)
    (dirs["pending"] / "abc123.json").write_text(
        json.dumps({"kind": "read", "slug": "demo-survey-2026"}), encoding="utf-8")
    claimed = edit.claim_edit_job(cfg.jobs_dir)
    edit.process_edit_job(cfg, claimed)
    assert not claimed.exists()
    result = json.loads((dirs["done"] / "abc123.json").read_text(encoding="utf-8"))
    assert result["ok"] is True and result["version"] == "1.0.0"


def test_process_edit_job_never_raises(tmp_path):
    # Refusals AND unexpected garbage both land as {ok:False} result files — an edit job is
    # request/response, so a missing result would strand the polling gateway until timeout.
    _write_package(tmp_path / "surveys-live")
    cfg = _cfg(tmp_path)
    dirs = edit.edit_dirs(cfg.jobs_dir)
    # (a) a curator-facing refusal (no-op edit)
    (dirs["pending"] / "r1.json").write_text(json.dumps({
        "kind": "merge", "slug": "demo-survey-2026",
        "patch": {"region": "South Australia"}, "bump": "patch", "note": "n",
        "today": "2026-07-06"}), encoding="utf-8")
    edit.process_edit_job(cfg, edit.claim_edit_job(cfg.jobs_dir))
    r1 = json.loads((dirs["done"] / "r1.json").read_text(encoding="utf-8"))
    assert r1["ok"] is False and "no changes" in r1["error"]
    # (b) a malformed job file (not JSON) -> generic internal error, no exception
    (dirs["pending"] / "r2.json").write_text("not json", encoding="utf-8")
    edit.process_edit_job(cfg, edit.claim_edit_job(cfg.jobs_dir))
    r2 = json.loads((dirs["done"] / "r2.json").read_text(encoding="utf-8"))
    assert r2["ok"] is False and "internal error" in r2["error"]


# --------------------------------------------------------------------------------------------------
# real-validator integration (the shipped validate_survey.py, run over the scratch copy)
# --------------------------------------------------------------------------------------------------
_VALID_PACKAGE_YAML = """\
schema_version: "0.2"
slug: intg-survey-2026
project_name: Integration Survey      # keep this comment
version: 1.0.0
country: Australia
region: South Australia
organisation:
  name: University of Example
license: CC-BY-4.0
access:
  level: open
  embargo_until: null
custom_note: "unknown key survives"
"""

# C35b/D3 (review F7): resolve the validator UNCONDITIONALLY — sibling if present, else the committed
# vendored pinned copy; require_validator_dir() FAILS (never skips) if neither is present.
from gateway.tests.conftest import require_validator_dir  # noqa: E402


def test_merge_runs_the_real_validator(tmp_path):
    # Integration: run the merge with the REAL validate_survey.py (no override). Proves the actual
    # `validate_survey.py --json <file>` invocation + report interpretation work end-to-end over the
    # scratch copy. FAILS IF the invocation shape regresses (e.g. reading stdout instead of the
    # --json file) or the scratch plumbing breaks.
    surveys_live = tmp_path / "surveys-live"
    pkg = _write_package(surveys_live, slug="intg-survey-2026", yaml_text=_VALID_PACKAGE_YAML)
    (pkg / "README.md").write_text("# Integration Survey\n", encoding="utf-8")
    (pkg / "LICENSE.md").write_text("CC-BY-4.0\n", encoding="utf-8")
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45.2\n  LONG=136:58:12.0\n>END\n>FREQ ORDER=INC //1\n  1.0\n",
        encoding="utf-8")
    cfg = _cfg(tmp_path, validator_path=str(require_validator_dir()))
    result = _merge(cfg, slug="intg-survey-2026")
    assert result["ok"] is True
    assert isinstance(result["validator"].get("items"), list)
    assert len(result["validator"]["items"]) > 0
    assert result["has_fail"] is False, result["validator"]
    assert "# keep this comment" in result["new_yaml"]
    assert 'custom_note: "unknown key survives"' in result["new_yaml"]
    # And the surveys tree is untouched (FIX 2, against the real validator this time).
    assert not list(surveys_live.rglob("_edit_*"))


def test_merge_real_validator_flags_fail(tmp_path):
    # The real validator FAILs an out-of-enum access.level (a required, enumerated field), and the
    # merge reports has_fail=True — the signal the gateway turns into a confirm 409 (§0.4).
    # C35b/D3 (review F7): UNCONDITIONAL — sibling-or-vendored, FAILS if neither present.
    pkg = _write_package(tmp_path / "surveys-live", slug="intg-survey-2026",
                         yaml_text=_VALID_PACKAGE_YAML)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45.2\n  LONG=136:58:12.0\n>END\n>FREQ ORDER=INC //1\n  1.0\n",
        encoding="utf-8")
    cfg = _cfg(tmp_path, validator_path=str(require_validator_dir()))
    result = _merge(cfg, slug="intg-survey-2026",
                    patch={"access": {"level": "nonsense", "embargo_until": None}},
                    note="bad level")
    assert result["ok"] is True
    assert result["has_fail"] is True
