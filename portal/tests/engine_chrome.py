"""The engine's chrome emitters, executed from engine/extract/_pages.py's SOURCE text.

The portal suite holds the generated pages' header and footer against the static pages', and it reads
the emitter rather than a rendered page: portal-ci runs on portal/** and on _pages.py, where the engine
workflow cannot see an index.html edit. _pages.py cannot simply be imported (it sibling-imports
_au_outline and _stationcheck, which need the engine's own path set up), and re-typing its markup here
would only pin a third copy of it. So the module's literal constants and the named emitters are lifted
out with ast and run in a namespace of their own, the mechanism test_collection_colours.py uses for
_member_colours. An emitter that reaches for something this namespace does not carry fails loudly with
a NameError rather than rendering a region empty.
"""
import ast
import html
import inspect
from pathlib import Path

PAGES_PY = Path(__file__).resolve().parents[2] / "engine" / "extract" / "_pages.py"

# The helpers an emitter may call besides itself. Each is lifted only if _pages.py defines it.
_HELPERS = ("_e",)


def source():
    return PAGES_PY.read_text(encoding="utf-8")


def namespace(*funcs):
    """Every module-level literal constant, plus the named functions and the helpers they may call."""
    tree = ast.parse(source())
    ns = {"html": html}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                ns[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    wanted = set(funcs) | set(_HELPERS)
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(PAGES_PY), "exec"), ns)  # noqa: S102
            found.add(node.name)
    missing = set(funcs) - found
    assert not missing, f"engine/extract/_pages.py no longer defines {sorted(missing)}"
    return ns


def site_header(active=""):
    """The header _site_header() writes for a page whose current tab is `active`."""
    fn = namespace("_site_header")["_site_header"]
    return fn(active)


def site_footer(status=""):
    """The footer _site_footer() writes around a page's contextual `status` markup."""
    fn = namespace("_site_footer")["_site_footer"]
    params = inspect.signature(fn).parameters
    assert "status" in params, (
        "engine/extract/_pages.py: _site_footer must take the page's contextual status markup, which "
        "moved from the header's right zone to the footer's")
    return fn(status=status)


def function_source(name):
    """One top-level function's source text, for pins on what an emitter writes in order."""
    src = source()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(f"engine/extract/_pages.py no longer defines {name}")
