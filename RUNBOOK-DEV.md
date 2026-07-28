# AusMT developer runbook

Orientation for anyone working on this repository. Facts below were verified 2026-07-29.
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

Any Python 3.12 env with the pinned requirements works. The maintainer's known-good env is the
`ausmt` conda env, so the commands below are written for it; drop the `conda run -n ausmt`
prefix if your interpreter is already the right one.

Counts below are per-suite collection figures, plus **118** in the surveys repository gate. The
portal and deploy rows were re-measured on 2026-07-29 after `main` brought in the release machinery
and the C45 analytics work. The engine and gateway rows predate that merge and are known to be low;
both need a re-count in the `ausmt` env, so this file states no repository-wide total until they
have one.

| Suite | cwd | Command | Collected | Notes |
|-------|-----|---------|-----------|-------|
| engine | `engine/` | `conda run -n ausmt python -m pytest -q tests` | 438 | 433 pass, 5 skip. Several minutes; needs mt_metadata/mth5 (pinned in `engine/environments/`) |
| gateway | **repo root** | `conda run -n ausmt python -m pytest -q gateway/tests` | 678 | under a minute; deps in `gateway/requirements-dev.txt`; cwd must be repo root so `gateway` imports |
| deploy | **repo root** | `conda run -n ausmt python -m pytest -q deploy/tests` | 183 | shell, compose and Caddy config gates. Two tests shell out to host tools and skip when they are absent: `caddy validate` and `flock(1)`. The Caddy one needs to be able to create the log dir the Caddyfile names, so it can fail on a dev box where CI is green |
| portal | `portal/` | `conda run -n ausmt python -m pytest -q tests` | 135 | jsdom drivers need node + `npm ci` in `portal/` (see `portal-ci.yml`) |
| surveys gate | `../ausmt-surveys/` | `conda run -n ausmt python -m pytest -q tests` | 118 | validates the validator + contribute tooling |

CI runs gateway and deploy together from the repo root
(`python -m pytest -q -rs gateway/tests deploy/tests`, `gateway-ci.yml`), so run them that way
when you are reproducing a CI failure.

Lint, exactly as CI runs it:

```
cd engine && ruff check --config pyproject.toml . ../contract ../portal/tools
ruff check --config engine/pyproject.toml gateway/          # from the repo root
```

Generated-file drift guards: `python contract/generate.py --check` and
`python portal/tools/gen_config.py --check`.

Quick engine smoke without any data: `python -m extract.build_portal --surveys <empty-dir>
--allow-empty --no-validate --out /tmp/out` (from `engine/`). The docs site has no CI; run
`mkdocs build --strict` from `docs/` before changing it.

## CI repo variables (deploy-images.yml)

The `deploy-images` workflow's **curator-e2e** and **gateway-e2e** jobs need the separate
`ausmt-surveys` repo (for the validator) to reach the `VALIDATED` state and prove the publish flow.
Two GitHub repo settings supply it:

| Name | Kind | Purpose |
|------|------|---------|
| `AUSMT_SURVEYS_URL` | repo **variable** | clone URL of the `ausmt-surveys` repo (the validator source) |
| `AUSMT_SURVEYS_TOKEN` | repo **secret** | scoped token for cloning it when private (injected into the https URL; never logged) |

**On a push to main these are required.** curator-e2e is the ONLY end-to-end proof of
submission → curation → commit-to-surveys-live, and the build job publishes `:latest` before it runs;
if the variable is unset the job **fails** (guard step in `deploy-images.yml`) rather than skipping
silently and leaving a hollow green. On **pull-request** runs the jobs still skip cleanly when the
variable is unset (a fork PR has no access to the private surveys repo), recording on the job summary
exactly which acceptance halves were skipped. Set both under repo **Settings → Secrets and variables →
Actions** (variable on the *Variables* tab, token on the *Secrets* tab).

Separately, the **anon-pull-check** job (push-only) asserts the three published GHCR images are
anonymously pullable; it **fails until the owner flips each package to Public** (Package settings →
Change visibility → Public) — that failure is the intended regression guard against the private-package
403, not a misconfiguration to suppress.

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
| `survey.yaml` fields, credit model, identifiers, coordinate access | `docs/docs/reference/survey-yaml.md` |
| Why a model is shaped the way it is | `docs/docs/rationale/` |
| Design records (ADRs + C-series) | `maintainer/README.md` |

The **C-series** files (`maintainer/C<NN>-*.md`) are numbered implementation contracts. Each
freezes the security and design decisions for one subsystem before it was built, and the index in
`maintainer/README.md` says which record covers what. Read the relevant one before changing
behaviour it froze.

## Pitfalls

1. **Positional contract**: adding a catalogue column touches engine emit + `contract/columns.json`
   + portal consumption *together*, or the UI silently corrupts (`extending.md` recipe 3).
2. **`python -m extract.build_portal` resolves via the installed package.** The editable and
   in-image installs expose both `ausmt_science` and `extract`, so the module runs from any
   working directory. If it raises `ModuleNotFoundError`, refresh the editable install:
   `pip install -e engine --no-deps`.
3. **Fail-closed behaviour is deliberate.** Gateway states, validator resolution, embargo
   gates, coordinate-access policies and licence allow-lists refuse rather than guess. Before
   weakening a refusal, read the design record that froze it (a `maintainer/C*.md` file or
   `deploy/README.md`).
4. **Development on Windows, CI on Linux.** Sort any glob whose order you rely on, keep to
   the CI Python version's syntax, and pass `encoding="utf-8"` on file I/O.
5. **Automation never pushes.** Merges and releases are performed by the maintainer.
