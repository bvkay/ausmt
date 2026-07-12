#!/bin/sh
# AusMT gateway entrypoint (incident 2026-07-11). This is the process-spawn seam for the gateway image
# (gateway.Dockerfile ENTRYPOINT); it sets the umask ONCE, then execs the real gateway so uvicorn AND
# every subprocess the gateway spawns (its `git` publish invocations) inherit it.
#
# WHY umask 0002. The gateway runs as uid 10002 and opens its sqlite state DB in WAL mode, which mints
# the `-wal`/`-shm` sidecars (gateway.sqlite-wal / -shm) fresh whenever the container is (re)created.
# The nightly HOST backup runs as the OPERATOR in the shared group 10002 and needs group-WRITE on those
# sidecars — opening a WAL DB writes to its directory even for a read (README "Backups & restore" /
# "Ownership prep"). The default umask 022 strips the group-write bit, so after a `docker compose up -d`
# (an image bump) the fresh sidecars were operator-UNWRITABLE and the backup FAILED two nights running
# until a manual `chmod g+rw` — the incident. umask 0002 makes every file the gateway creates
# group-writable, so the shared-group backup path stays healthy across container recreates with NO
# retroactive chmod. It only ADDS the group-write bit (0002 vs 022); it does not widen world perms.
#
# `exec` so the gateway becomes PID 1 (correct signal handling / clean shutdown). No CMD args are
# expected (the gateway's config surface is env-only — gateway.Dockerfile), but "$@" is forwarded for
# symmetry so an explicit `docker run … <args>` still reaches it.
umask 0002
exec python -m gateway "$@"
