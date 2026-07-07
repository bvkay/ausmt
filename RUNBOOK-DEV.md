# AusMT developer runbook

Orientation for anyone working on this repository. Facts below were verified 2026-07-07.
If a count or command here disagrees with reality, fix this file in the same pull request.

## What this system is

Offline **engine** builds survey packages (EDI + `survey.yaml`, from the separate
`ausmt-surveys` repo) into static JSON/XML products; a static **portal** serves them; a
**gateway** takes community submissions through upload → ClamAV scan → validate → curator
review → publish (a git commit+push to `ausmt-surveys`); **deploy** runs the three as Docker
Compose services. Engine and portal share one **positional column contract**
(`contract/columns.json` → generated `_contract.py` / `contract.js`) — never reorder columns;
follow `docs/docs/developer/extending.md` recipes exactly.

## Running the test suites

Any Python 3.12 env with the pinned requirements works; the known-good dev env is the
`ausmt` conda env. Counts as of 2026-07-07: **444 total** (including the surveys repository gate).

| Suite | cwd | Command | Notes |
|-------|-----|---------|-------|
| engine (190) | `engine/` | `conda run -n ausmt python -m pytest -q tests` | ~3 min; needs mt_metadata/mth5 (pinned in `engine/environments/`) |
| gateway (194) | **repo root** | `conda run -n ausmt python -m pytest -q gateway/tests` | ~10 s; deps in `gateway/requirements-dev.txt`; cwd must be repo root so `gateway` imports |
| portal (22) | `portal/` | `conda run -n ausmt python -m pytest -q tests` | jsdom drivers need node + `npm install` in `portal/` (see `portal-ci.yml`) |
| surveys gate (38) | `../ausmt-surveys/` | `conda run -n ausmt python -m pytest -q tests` | validates the validator + contribute tooling |

Lint: `ruff check` runs per-package in CI; run it on whatever you touched.

Quick engine smoke without any data: `python -m extract.build_portal --surveys <empty-dir>
--allow-empty --no-validate --out /tmp/out` (from `engine/`). The docs site has no CI; run
`mkdocs build --strict` from `docs/` before changing it.

## Running the portal locally

```
cd portal && python -m http.server 8000     # then open http://localhost:8000/
```

Must be HTTP, not `file://`. The committed `portal/data/*.json` sample makes the map work
immediately; download tiles (EDI/XML/bundles) need one engine build first
(`python -m extract.build_portal --surveys ... --out portal/data` — see `engine/README.md`).

## Which doc owns which subsystem

| Topic | Authoritative doc |
|-------|-------------------|
| Deploying / operating (Docker, box runbook, incidents) | `deploy/README.md` |
| Positional data contract | `docs/docs/developer/data-files.md` |
| "How do I add/change X" recipes | `docs/docs/developer/extending.md` |
| System map | `docs/docs/developer/architecture.md` |
| Design records (ADRs + C-series) | `maintainer/README.md` |
| Frozen subsystem designs (**C-series**) | `maintainer/C<NN>-*.md` — numbered implementation contracts; each freezes the security/design decisions for one subsystem before it was built. Gateway=C10, curator=C11/C11b, upload button=C13, build cache=C18, metadata editor=C31, bundles=C32, operator docs=C33 |
## Pitfalls

1. **Positional contract**: adding a catalogue column touches engine emit + `contract/columns.json`
   + portal consumption *together*, or the UI silently corrupts (`extending.md` recipe 3).
2. **`python -m extract.build_portal` resolves via the installed package.** The editable and
   in-image installs expose both `ausmt_science` and `extract`, so the module runs from any
   working directory. If it raises `ModuleNotFoundError`, refresh the editable install:
   `pip install -e engine --no-deps`.
3. **Fail-closed behaviour is deliberate.** Gateway states, validator resolution, embargo
   gates and licence allow-lists refuse rather than guess. Before weakening a refusal, read
   the design record that froze it (a `maintainer/C*.md` file or `deploy/README.md`).
4. **Development on Windows, CI on Linux.** Sort any glob whose order you rely on, keep to
   the CI Python version's syntax, and pass `encoding="utf-8"` on file I/O.
5. **Automation never pushes.** Merges and releases are performed by the maintainer.
