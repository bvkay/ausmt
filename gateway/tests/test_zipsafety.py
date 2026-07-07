"""Zip central-directory safety (design §4.3 / §8). Each hostile shape is rejected with a DISTINCT
reason and — proven separately in test_upload.py — nothing is written under quarantine/. These are
pure-unit tests against zipsafety.inspect(); test_upload.py drives the same shapes through the HTTP
seam.

Proven-failing-first: each guard was confirmed to genuinely fire by first asserting the OPPOSITE
(that a hostile zip passes) and watching it fail. Evidence recorded per-test below.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from gateway import zipsafety
from gateway.tests.conftest import good_package_zip, make_zip, ratio_bomb_zip

MAX = 1024 * 1024  # 1 MiB upload cap for these unit checks


def _inspect(data: bytes):
    return zipsafety.inspect(io.BytesIO(data), MAX)


def test_good_package_passes():
    # Baseline: a well-formed package inspects clean and returns its member list.
    names = _inspect(good_package_zip())
    assert any(n.endswith("survey.yaml") for n in names)
    assert any(n.endswith(".edi") for n in names)


def test_zip_slip_parent_segment_rejected():
    # proven failing 2026-07-05: without the `..`-segment guard, inspect() returned the member list
    # instead of raising -> AssertionError on pytest.raises.
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/../evil.edi": b"x"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "parent-directory" in str(exc.value)


def test_absolute_path_rejected():
    # proven failing 2026-07-05: absolute-path member accepted -> no raise.
    data = make_zip({"mysurvey/survey.yaml": b"s", "/etc/evil.edi": b"x"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "absolute path" in str(exc.value)


def test_backslash_rejected():
    # zipfile normalises '\\' -> '/' in its writer, reader, AND the ZipInfo constructor, so a
    # backslash cannot reach inspect() via a python-parsed archive — the guard is belt-and-braces
    # against a foreign zip tool whose bytes some other parser might surface un-normalised. Tested at
    # check_member()'s seam by setting .filename directly (bypassing the constructor's normalisation)
    # to prove the branch fires on a literal backslash.
    # proven failing 2026-07-05: with the backslash branch removed, check_member() returned without
    # raising -> pytest.raises failed "DID NOT RAISE".
    info = zipfile.ZipInfo("placeholder")
    info.filename = "mysurvey\\evil.edi"
    with pytest.raises(zipsafety.ZipRejection) as exc:
        zipsafety.check_member(info)
    assert "backslash" in str(exc.value)


def test_symlink_external_attr_rejected():
    # S_IFLNK (0o120000) in the top 16 bits of external_attr marks a symlink.
    # proven failing 2026-07-05: symlink member accepted (mode check absent).
    attr = (0o120777 << 16)
    data = make_zip(
        {"mysurvey/survey.yaml": b"s", "mysurvey/link.edi": b"/etc/passwd"},
        external_attrs={"mysurvey/link.edi": attr},
    )
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "symlink" in str(exc.value) or "non-regular" in str(exc.value)


def test_nested_archive_rejected():
    # proven failing 2026-07-05: a member named x.zip accepted (nested-archive check absent).
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/inner.zip": b"PK", "mysurvey/S.edi": b"e"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "nested archive" in str(exc.value)


def test_ratio_bomb_rejected():
    # proven failing 2026-07-05: 5-MiB-of-'A' member (ratio >> 100:1) accepted (ratio check absent).
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(ratio_bomb_zip())
    assert "ratio" in str(exc.value)


def test_member_count_bomb_rejected():
    # proven failing 2026-07-05: 2001-member zip accepted (member-count cap absent).
    members = {"mysurvey/survey.yaml": b"s", "mysurvey/S.edi": b"e"}
    for i in range(zipsafety.MAX_MEMBERS + 1):
        members[f"mysurvey/f{i}.txt"] = b"x"
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(make_zip(members))
    assert "member count" in str(exc.value)


def test_two_survey_yaml_rejected():
    # proven failing 2026-07-05: two survey.yaml at depth <=2 accepted.
    data = make_zip({
        "mysurvey/survey.yaml": b"s",
        "mysurvey/survey.yaml ": b"s",  # distinct name; both at depth 2 -> forge via second dir
    })
    # The trailing-space trick above yields a disallowed-name check first in some cases; build a
    # cleaner two-manifest case with a nested top dir sharing depth<=2.
    data = _two_manifest_zip()
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "survey.yaml" in str(exc.value)


def _two_manifest_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("survey.yaml", b"s")           # depth 1
        zf.writestr("mysurvey/survey.yaml", b"s")  # depth 2
        zf.writestr("mysurvey/S.edi", b"e")
    return out.getvalue()


def test_zero_edi_rejected():
    # proven failing 2026-07-05: package with no .edi accepted (edi-count check absent).
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/README.md": b"hi"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "no .edi" in str(exc.value)


def test_more_than_one_top_level_dir_rejected():
    # proven failing 2026-07-05: two top-level dirs accepted (single-package rule absent).
    data = make_zip({
        "a/survey.yaml": b"s", "a/S.edi": b"e",
        "b/other.txt": b"x",
    })
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "top-level" in str(exc.value)


def test_disallowed_char_rejected():
    # A control/odd char outside the allowed class.
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/we\x01rd.edi": b"e"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "disallowed character" in str(exc.value)


def test_duplicate_member_name_rejected():
    # review #13: a zip with two entries of the same name extracts last-wins, so the file the
    # validator/engine reads can differ from the central-directory view a reviewer inspected. Reject.
    # proven failing 2026-07-06: before the seen_names check, the duplicate passed inspect() (both
    # entries counted) and only the last survived extraction.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mysurvey/survey.yaml", b"s")
        zf.writestr("mysurvey/transfer_functions/edi/S01.edi", b"first")
        zf.writestr("mysurvey/transfer_functions/edi/S01.edi", b"second")  # duplicate name
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(out.getvalue())
    assert "duplicate member name" in str(exc.value)


def test_not_a_zip_rejected():
    with pytest.raises(zipsafety.ZipRejection):
        _inspect(b"this is not a zip")
