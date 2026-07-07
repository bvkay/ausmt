# Contributing to AusMT

AusMT is early-stage infrastructure with a single maintainer, heading for AuScope stewardship.
Contributions are welcome. The aim of this file is that a newcomer can prepare a good pull
request without needing prior contact.

## Before you write code

1. Read [`RUNBOOK-DEV.md`](RUNBOOK-DEV.md) (one page): repo map, test suites, the traps.
2. Check whether the area you're touching has a **frozen design doc** (`maintainer/C<NN>-*.md`).
   Those documents fix security and architecture decisions deliberately — PRs that contradict a
   frozen decision without first proposing an amendment to the doc will be declined, however
   good the code.
3. For anything touching the **positional data contract** (`contract/columns.json`), follow
   `docs/docs/developer/extending.md` to the letter. Columns are append-only, forever.

## The PR bar

- **All four test suites green** (commands in `RUNBOOK-DEV.md`), plus `ruff check` on what you
  touched. If you add behaviour, add a test that **fails without your change** — tests that
  cannot fail are not tests, and reviews here check for that specifically.
- Follow the [code and data conventions](docs/docs/developer/conventions.md).
- Match the local style of the file you're editing (this repo intentionally has more than one
  style; consistency is judged per-file, not repo-wide).
- Comments explain *why* (constraints, invariants), not *what*.
- Docs are part of the change: if your PR makes a README/runbook/design-doc claim false, fix
  the claim in the same PR.
- Keep PRs reviewable without whole-system knowledge: one concern per PR, ~200 lines of diff
  is a happy size.

## Data contributions

Survey **data** does not go through this repo — see the portal's *Add survey* page, which
packages your EDIs + metadata and submits them through the gateway for curation
(`docs/docs/operations/submission.md`). Data licensing is per-survey (typically CC-BY-4.0) and
is declared in `survey.yaml`, not here.

## Security

Found something security-relevant (gateway, deployment, PII handling)? Please **do not** open
a public issue with the details — email the maintainer (see `NOTICE`) and reference the
affected file so it can be triaged privately first.

## Licence

Code contributions are accepted under the repository's Apache-2.0 licence. You retain
copyright; by contributing you agree your contribution is licensed under Apache-2.0 like the
rest of the framework.

## Provenance

Development of AusMT has been assisted by AI coding tools. All design decisions, review, and
responsibility rest with the maintainer.
