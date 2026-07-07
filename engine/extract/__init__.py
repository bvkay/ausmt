"""AusMT extraction engine — the app-layer build package of the engine image.

`extract` is the offline pipeline that ingests EDI/MTH5 survey packages and emits the
portal/data JSON products (`python -m extract.build_portal`). It is a SIBLING of the
importable science library `ausmt_science` under `engine/`; both are installed by the
engine's editable/pip install so `extract` resolves by INSTALLED PACKAGE, not by cwd.

Naming note (design record C37): the top-level name `extract` is deliberately
generic and is ACCEPTED here because this package lives only inside a dedicated engine
image + env — it is never published to PyPI, so there is no external namespace to collide
with. Making it a real installed package (this `__init__.py` + `"extract*"` in
`[tool.setuptools.packages.find]`) is what makes the `python -m extract.build_portal`
claim TRUE independent of the working directory; the prior WORKDIR-on-sys.path contract is
retired (see docs/docs/developer/build-lifecycle.md and the engine.Dockerfile comment).
"""
