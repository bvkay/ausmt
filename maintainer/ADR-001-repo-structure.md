# ADR-001 — Repository structure: framework monorepo + separate data repo + contract-as-package

- **Status:** ACCEPTED 2026-06-16 · **EXECUTED 2026-06-17** (the framework merge is done — see *Status /
  next action* at the bottom). The `contract/` extraction + the GitHub push are the remaining parts.
- **Deciders:** the project maintainer (AuScope).
- **Supersedes:** the initial 5-separate-repos layout (`ausmt-science`, `ausmt-surveys`, `ausmt-portal`,
  `ausmt-docs`, `maintainer`).

## Context

AusMT today is **5 separate git repos**. An adversarial audit of the codebase (2026-06)
found that its single biggest *recurring* failure mode is **cross-repo contract drift**: the regex
retirement's sweep was incomplete because it spanned repos (the surveys `contribute.py` and several docs
still drove a deleted engine); the positional `*_COLUMNS` contract drifts because producer and consumers
live apart; the `manifest.json` contract spans engine → schema → portal. Every one of those is a
"the code is split but the contract isn't" defect.

The key realisation: **the 5 repos are not the same kind of thing.** Four are the *framework* (code +
docs, coupled by a shared contract, versioned together); one (`ausmt-surveys`) is *instance data* —
citable, governed, growing, and on a trajectory to NCI THREDDS + DataCite DOIs (see
the NCI storage-tier assessment, 2026-06). The current seams are half-right: the **data separation is
correct**; the **framework fragmentation is not**.

## Decision

1. **Merge the framework repos into ONE `ausmt` monorepo:** `ausmt-science` + `ausmt-portal` +
   `ausmt-docs` + `maintainer`.
2. **Keep `ausmt-surveys` (the data) a SEPARATE repo** — different lifecycle, scale (→ GB), governance
   (curated/embargoable/PR-submitted), and a path to NCI + DOIs that should not drag the framework.
3. **Extract the shared contract into a versioned `contract/` package** that is the single source of the
   positional column definitions (`CATALOGUE_COLUMNS`/`SCI_COLUMNS`/`TF_COLUMNS`) **and** the JSON schemas
   (`mtcat`, `manifest`), generating both the **Python** constants the engine uses and the **JS** constants
   the portal uses. A consumer then *cannot silently lag* the producer.

Net: **5 repos → 2** (`ausmt` framework + `ausmt-surveys` data).

### Proposed layout

```
ausmt/                         ← the framework monorepo
  contract/                    ← SINGLE SOURCE of *_COLUMNS + JSON schemas; generates py + js constants
  engine/                      ← was ausmt-science (extract/, ausmt_science/, scripts/, environments/, tests/)
  portal/                      ← was ausmt-portal (static site)
  docs/                        ← was ausmt-docs (ReadTheDocs builds fine from a subdir)
  maintainer/                  ← the KB (this file)
  .github/workflows/           ← PATH-SCOPED CI (see consequences)
ausmt-surveys/                 ← SEPARATE: data-as-code now → metadata+pointers (TF files on NCI) + DOIs later
```

## Why (condensed)

| Angle | Verdict |
|-------|---------|
| **Provenance / citability** | Data separate ⇒ its git history *is* its provenance, clean of code noise, decoupled from the volatile engine. The build already stamps the code commit + engine versions into `build_provenance`. |
| **Scale** | Strongest reason data stays out: ~4000 AusLAMP stations → GB; a monorepo would drag GB into every code clone. Separate, the data can move to LFS/NCI without touching code. |
| **Maintainability / DX** | Merge the code: one clone, one PR for a contract change, atomic refactors, "find all references" trivial — the exact fix for the audit's drift. The polyrepo coordination tax is what a small team can least afford. |
| **Trust / governance** | Separate repos let the **code be public (auditable) while data is governed/embargoable** — a monorepo forces one access policy on everything. Consolidating the framework also makes it auditable as one unit. |
| **Reuse (NZMT/CanadaMT)** | The framework *is* the reusable thing: "fork `ausmt`, swap `portal.config.yaml`, point at your own data repo." Forking 3 coupled code repos is the messy version. |
| **Future / evolution** | Split by churn rate: code changes occasionally; data churns constantly once slice-6 submissions flow. Don't put thousands of data PRs in the engine's history. |
| **Contract drift (the audit's #1 theme)** | `contract/` package makes drift *impossible*, not just easier to catch; the monorepo makes the generator + both consumers co-located. |

### Rejected alternatives

- **Status quo (5 repos):** keeps clean boundaries but pays the audit's drift tax forever; wrong trade for
  a system where the contract is the hard part.
- **Full monorepo (incl. data):** the GB-clone problem + coupling data governance to code openness + a
  messier fork-to-reuse story make it worse than splitting the data out.
- **Monorepo-for-dev / polyrepo-for-publish (git-subtree/Copybara mirrors):** real pattern, but maintaining
  a split pipeline is over-engineering at this team size. Consciously not doing it.

## Consequences

- **(+)** Atomic contract changes; one clean clone for any framework work; framework forks cleanly for reuse;
  easier holistic audit; data stays light, governed, separately-hostable (NCI).
- **(−)** CI must become **path-scoped** (pytest only when `engine/`|`contract/` changes; Pages deploy only
  when `portal/`|`contract/` changes; docs build only on `docs/` changes). Standard, low-cost.
- **(−)** A one-time **history-preserving merge** (see below).
- Polyglot repo (Python engine + JS portal) — fine; monorepos routinely hold both.

## Migration (history-preserving) — do before the AuScope push

1. Create the new `ausmt` repo. For each of the four framework repos, fold it into a subdirectory **keeping
   its commit history** using `git-filter-repo --to-subdirectory-filter <dir>` (or `git subtree add`/the
   `tomono` script), then merge into `ausmt`.
2. Introduce `contract/` and move `schema/*.json` + the `*_COLUMNS` definitions there; generate the Python
   and JS constants from it; repoint `engine/` and `portal/` at the generated artifacts.
3. Add path-scoped `.github/workflows/`.
4. Leave `ausmt-surveys` as-is.
5. THEN create the GitHub org remotes and push (`ausmt` + `ausmt-surveys`), unifying branch names.

**Timing rationale:** this is the cheapest possible moment — repos just init'd, **no remotes**, before the
AuScope push, before the data scales, before the first DOI, before slice-6 submissions create
un-rewritable history. It only gets more expensive.

## Status / next action

**EXECUTED 2026-06-17 — the history-preserving framework merge is done.** `ausmt-science`,
`ausmt-portal`, `ausmt-docs`, and `maintainer` were folded (full commit history preserved via
`git-filter-repo --to-subdirectory-filter`) into the `ausmt/` monorepo at `engine/`, `portal/`, `docs/`,
`maintainer/`; `ausmt-surveys` stays a separate repo. Path-scoped CI was moved to the repo-root
`.github/workflows/`, the engine↔surveys resolver paths were widened, `.readthedocs.yaml` was repointed
into `docs/`, and the cross-repo doc links were rewritten. Engine (52), portal (smoke + config-sync), and
surveys (13) suites are green from the new layout; a real build runs with the validator resolving across
the `ausmt/` ↔ `ausmt-surveys` boundary. The **legacy five repos are kept in place as a safety net** —
delete them once you've verified `ausmt/`.

**Deliberately NOT done yet (each its own focused pass):**
- ~~The **`contract/` package** extraction~~ — **DONE 2026-06-17.** `contract/columns.json` is the single
  source; `contract/generate.py` emits `engine/extract/_contract.py` (engine `*_COLUMNS`) +
  `portal/src/contract.js` (portal `C`/`SC`/`T` index maps); the engine imports its constants and the
  portal reads via the maps (32 raw indices / 101 sites converted); CI runs `generate.py --check`.
  Verified byte-identical products (engine) + populated headless smoke (portal). *(Optional later: move
  the JSON schemas under `contract/schema/` — they're engine-only single files, not a cross-consumer
  drift risk, so deferred.)*
- ~~**Distribution-name / provenance identity**~~ — **DONE 2026-06-17.** The engine distribution +
  `build_provenance.pipeline` were renamed `ausmt-science` → `ausmt` (pipeline now
  `ausmt/extract.build_portal`); done pre-publish, before any DOIs, so no published provenance breaks.
  (The internal import package dir stays `ausmt_science/`.)
- **GitHub remotes + branch-name unification** (`ausmt` `main` vs `ausmt-surveys` `master`) — at the push.
