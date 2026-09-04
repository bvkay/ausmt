# AusMT engine image — runs extract.build_portal (mt_metadata/mth5 ingest -> portal/data JSON).
#
# Build context MUST be the ausmt repo root (docker build -f deploy/docker/engine.Dockerfile .):
#   COPY contract/ engine/  below are relative to that root. ausmt-surveys is a SEPARATE repo and is
#   NOT available in this build context (per contract) -- the validator it ships
#   (_validation/validate_survey.py) is supplied at RUNTIME via a read-only bind mount
#   (compose.yaml mounts the surveys-live checkout at /srv/surveys) and located through
#   AUSMT_VALIDATOR_PATH, the env pin that engine/extract/build_portal.py's _load_validator()
#   already reads for exactly this cross-repo case. Baking the surveys repo into this
#   image would require a second build context / git submodule wiring that the contract for this
#   image does not include; the bind-mount keeps ausmt-surveys on its own release cadence.
#
# ONE stage (python:3.12-slim, non-root ausmt:10001): install the COMMITTED lock, install the engine
# editable, verify the contract, ENTRYPOINT to the build pipeline module. (There is NO in-build
# stack-less pytest run here; it is redundant with the two CI runs -- see the note further down.)
# No CMD: the actual --surveys/--out/--products/... args are supplied by
# the caller (compose.yaml's build-runner service, or an operator's `docker run`/`compose run`) --
# build_portal.py has no meaningful zero-arg invocation (--out is `required=True`), so a bare
# `docker run ausmt-engine` intentionally exits on argparse's own usage error rather than silently
# doing nothing.
#
# REPRODUCIBILITY. There is NO `locker` stage here: a stage that IGNORES the committed
# engine/environments/requirements-mtmetadata-lock.txt and re-resolves the floating direct
# pins fresh on every build would be justified only by this claim:
#
#   "the committed lock was captured on WINDOWS (it pins win32_setctime==1.2.0, a Windows-only
#    package, with no environment marker -- an unconditional `pip install -r` of that file on Linux
#    fails outright)"
#
# That claim is FALSE and the bypass it justified was the real problem. win32_setctime ships as
# win32_setctime-1.2.0-py3-none-any.whl, a pure-python universal wheel that installs on any platform;
# every one of the lock's pins resolves to a linux/amd64 CPython 3.12 wheel (verified by a
# cross-platform resolve of the whole file). Nothing ever failed outright.
#
# What the bypass DID cost was reproducibility: the resolve floated, so the image shipped whatever
# PyPI held at build time rather than the VERIFIED stack. Re-resolving the same direct pins
# produced numpy 2.5.1 / scipy 1.18.0 / pandas 3.0.5 / xarray 2026.7.0 against the lock's
# verified numpy 2.4.6 / scipy 1.17.1 / pandas 3.0.3 / xarray 2026.4.0. The lock exists precisely
# because normalize.py's metadata conditioning is version-sensitive, so the image was shipping an
# unverified science stack while the repo carried a verified one.
#
# The image now installs the committed lock. Its three genuinely Windows-only pins (colorama,
# tzdata, win32_setctime) carry environment markers taken from their upstream metadata, so they are
# skipped here honestly rather than routed around. The test tooling on top is installed CONSTRAINED
# by the same lock, so resolving pytest/jsonschema/ruff can never move the science stack.
#
# pip-tools/pip-compile stays RETIRED (it broke twice in CI: pip 26 removed
# PackageFinder.allow_all_prereleases and pip-tools 7.4.1 crashed on it). Refreshing the lock is a
# deliberate act documented in the lock file's own header, not a build-time side effect.
#
# HISTORY (CI minutes economy): the runtime stage used to `RUN python -m pytest -q tests` as an
# in-build STACK-LESS sanity check — against whatever mt_metadata/mth5 the `locker` stage resolved
# for THIS build, NOT the pinned lock the image ships. That in-build run was the least truthful of
# the engine suite's three runs (it tested a build-time resolution, not the shipped stack) and
# was the only one costing ~4 min on every image build (see the note further down this file).
# The FULL, pinned-lock pytest run, the real release gate, runs in
# CI (.github/workflows/deploy-images.yml's `engine-full-tests` job) INSIDE the shipped image with the
# lock installed and the skip tripwire; the fast source-tree gate runs in build-products.yml. Two
# truthful runs remain, and the redundant least-truthful one is not among them.
# (With no separate build-time resolve there is nothing for a run to be untruthful about: the image
# and the release gate both install the one committed lock.)

FROM python:3.12-slim AS runtime

# engine_commit fallback. This stage COPYs engine/ WITHOUT .git (see the COPY below), so
# build_identity()'s git resolution for THIS repo (ausmt/) is ALWAYS None in a container -- the
# first live deployment's footer showed "None - None - <date>" for exactly this reason. GIT_SHA is
# passed as a build-arg by deploy-images.yml (github.sha -- the FULL 40-char SHA; see that
# workflow's comment on why the full form was chosen over rev-parse --short's ~7 chars) and baked
# into the env var build_portal.py's build_identity() falls back to when git resolution yields
# None. Default "unknown" covers a bare `docker build` with no --build-arg (e.g. a local manual
# build) so the fallback chain still terminates in a real string, never a literal None.
ARG GIT_SHA=unknown
ENV AUSMT_ENGINE_COMMIT=${GIT_SHA}

# git is a REAL runtime dependency, not a build tool: build_identity() records the SURVEYS
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

# /srv/surveys is a read-only bind mount of the HOST operator's ausmt-surveys checkout, owned by
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

# Install the COMMITTED lock first (maximises Docker layer cache reuse across source-only edits --
# this layer only invalidates when a *requirements* file changes). The requirements files are COPYed
# on their own, ahead of the bulk `COPY engine/` further down, so an edit to engine source does not
# invalidate this expensive layer.
#
# Two installs, in this order and for this reason:
#   1. the LOCK -- the verified, pinned science stack this image ships. Its three Windows-only pins
#      carry environment markers, so on linux/amd64 they are skipped and the remaining 32 pins all
#      resolve to CPython 3.12 wheels.
#   2. the test tooling (pytest/jsonschema/ruff from requirements-dev.txt) CONSTRAINED by that same
#      lock (-c). deploy-images.yml's `engine-full-tests` job runs the engine suite INSIDE this
#      image, so the tooling has to be here; -c guarantees that resolving it cannot upgrade,
#      downgrade or re-pin anything the lock already fixed. requirements-dev.txt pulls in
#      requirements.txt (loose floors), every one of which the lock already satisfies, so this step
#      adds only the test packages. jsonschema is the one genuine float; the pip-freeze artifact
#      deploy-images.yml uploads records what any given image actually got.
COPY engine/requirements.txt engine/requirements-dev.txt /app/engine/
COPY engine/environments/requirements-mtmetadata-lock.txt /app/engine/environments/
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir -r /app/engine/environments/requirements-mtmetadata-lock.txt \
 && python -m pip install --no-cache-dir \
      -c /app/engine/environments/requirements-mtmetadata-lock.txt \
      -r /app/engine/requirements-dev.txt

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
# includes BOTH ausmt_science* AND extract*, so `extract` is a real installed package on
# sys.path -- NOT a cwd artifact. `extract` must stay in that package list: with it excluded the
# module resolves only because this WORKDIR puts the engine dir on sys.path, which is a cwd
# contract nothing states. The image
# ENTRYPOINT below still runs from this WORKDIR, but resolution must not DEPEND on it; and the
# gw-runner's preview subprocess passes an explicit cwd via AUSMT_ENGINE_DIR (runner.py)
# so its engine spawn is likewise independent of the inherited working directory.
RUN python -m pip install --no-cache-dir --no-deps -e .

# Contract gate: fail the image build itself if engine/extract/_contract.py has drifted from
# contract/columns.json (the same gate CI runs post-checkout; here it also proves the COPY above
# didn't miss a generated file).
RUN python ../contract/generate.py --check

# CI minutes economy: NO in-build stack-less pytest run stands here.
# Such a run would be the least truthful of the engine suite's three runs and the only one paying
# ~4 min on every image build. The three runs were:
#   (a) an in-build `RUN python -m pytest -q tests` — ran against whatever mt_metadata/mth5 the
#       `locker` stage happened to resolve at build time, NOT the pinned lock the image ships (see
#       the HISTORY note at the top of this file, which admits exactly that). Least faithful → dropped.
#   (b) deploy-images.yml's `engine-full-tests` job — runs `pytest` INSIDE the SHIPPED image with
#       the pinned lock installed, piped through the skip tripwire. This is the real release gate
#       and is UNCHANGED; it is also where the topology skip ("gateway tree not shipped")
#       legitimately fires (engine image ships engine/ only, no /app/gateway), covered by the
#       ci_check_skips.py allow-list. That skip is unaffected by removing (a): the image topology at
#       (b) is identical, so the skip still fires there and its allow-list entry stays load-bearing.
#   (c) build-products.yml — the fast source-tree gate on the pinned lock. UNCHANGED.
# Nothing downstream in this Dockerfile depended on the deleted RUN's layer (the next step chowns
# /app wholesale; no file the pytest run produced is read later), so removing it is layer-safe.
# (b)'s description of itself, "with the pinned lock installed", is TRUE only while no locker stage
# stands above. A shipped image carrying a locker's floating resolve leaves the release gate
# testing a stack the repo has never verified.

# Drop root for the actual runtime process.
RUN chown -R ausmt:ausmt /app
USER ausmt

# AUSMT_VALIDATOR_PATH is set here (not baked to a specific ausmt-surveys checkout path) because
# /srv/surveys is the FIXED mount point compose.yaml uses for the surveys-live bind mount -- any
# compose/README deployment that follows that convention gets a working validator with zero extra
# config. Overridable at `docker run -e AUSMT_VALIDATOR_PATH=...` for non-compose invocations.
ENV AUSMT_VALIDATOR_PATH=/srv/surveys/_validation

ENTRYPOINT ["python", "-m", "extract.build_portal"]
