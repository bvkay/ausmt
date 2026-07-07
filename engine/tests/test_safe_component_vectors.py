"""C38 item 4 (code-health review §6 M2 family): pin build_portal.safe_component against shared vectors.

safe_component is the untrusted-DATAID/slug sanitiser guarding on-disk product paths, ausmt_ids and
portal markup against traversal / stored XSS. Its behaviour is pinned here by a COMMITTED vector file
(engine/tests/fixtures/safe_component_vectors.json) — the same file the jsdom mirror consumes
(portal/tests/add_survey_logic.test.js -> add-survey.html's safeEdiComponent, landed with the DATAID
packaging lane), so the two copies of the rule cannot drift. Sharing the vectors is the point — a
change to the sanitiser that this file does not also update reds here or on the JS side.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal as bp   # noqa: E402

_VECTORS = HERE / "fixtures" / "safe_component_vectors.json"


def _load():
    return json.loads(_VECTORS.read_text(encoding="utf-8"))


def test_safe_component_matches_shared_vectors():
    # FAILS IF safe_component's output diverges from any committed vector — the mutation target: change
    # the sanitiser (e.g. stop neutralising '..') or edit one expected value and exactly that vector
    # reds. Uses the file's own `fallback` so an empty-result vector is pinned to the real default.
    data = _load()
    fallback = data["fallback"]
    mismatches = []
    for v in data["vectors"]:
        got = bp.safe_component(v["input"], fallback)
        if got != v["expected"]:
            mismatches.append({"input": v["input"], "expected": v["expected"], "got": got,
                               "kind": v["kind"]})
    assert not mismatches, f"safe_component diverged from safe_component_vectors.json: {mismatches}"


def test_vectors_cover_the_security_relevant_kinds():
    # Non-vacuity guard: the file must actually exercise traversal, XSS, unicode and empty inputs (the
    # cases safe_component exists FOR). FAILS IF any class is missing — a vector file of only 'plain'
    # ids would be a hollow oracle.
    kinds = " ".join(v["kind"] for v in _load()["vectors"])
    for needed in ("traversal", "xss", "unicode", "empty"):
        assert needed in kinds, f"safe_component vectors miss the {needed!r} class"


def test_safe_component_never_returns_empty_or_unsafe():
    # Structural invariant across EVERY vector output: the result is non-empty and contains only the
    # safe charset [A-Za-z0-9._-], with no '..' — the property the sanitiser guarantees, checked
    # independently of the per-vector expected strings (so a wrong expected value can't hide a genuine
    # traversal/empty escape).
    import re
    safe_re = re.compile(r"^[A-Za-z0-9._-]+$")
    for v in _load()["vectors"]:
        out = bp.safe_component(v["input"])
        assert out, f"safe_component returned empty for {v['input']!r}"
        assert safe_re.match(out), f"safe_component left unsafe chars in {out!r} (from {v['input']!r})"
        assert ".." not in out, f"safe_component left a '..' in {out!r} (from {v['input']!r})"
