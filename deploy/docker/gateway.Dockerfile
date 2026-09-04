# AusMT gateway image — runs the FastAPI submission gateway (gateway/, contract C10). Upload ->
# zip-safety -> clamd scan -> job queue -> tokenised status. The gateway NEVER parses EDI/YAML and
# NEVER runs the validator/engine itself: content parsing happens in the gw-runner service, which is
# the ENGINE image with a user:10002 + network_mode:none override (see compose.yaml's gateway
# profile). This image therefore ships ONLY the gateway package + its light web deps.
#
# Build context MUST be the ausmt repo root (docker build -f deploy/docker/gateway.Dockerfile .):
#   COPY gateway/ below is relative to that root, matching engine/portal Dockerfile convention.
#
# ONE stage, mirroring engine.Dockerfile (which retired pip-tools deliberately -- read its header):
# python:3.12-slim, non-root (gwuser:10002 -- a NEW uid distinct from the engine's 10001 so a
# compromised gateway stack cannot touch published site-data even via a uid collision; design §1),
# installs the COMMITTED lock + the gateway package, and sets the entrypoint to `python -m gateway`
# (uvicorn on :8000, container-internal).
#
# REPRODUCIBILITY. There is NO `locker` stage here. A stage that resolves
# gateway/requirements.txt (deliberate FLOORS: fastapi>=..., starlette>=..., the tested majors) into a
# lock INSIDE the build throws it away with the stage. Nothing is committed, so two builds of the
# same commit could ship different dependency versions and a PyPI release could break the image with
# no repo change at all. That is a sharper risk here than in a typical web app: gateway/upload.py
# imports starlette.formparsers.MultiPartParser DIRECTLY (a non-public API, see that module's header)
# to cap a multipart stream by bytes, and a floating starlette can move or rename it without any
# deprecation cycle. Floors break exactly that way.
#
# The resolved closure is now COMMITTED at gateway/requirements-lock.txt (linux/amd64, CPython 3.12,
# the platform of the base image below) and this image installs it. requirements.txt keeps the floors
# as the human-readable statement of intent; the lock is what actually ships. Refreshing it is a
# deliberate act with a ritual documented in the lock file's own header, not a build-time side effect.
# Every published image also uploads its `pip freeze` as a CI artifact (deploy-images.yml), so the
# exact stack of any shipped image is recorded independently of this file.

FROM python:3.12-slim AS runtime

# GIT_SHA build-arg, mirroring engine.Dockerfile: baked into an env var so a startup log line can
# identify the built commit. Default "unknown" covers a bare `docker build` with no --build-arg.
ARG GIT_SHA=unknown
ENV AUSMT_GATEWAY_COMMIT=${GIT_SHA}

# Publish flow (design §5 v2) shells out to `git` ONLY - stage/commit/push into surveys-live. It
# does NOT invoke the build: demo publish is COMMIT-AND-PUSH ONLY, and the operator runs
# `make rebuild-data` by hand afterward. So NO `make` here, and crucially NO Docker socket — which is
# exactly what keeps the C10 §0 no-socket invariant intact. `git` is not in python:3.12-slim, so
# install it (+ openssh-client so a `git push` over an ssh deploy key at /srv/git-creds authenticates;
# ca-certs for an https remote). The gateway still NEVER parses EDI/YAML; it only invokes git.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user, uid/gid 10002 (fixed + named so the /srv/ausmt/gateway bind-mount ownership on the
# host is predictable — see deploy/README.md). 10002 is DELIBERATELY distinct from the engine's
# 10001 (design §1): the gateway stack owns only its own gw/ tree, never the published site-data.
RUN groupadd --gid 10002 gwuser \
 && useradd --uid 10002 --gid gwuser --home-dir /home/gwuser --create-home --shell /usr/sbin/nologin gwuser

WORKDIR /app

# Install the committed lock first (maximises layer-cache reuse across source-only edits: this layer
# only invalidates when the lock itself changes). httpx/pytest are absent from it on purpose, they
# are dev-only (gateway/requirements-dev.txt) and must never enter the image.
COPY gateway/requirements-lock.txt /app/gateway-requirements-lock.txt
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir -r /app/gateway-requirements-lock.txt

# The gateway package. Nothing else from the repo is needed at runtime: the gateway is content-blind
# (no contract/, no engine/, no portal/) — those belong to the gw-runner (engine image) which the
# compose gateway profile wires up separately.
COPY gateway/ /app/gateway/

# The entrypoint wrapper sets umask 0002 before exec'ing the gateway, so the sqlite WAL sidecars the
# gateway mints stay group-writable for the shared-group host backup across container recreates
# (see the script header). `chmod` because a Windows/MSYS build host does not
# carry the exec bit through COPY. Installed root-owned before the USER drop below.
COPY deploy/docker/gateway-entrypoint.sh /usr/local/bin/gateway-entrypoint.sh
RUN chmod 0755 /usr/local/bin/gateway-entrypoint.sh

# AUSMT_GW_DATA is the mount point compose.yaml uses for the gateway's gw/ tree (state/incoming/
# quarantine/jobs). Baked here so a compose deployment following that convention works with no extra
# config; overridable at `docker run -e AUSMT_GW_DATA=...`. AUSMT_SUBMIT_KEY is intentionally NOT set
# here — the app fail-closes at startup if it is unset/short (design §3), so the operator MUST supply
# it via compose env/secret; baking a default would be a security hole.
ENV AUSMT_GW_DATA=/gw

# Drop root for the actual runtime process.
RUN mkdir -p /gw && chown -R gwuser:gwuser /app /gw
USER gwuser

EXPOSE 8000

# The entrypoint wrapper sets umask 0002 (durable group-writable WAL sidecars, incident)
# then execs `python -m gateway`, which runs create_app() (fail-closes on a missing submit key) then
# uvicorn on 0.0.0.0:8000 — container-internal; compose publishes it loopback-only and Caddy fronts it
# same-origin (design §1). No CMD args: the config surface is env-only (design §7).
ENTRYPOINT ["/usr/local/bin/gateway-entrypoint.sh"]
