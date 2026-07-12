# AusMT gateway image — runs the FastAPI submission gateway (gateway/, contract C10). Upload ->
# zip-safety -> clamd scan -> job queue -> tokenised status. The gateway NEVER parses EDI/YAML and
# NEVER runs the validator/engine itself: content parsing happens in the gw-runner service, which is
# the ENGINE image with a user:10002 + network_mode:none override (see compose.yaml's gateway
# profile). This image therefore ships ONLY the gateway package + its light web deps.
#
# Build context MUST be the ausmt repo root (docker build -f deploy/docker/gateway.Dockerfile .):
#   COPY gateway/ below is relative to that root, matching engine/portal Dockerfile convention.
#
# Two stages, mirroring engine.Dockerfile (which retired pip-tools deliberately — read its header):
#   1. locker  -- resolves the floating direct pins (gateway/requirements.txt) into a LINUX lock by
#                 INSTALLING them into a clean venv and pip-freezing the result. Same rationale as
#                 the engine image: a real install + freeze gives the platform-correct transitive
#                 closure through pip's PUBLIC interface only, with zero pip-tools private-API
#                 coupling (pip-tools broke twice in CI on pip's internals — see engine.Dockerfile).
#   2. runtime -- python:3.12-slim, non-root (gwuser:10002 — a NEW uid distinct from the engine's
#                 10001 so a compromised gateway stack cannot touch published site-data even via a
#                 uid collision; design §1), installs the stage-1 lock + the gateway package, and
#                 sets the entrypoint to `python -m gateway` (uvicorn on :8000, container-internal).

# ---------------------------------------------------------------------------
# Stage 1: locker -- resolve a LINUX-correct lock via clean-venv install + pip freeze.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS locker

WORKDIR /lock
# Only the runtime requirements feed the resolve (httpx/pytest are dev-only and must NOT enter the
# image). requirements.txt lists fastapi + uvicorn + python-multipart — the whole runtime surface.
COPY gateway/requirements.txt ./
RUN python -m venv /lockvenv \
 && /lockvenv/bin/pip install --no-cache-dir -r requirements.txt \
 && /lockvenv/bin/pip freeze > /lock/gateway-lock.txt \
 && sed -i '1i # Generated in-image by deploy/docker/gateway.Dockerfile (locker stage): clean-venv install of\n# gateway/requirements.txt on linux/amd64 py3.12, then pip freeze.' /lock/gateway-lock.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# GIT_SHA build-arg, mirroring engine.Dockerfile: baked into an env var so a startup log line can
# identify the built commit. Default "unknown" covers a bare `docker build` with no --build-arg.
ARG GIT_SHA=unknown
ENV AUSMT_GATEWAY_COMMIT=${GIT_SHA}

# C11 publish flow (design §5 v2) shells out to `git` ONLY — stage/commit/push into surveys-live. It
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

# Install the Linux-resolved lock from stage 1 first (maximises layer-cache reuse across source-only
# edits — this layer only invalidates when gateway/requirements.txt changes).
COPY --from=locker /lock/gateway-lock.txt /app/gateway-lock.txt
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir -r /app/gateway-lock.txt

# The gateway package. Nothing else from the repo is needed at runtime: the gateway is content-blind
# (no contract/, no engine/, no portal/) — those belong to the gw-runner (engine image) which the
# compose gateway profile wires up separately.
COPY gateway/ /app/gateway/

# The entrypoint wrapper sets umask 0002 before exec'ing the gateway, so the sqlite WAL sidecars the
# gateway mints stay group-writable for the shared-group host backup across container recreates
# (incident 2026-07-11 — see the script header). `chmod` because a Windows/MSYS build host does not
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

# The entrypoint wrapper sets umask 0002 (durable group-writable WAL sidecars, incident 2026-07-11)
# then execs `python -m gateway`, which runs create_app() (fail-closes on a missing submit key) then
# uvicorn on 0.0.0.0:8000 — container-internal; compose publishes it loopback-only and Caddy fronts it
# same-origin (design §1). No CMD args: the config surface is env-only (design §7).
ENTRYPOINT ["/usr/local/bin/gateway-entrypoint.sh"]
