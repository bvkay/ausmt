# AusMT engine image — runs extract.build_portal (mt_metadata/mth5 ingest -> portal/data JSON).
#
# Build context MUST be the ausmt repo root (docker build -f deploy/docker/engine.Dockerfile .):
#   COPY contract/ engine/  below are relative to that root. ausmt-surveys is a SEPARATE repo and is
#   NOT available in this build context (per contract) -- the validator it ships
#   (_validation/validate_survey.py) is supplied at RUNTIME via a read-only bind mount
#   (compose.yaml mounts the surveys-live checkout at /srv/surveys) and located through
#   AUSMT_VALIDATOR_PATH, the env pin that engine/extract/build_portal.py's _load_validator()
#   already reads for exactly this cross-repo case (ADR-001). Baking the surveys repo into this
#   image would require a second build context / git submodule wiring that the contract for this
#   image does not include; the bind-mount keeps ausmt-surveys on its own release cadence.
#
# Two stages:
#   1. locker  -- resolves the FLOATING direct pins (requirements-mtmetadata.txt +
#                 requirements-dev.txt) into a LINUX lock by INSTALLING them into a clean venv and
#                 `pip freeze`-ing the result. The committed
#                 environments/requirements-mtmetadata-lock.txt was captured on WINDOWS (it pins
#                 win32_setctime==1.2.0, a Windows-only package, with no environment marker -- an
#                 unconditional `pip install -r` of that file on Linux fails outright), so the lock
#                 is re-resolved fresh inside a linux/amd64 python:3.12-slim container.
#                 NOTE: pip-tools/pip-compile was deliberately RETIRED here after breaking twice in
#                 CI -- it couples to pip's private internals (pip 26 removed
#                 PackageFinder.allow_all_prereleases and pip-tools 7.4.1 crashed on it). A real
#                 install + freeze produces the same artifact (the platform-correct transitive
#                 closure) with zero private-API coupling.
#   2. runtime -- python:3.12-slim, non-root (ausmt:10001), installs the stage-1 lock, installs the
#                 engine editable, verifies the contract, and sets ENTRYPOINT to the build pipeline
#                 module. (An in-build stack-less pytest sanity lane used to run here; C39 removed it
#                 as redundant — see the HISTORY note below and the note at its former site.) No CMD:
#                 the actual --surveys/--out/--products/... args are supplied by the
#                 caller (compose.yaml's build-runner service, or an operator's `docker run`/
#                 `compose run`) -- build_portal.py has no meaningful zero-arg invocation
#                 (--out is `required=True`), so a bare `docker run ausmt-engine` intentionally
#                 exits on argparse's own usage error rather than silently doing nothing.
#
# HISTORY (C39, CI minutes economy): the runtime stage used to `RUN python -m pytest -q tests` as an
# in-build STACK-LESS sanity check — against whatever mt_metadata/mth5 the `locker` stage resolved
# for THIS build, NOT the pinned lock the image ships. That in-build run was the least truthful of
# the engine suite's three runs (it tested the locker-stage resolution, not the shipped stack) and
# was the only one costing ~4 min on every image build, so C39 REMOVED it (see the note at its former
# site further down this file). The FULL, pinned-lock pytest lane — the real release gate — runs in
# CI (.github/workflows/deploy-images.yml's `engine-full-tests` job) INSIDE the shipped image with the
# lock installed and the M5 skip tripwire; the fast source-tree gate runs in build-products.yml. No
# CI truth was given back: the two truthful runs remain, only the redundant least-truthful one is gone.

# ---------------------------------------------------------------------------
# Stage 1: locker -- resolve a LINUX-correct lock via clean-venv install + pip freeze.
# (pip-tools retired: see the stage notes in the header -- it broke on pip 26's internals.)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS locker

WORKDIR /lock
# The floating direct-pin files feed the resolve; the committed (Windows) lock is deliberately
# NOT an input here. requirements.txt MUST be copied too: requirements-dev.txt does
# `-r requirements.txt` (the very first CI run failed chasing that include into a missing file).
COPY engine/requirements.txt engine/requirements-mtmetadata.txt engine/requirements-dev.txt ./
# A clean venv so the freeze contains EXACTLY the resolved closure (no base-image site-packages
# noise); freeze output is the same artifact pip-compile produced -- pinned name==version lines --
# but obtained through pip's PUBLIC interface only.
RUN python -m venv /lockvenv \
 && /lockvenv/bin/pip install --no-cache-dir -r requirements-mtmetadata.txt -r requirements-dev.txt \
 && /lockvenv/bin/pip freeze > /lock/engine-lock.txt \
 && sed -i '1i # Generated in-image by deploy/docker/engine.Dockerfile (locker stage): clean-venv install of\n# requirements-mtmetadata.txt + requirements-dev.txt on linux/amd64 py3.12, then pip freeze.' /lock/engine-lock.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# U2: engine_commit fallback. This stage COPYs engine/ WITHOUT .git (see the COPY below), so
# build_identity()'s git resolution for THIS repo (ausmt/) is ALWAYS None in a container -- the
# first live deployment's footer showed "None - None - <date>" for exactly this reason. GIT_SHA is
# passed as a build-arg by deploy-images.yml (github.sha -- the FULL 40-char SHA; see that
# workflow's comment on why the full form was chosen over rev-parse --short's ~7 chars) and baked
# into the env var build_portal.py's build_identity() falls back to when git resolution yields
# None. Default "unknown" covers a bare `docker build` with no --build-arg (e.g. a local manual
# build) so the fallback chain still terminates in a real string, never a literal None.
ARG GIT_SHA=unknown
ENV AUSMT_ENGINE_COMMIT=${GIT_SHA}

# git is a REAL runtime dependency, not a build tool: build_identity() (C12) records the SURVEYS
# checkout's HEAD as source_commit in build.json/build_provenance.json -- the build<->data
# handshake. python:3.12-slim ships no git, so without this every containerised rebuild would
# silently record source_commit=null (the in-image test suite caught exactly that: fourth
# first-build failure, and the only one that exposed a genuine runtime gap rather than CI plumbing).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 10001, fixed and named so bind-mount permissions on the host are
# predictable -- see deploy/README.md for the /srv/ausmt ownership note).
RUN groupadd --gid 10001 ausmt \
 && useradd --uid 10001 --gid ausmt --home-dir /home/ausmt --create-home --shell /usr/sbin/nologin ausmt

# U2: /srv/surveys is a read-only bind mount of the HOST operator's ausmt-surveys checkout, owned by
# the host uid -- NOT by the ausmt(10001) user this container runs as. git >=2.35's dubious-ownership
# check refuses to run ANY command (including rev-parse) in a repo owned by a different uid, so
# build_identity()'s source_commit resolution silently failed (rev-parse errored -> caught -> None)
# on the very first live deployment. --system (not --global, which would write to $HOME and be
# per-user) so the allow-list applies regardless of which user's HOME git consults, and it is
# scoped to this ONE path -- NEVER '*' -- because /srv/surveys (the compose-mounted surveys
# checkout) is the ONLY foreign-owned repo this container should ever trust; a wildcard would trust
# any bind-mounted or COPYed repo a future compose change introduces, including untrusted input.
RUN git config --system --add safe.directory /srv/surveys

WORKDIR /app

# Install the Linux-resolved lock from stage 1 first (maximises Docker layer cache reuse across
# source-only edits -- this layer only invalidates when a *requirements* file changes).
COPY --from=locker /lock/engine-lock.txt /app/engine-lock.txt
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir -r /app/engine-lock.txt

# Repo content the pipeline needs at runtime: contract/ (single-source column + licence contract,
# read by both generate.py and the engine) and engine/ (the package + its tests). Portal/ is NOT
# copied into this image -- this is the extraction engine, not the static site; portal/data is a
# generated OUTPUT (bind-mounted volume at compose runtime), not an input.
COPY contract/ /app/contract/
COPY engine/ /app/engine/
# The contract gate below verifies BOTH generated artifacts, and generate.py --check reports a
# missing file as STALE (correct behaviour on a full checkout; third first-build failure was
# exactly this in-image). The engine image deliberately ships no portal -- copy in just the one
# generated portal artifact so the full check can run against real bytes, not absence.
COPY portal/src/contract.js /app/portal/src/contract.js

WORKDIR /app/engine
# Editable install, no deps (the lock already installed every dependency pinned). This install is
# what makes `python -m extract.build_portal` resolve: pyproject's [tool.setuptools.packages.find]
# includes BOTH ausmt_science* AND extract* (C37/F8), so `extract` is a real installed package on
# sys.path -- NOT a cwd artifact. (Pre-C37 the comment here claimed the install did this while it
# did not: `extract` was excluded from the package list, and the module only resolved because this
# WORKDIR put the engine dir on sys.path. That undocumented cwd contract is retired.) The image
# ENTRYPOINT below still runs from this WORKDIR, but resolution no longer DEPENDS on it; and the
# gw-runner's preview subprocess now passes an explicit cwd via AUSMT_ENGINE_DIR (runner.py, C37
# item 2) so its engine spawn is likewise independent of the inherited working directory.
RUN python -m pip install --no-cache-dir --no-deps -e .

# Contract gate: fail the image build itself if engine/extract/_contract.py has drifted from
# contract/columns.json (the same gate CI runs post-checkout; here it also proves the COPY above
# didn't miss a generated file).
RUN python ../contract/generate.py --check

# C39 (CI minutes economy): the in-build stack-less pytest lane that stood here was REMOVED —
# it was the least truthful of the engine suite's three runs and the only one paying ~4 min on
# every image build. The three runs were:
#   (a) THIS in-build `RUN python -m pytest -q tests` — ran against whatever mt_metadata/mth5 the
#       `locker` stage happened to resolve at build time, NOT the pinned lock the image ships (see
#       the HISTORY note at the top of this file, which admits exactly that). Least faithful → dropped.
#   (b) deploy-images.yml's `engine-full-tests` job — runs `pytest` INSIDE the SHIPPED image with
#       the pinned lock installed, piped through the M5 skip tripwire. This is the real release gate
#       and is UNCHANGED; it is also where the D3.1 topology skip ("gateway tree not shipped")
#       legitimately fires (engine image ships engine/ only, no /app/gateway), covered by the
#       ci_check_skips.py allow-list. That skip is unaffected by removing (a): the image topology at
#       (b) is identical, so the skip still fires there and its allow-list entry stays load-bearing.
#   (c) build-products.yml — the fast source-tree gate on the pinned lock. UNCHANGED.
# Nothing downstream in this Dockerfile depended on the deleted RUN's layer (the next step chowns
# /app wholesale; no file the pytest run produced is read later), so removing it is layer-safe.

# Drop root for the actual runtime process.
RUN chown -R ausmt:ausmt /app
USER ausmt

# AUSMT_VALIDATOR_PATH is set here (not baked to a specific ausmt-surveys checkout path) because
# /srv/surveys is the FIXED mount point compose.yaml uses for the surveys-live bind mount -- any
# compose/README deployment that follows that convention gets a working validator with zero extra
# config. Overridable at `docker run -e AUSMT_VALIDATOR_PATH=...` for non-compose invocations.
ENV AUSMT_VALIDATOR_PATH=/srv/surveys/_validation

ENTRYPOINT ["python", "-m", "extract.build_portal"]
