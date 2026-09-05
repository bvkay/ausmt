"""Zip central-directory safety. Each hostile shape is rejected with a DISTINCT
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
    # Proven failing: without the `..`-segment guard, inspect() returned the member list
    # instead of raising -> AssertionError on pytest.raises.
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/../evil.edi": b"x"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "parent-directory" in str(exc.value)


def test_absolute_path_rejected():
    # Proven failing: absolute-path member accepted -> no raise.
    data = make_zip({"mysurvey/survey.yaml": b"s", "/etc/evil.edi": b"x"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "absolute path" in str(exc.value)


def test_backslash_rejected():
    # zipfile normalises '\\' -> '/' in its writer, reader, AND the ZipInfo constructor, so a
    # backslash cannot reach inspect() via a python-parsed archive - the guard is belt-and-braces
    # against a foreign zip tool whose bytes some other parser might surface un-normalised. Tested at
    # check_member()'s seam by setting .filename directly (bypassing the constructor's normalisation)
    # to prove the branch fires on a literal backslash.
    # Proven failing: with the backslash branch removed, check_member() returned without
    # raising -> pytest.raises failed "DID NOT RAISE".
    info = zipfile.ZipInfo("placeholder")
    info.filename = "mysurvey\\evil.edi"
    with pytest.raises(zipsafety.ZipRejection) as exc:
        zipsafety.check_member(info)
    assert "backslash" in str(exc.value)


def test_symlink_external_attr_rejected():
    # S_IFLNK (0o120000) in the top 16 bits of external_attr marks a symlink.
    # Proven failing: symlink member accepted (mode check absent).
    attr = (0o120777 << 16)
    data = make_zip(
        {"mysurvey/survey.yaml": b"s", "mysurvey/link.edi": b"/etc/passwd"},
        external_attrs={"mysurvey/link.edi": attr},
    )
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "symlink" in str(exc.value) or "non-regular" in str(exc.value)


def test_nested_archive_rejected():
    # Proven failing: a member named x.zip accepted (nested-archive check absent).
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/inner.zip": b"PK", "mysurvey/S.edi": b"e"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "nested archive" in str(exc.value)


def test_ratio_bomb_rejected():
    # Proven failing: 5-MiB-of-'A' member (ratio >> 100:1) accepted (ratio check absent).
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(ratio_bomb_zip())
    assert "ratio" in str(exc.value)


def test_member_count_bomb_rejected():
    # Proven failing: 2001-member zip accepted (member-count cap absent).
    members = {"mysurvey/survey.yaml": b"s", "mysurvey/S.edi": b"e"}
    for i in range(zipsafety.MAX_MEMBERS + 1):
        members[f"mysurvey/f{i}.txt"] = b"x"
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(make_zip(members))
    assert "member count" in str(exc.value)


def test_two_survey_yaml_rejected():
    # Proven failing: two survey.yaml at depth <=2 accepted.
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


def test_zero_transfer_functions_rejected():
    # Proven failing: package with no transfer function accepted (count check absent).
    data = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/README.md": b"hi"})
    with pytest.raises(zipsafety.ZipRejection) as exc:
        _inspect(data)
    assert "no transfer-function members" in str(exc.value)


def test_emtfxml_only_package_accepted():
    """EMTF XML is a first-class submission input, so a package whose only
    transfer functions are EMTF XML must pass the shape rule.

    FAILS IF the shape rule still demands a .edi: before this change an EMTF-XML-only submission was
    rejected at the door with "no .edi members in package" and never reached the validator, so the
    engine's XML ingest path could not be exercised by a real submission at all."""
    names = _inspect(make_zip({
        "mysurvey/survey.yaml": b"s",
        "mysurvey/transfer_functions/emtfxml/S01.xml": b"<EM_TF></EM_TF>",
    }))
    assert "mysurvey/transfer_functions/emtfxml/S01.xml" in names


def test_mixed_edi_and_emtfxml_package_accepted():
    # The precedence case (a station supplied in both formats) must get through the door too; which
    # rendition wins is the ENGINE's decision, made after parsing, not a shape rule this module knows.
    names = _inspect(make_zip({
        "mysurvey/survey.yaml": b"s",
        "mysurvey/transfer_functions/edi/S01.edi": b">HEAD\n",
        "mysurvey/transfer_functions/emtfxml/S01.xml": b"<EM_TF></EM_TF>",
    }))
    assert len(names) == 3


def test_more_than_one_top_level_dir_rejected():
    # Proven failing: two top-level dirs accepted (single-package rule absent).
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
    # a zip with two entries of the same name extracts last-wins, so the file the
    # validator/engine reads can differ from the central-directory view a reviewer inspected. Reject.
    # Proven failing: before the seen_names check, the duplicate passed inspect() (both
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
