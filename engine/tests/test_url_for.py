"""url_for — the manifest storage-tier resolver (slice #4 distribution backbone). A pure, dependency-free
function, so this runs in the core suite. Locks the branches the build/integration tests could not reach
(they only ever emit tier=repo, relative urls — the `assert tier in (repo,nci)` there is tautological,
audit M6): absolute --base-url joining, the tier=nci null contract (url_for returns None for a bare
tier=nci because the absolute NCI url is built from a survey's nci_base by _resolve_artifact, not here —
see test_manifest.py::test_manifest_nci_base_flips_tier), and the Windows-backslash normalization that
makes a build on Windows still emit web urls.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import build_portal as bp  # noqa: E402


def test_url_for_relative_default():
    # tier=repo + base_url='' -> a portal-relative url the consumer joins onto data_base_url
    assert bp.url_for("edi/sample/A1.edi") == "edi/sample/A1.edi"
    assert bp.url_for("/xml/s/A.xml") == "xml/s/A.xml"          # any leading slash is stripped


def test_url_for_base_url_join():
    assert bp.url_for("edi/A1.edi", base_url="https://nci.example") == "https://nci.example/edi/A1.edi"
    # a trailing slash on the base must NOT produce a double slash
    assert bp.url_for("edi/A1.edi", base_url="https://nci.example/") == "https://nci.example/edi/A1.edi"


def test_url_for_nci_tier_is_null():
    # url_for is the repo/base_url resolver; it deliberately returns None for a bare tier=nci because the
    # absolute NCI url is built from a survey's nci_base by _resolve_artifact (proven end-to-end in
    # test_manifest.py::test_manifest_nci_base_flips_tier), NOT because the NCI tier is unimplemented.
    assert bp.url_for("edi/A1.edi", tier="nci") is None
    assert bp.url_for("edi/A1.edi", tier="nci", base_url="https://nci.example") is None


def test_url_for_normalizes_backslashes():
    # a Windows-built path component must still serialize as a web url
    assert bp.url_for("edi\\sample\\A1.edi") == "edi/sample/A1.edi"
