#!/usr/bin/env python3
"""C18 — content-addressed build cache for per-station products.

A full portal build re-parses every EDI through mt_metadata and re-runs normalize()'s served-XML
round-trip for every served station, even when a one-line survey.yaml edit changed nothing about
those stations. This module is a content-addressed cache of the two expensive per-station products
so an incremental rebuild skips the parse and the round-trip for unchanged stations.

Design: maintainer/C18-BuildCacheDesign.md (FROZEN, as amended by Amendment A1). The invariants
this module upholds:

  * The cache may only ever change build SPEED, never output bytes. `scripts/verify.py` stays full,
    byte-re-hashing and cache-blind; a warm build is byte-identical to the build that populated its
    cache (proven by test; Amendment A1c records why INDEPENDENT full builds are not the baseline —
    mt_metadata stamps a wall-clock <CreateTime> in every written XML).
  * The key is derived from the SOURCE EDI content sha + a coarse engine-commit salt + library
    versions + the positional/schema contract + the whole survey.yaml digest. A byte-changed EDI,
    an engine commit, a library upgrade, a contract change, or ANY survey.yaml edit all miss.
  * A DEGENERATE salt (unknown engine commit, or a dirty checkout where a git checkout exists)
    silently DISABLES the cache for that build — no reads, no writes. A degenerate/ambiguous salt
    must never key a cache. --raw builds are a POLICY exclusion with the same inert behaviour
    (Amendment A1a: --seed-meta feeds served citations but is not a key component).
  * Entries are SELF-VERIFYING (Amendment A1b): each file is `<sha256-hex-of-payload>\n<payload>`,
    written temp-then-atomic-rename. Every read re-hashes the payload; a mismatch (disk corruption,
    tampering) DELETES the entry, counts in the `corrupt` counter, tallies as a MISS, and the
    caller recomputes — a poisoned VALUE can never ship. This is the cache's own job: the
    content-addressed KEY derives from inputs, while verify.py's manifest check (whose shas are
    computed FROM the served bytes) cannot see a poisoned value that flowed through the build; it
    guards post-build tampering of the served tree only.

The cache is a passive store: it makes no policy decisions about WHAT is cacheable, only about
whether a given key is present and readable. The build seams decide what to compute-and-put.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Prune policy defaults — operator-tunable, single-sourced here. Adjudicated v1 policy
# (Amendment A1d): mtime-age window + size cap, oldest-first. The design's "20 builds" window is
# NOT implemented (the cache keeps no per-build ledger); age is the operator-meaningful bound.
CACHE_MAX_MB_DEFAULT = 2048          # AUSMT_CACHE_MAX_MB overrides (size cap, oldest-first eviction)
PRUNE_MAX_AGE_DAYS = 90              # drop entries untouched for this many days

CACHE_MODES = ("rw", "ro", "refresh")


def _dirty_checkout(cwd: Path) -> bool | None:
    """Whether the git checkout containing `cwd` has uncommitted changes.

    Returns True (dirty) / False (clean) when `cwd` sits inside a git work tree; None when there is
    NO git checkout at all (a bare pip install / container copy without .git / not a repo). The
    None case is NOT "dirty" — a container build legitimately has no .git and keys off the baked-in
    engine-commit env var instead (see is_salt_degenerate)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    except Exception:  # noqa: BLE001  (git absent / not executable — treat as "no checkout")
        return None
    if out.returncode != 0:
        return None          # not a work tree (fatal: not a git repo) -> no checkout here
    return bool(out.stdout.strip())


def is_salt_degenerate(engine_commit, checkout_dir: Path | None) -> tuple[bool, str]:
    """Integrity gate (design §2.2): is the cache salt degenerate, so incremental must be DISABLED
    for this build (treated as full — no reads, no writes)?

    Degenerate iff EITHER:
      * the engine commit is unknown/None/the literal "unknown" (an unresolvable build identity), OR
      * a git checkout EXISTS at `checkout_dir` and is dirty (uncommitted changes) — the coarse
        commit salt would then key a cache against source that does not match that commit.

    A container build with no .git resolves engine_commit from AUSMT_ENGINE_COMMIT and has no
    checkout to be dirty; that is NOT degenerate. In production that env var is ALWAYS baked:
    docker/engine.Dockerfile takes ARG GIT_SHA -> ENV AUSMT_ENGINE_COMMIT and deploy-images.yml
    passes github.sha, so a current image has a healthy salt and the cache fires (the null commits
    once observed in the live box's build.json came from a stale pre-GIT_SHA-bake image, not from
    this gate). Returns (degenerate, reason)."""
    if not engine_commit or str(engine_commit).strip().lower() in ("", "none", "unknown"):
        return True, f"engine commit unknown ({engine_commit!r}) — a degenerate salt cannot key a cache"
    if checkout_dir is not None:
        dirty = _dirty_checkout(Path(checkout_dir))
        if dirty is True:
            return True, "engine checkout is dirty (git status --porcelain non-empty) — the coarse " \
                         "commit salt does not match the working tree; refusing to key a cache"
    return False, ""


def contract_schema_digest(engine_root: Path) -> str:
    """sha256 over the positional-column contract + the product schema versions (design §2.4). A
    column append (contract/columns.json) or an mtcat/manifest schema-version bump changes cached
    row shapes / cached XML validity, so it must invalidate the cache. Missing files degrade to an
    empty-string component rather than crashing — a build without a resolvable contract simply has a
    stable (if coarse) digest, and the engine-commit salt still moves on any real change."""
    parts: list[str] = []
    # contract/columns.json is a SIBLING of engine/ (contract/ at the repo root); engine_root is
    # engine/, so its parent holds contract/. Fall back to a bundled copy is unnecessary — a source
    # tree always has one, a container bakes the generated _contract.py which we hash instead below.
    candidates = [
        engine_root.parent / "contract" / "columns.json",
        engine_root / "extract" / "_contract.py",   # generated form, always present in the engine image
        engine_root / "schema" / "mtcat.schema.json",
        engine_root / "schema" / "manifest.schema.json",
    ]
    for c in candidates:
        try:
            parts.append(c.read_text(encoding="utf-8"))
        except OSError:
            parts.append("")   # absent component -> stable empty marker (never crashes the build)
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


# NOTE (Amendment A4): the per-survey yaml digest (design §2.5) is no longer derived here. It is
# computed in build_portal.discover_work from the SAME bytes the survey metadata is parsed from —
# one read feeds both, so a mid-build survey.yaml edit can never key products under a digest their
# metadata does not match (the 2026-07-07 poisoned-cache incident). The path-taking helper that
# lived here was deliberately DELETED, not deprecated: any reappearance of a read-the-yaml-again
# digest call site is the incident's window reopening.


class BuildCache:
    """A content-addressed store of per-station products under `<root>/<k[:2]>/<k>.<ext>`.

    One instance per build. Holds the shared salt (engine commit + library versions + contract +
    per-survey survey.yaml digest) and derives a per-station key from it plus the source EDI sha.
    Tracks hit/miss/write counters (deterministic, asserted by tests — never wall-clock). When the
    salt is degenerate the instance is INERT: enabled is False, get() always misses and put() is a
    no-op, and the counters prove no reads or writes happened.
    """

    def __init__(self, root: Path, *, engine_commit, lib_versions: dict,
                 contract_digest: str, mode: str = "rw", checkout_dir: Path | None = None,
                 max_mb: int | None = None, disabled_reason: str = ""):
        self.root = Path(root)
        self.mode = mode if mode in CACHE_MODES else "rw"
        self.engine_commit = engine_commit
        self.lib_versions = dict(lib_versions or {})
        self.contract_digest = contract_digest or ""
        self.max_mb = int(max_mb) if max_mb is not None else _env_max_mb()
        # Counters (design §4.6): deterministic build-report evidence, NOT wall-clock timing.
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.corrupt = 0   # A1b: entries whose embedded payload checksum failed on read (deleted+recomputed)
        # A4 forensics: environment-induced I/O failures, distinct from content-addressed misses.
        # write_errors = puts dropped after the rename retries were exhausted (AV/indexer lock class);
        # read_errors  = present-but-unreadable entries (counted as misses for the §4.6 arithmetic,
        # but attributable — a lock-induced spurious miss is not a cold miss).
        self.write_errors = 0
        self.read_errors = 0
        # `disabled_reason` is a POLICY exclusion (e.g. Amendment A1a: --raw builds, whose seed-meta
        # citations feed served XML but are not a key component) — behaviourally identical to a
        # degenerate salt: the cache is inert, no reads, no writes.
        if disabled_reason:
            self.degenerate, self.degenerate_reason = True, disabled_reason
        else:
            self.degenerate, self.degenerate_reason = is_salt_degenerate(engine_commit, checkout_dir)
        # The stable, per-survey salt component is injected via key(); the fixed part is precomputed.
        self._fixed_salt = "\x00".join([
            # Cache-format version tag. v2 = self-verifying entries (digest-line + payload, A1b);
            # v3 (C18b, Amendment A3) = the served-XML meta blob carries `survey_digest` (the digest
            # the entry was KEYED under), consumed by the digest-stamp sidecar + the verify.py
            # consistency gate; v4 (C20) = the parse product changed SHAPE — tf.json rows grew 10 -> 18
            # (rho/phase error columns + full complex tipper) and the placeholder-tipper mask now
            # withholds filler tippers, so a pre-C20 cached parse would replay 10-wide/unmasked rows.
            # Bumping the tag re-keys EVERY blob, so pre-C20 entries never resolve — a clean MISS,
            # counted as a miss, never a replay of a stale-shape parse. One full re-derive on the first
            # build after C20 lands; then warm again. (The contract_digest below ALSO shifts on the
            # column append; the tag bump is the explicit, self-documenting belt-and-suspenders — same
            # discipline as C18b.) Old-format entries age out via the prune.
            # v5 (C46-W3a) = the served-XML CONTENT changed corpus-wide: the EMTF-XML Copyright block now
            # carries the survey's real licence-derived release_status + conditions_of_use instead of
            # mt_metadata's default "Unrestricted Release"/"may be copied freely" boilerplate (a truth
            # fix in ausmt_science.ingest.normalize.condition_tf). That formatter change is not captured
            # by the source-EDI sha, the survey.yaml digest, or the contract digest, so a warm pre-C46
            # cache would REPLAY the boilerplate XML for an unchanged EDI on the same engine commit.
            # Bumping the tag forces one clean full re-derive so every served XML is the truthful form.
            "ausmt-c46-cache-v5",
            str(engine_commit),                                      # coarse engine-commit salt (§2.2)
            json.dumps(self.lib_versions, sort_keys=True),           # mt_metadata (+ mth5) versions (§2.3)
            self.contract_digest,                                    # columns + schema digest (§2.4)
        ])
        # A4 forensics: a short fingerprint of the FULL fixed salt (version tag + engine commit +
        # lib versions + contract digest). Two builds that should key identically expose identical
        # fingerprints; a mid-process salt flip (the C18c-flake class: moving HEAD, transient
        # rev-parse failure, contract-file read failure) is attributable from the build report alone.
        self.salt_fp = hashlib.sha256(self._fixed_salt.encode("utf-8")).hexdigest()[:12]
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        """The cache participates in this build only when its salt is non-degenerate. A degenerate
        salt yields an inert cache (no reads, no writes) — the whole build runs full."""
        return not self.degenerate

    def key(self, *, edi_sha: str, survey_digest: str, kind: str) -> str:
        """Derive the content-addressed key for one station product. `kind` namespaces the two
        distinct products (parse rows vs served XML) so they never collide on one key. The key binds
        EVERY salt field (§2): source EDI sha + engine commit + lib versions + contract + this
        survey's whole-yaml digest."""
        material = "\x00".join([self._fixed_salt, str(edi_sha), str(survey_digest or ""), str(kind)])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _path(self, key: str, ext: str) -> Path:
        return self.root / key[:2] / f"{key}.{ext}"

    def get_bytes(self, key: str, ext: str) -> bytes | None:
        """Read a cached blob's PAYLOAD, or None on miss / disabled / refresh-mode / integrity
        failure. Increments hits on a verified read, misses otherwise. `refresh` mode forces a miss
        (ignore hits and rewrite) — the forced-full-rebuild escape hatch that still repopulates.

        A1b integrity: the entry is `<sha256-hex>\\n<payload>`; the payload is RE-HASHED on every
        read. A malformed entry or a digest mismatch (bit rot, tampering) is deleted, counted in
        `corrupt`, tallied as a MISS, and None returned so the caller recomputes — fail-safe."""
        if not self.enabled or self.mode == "refresh":
            self.misses += 1
            return None
        p = self._path(key, ext)
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            self.misses += 1
            return None
        except OSError:
            # A4: a PRESENT-but-unreadable entry (Windows AV/indexer lock, permissions) is not a
            # normal cold miss. Still tallied as a miss (the §4.6 arithmetic and the recompute path
            # are unchanged) but counted in read_errors so a lock-induced spurious miss is
            # attributable from the build report instead of masquerading as content drift.
            self.read_errors += 1
            self.misses += 1
            return None
        head, sep, payload = raw.partition(b"\n")
        if not sep or head != hashlib.sha256(payload).hexdigest().encode("ascii"):
            self.corrupt += 1
            self.misses += 1
            _safe_unlink(p)      # drop the bad entry; the caller's recompute re-puts a good one
            return None
        self.hits += 1
        self._touch(key, ext)   # mark recently-used for the age prune policy
        return payload

    def get_json(self, key: str, ext: str = "json"):
        """Read a cached JSON blob (the parse-rows / xml-meta product), or None on miss. Shares the
        get_bytes counter + integrity semantics. A checksum-VALID payload that fails to decode is a
        put-side defect (put_json always writes valid JSON), handled with the same fail-safe
        discipline: revoke the counted hit, count corrupt + miss, drop the entry, recompute."""
        raw = self.get_bytes(key, ext)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.hits -= 1
            self.misses += 1
            self.corrupt += 1
            _safe_unlink(self._path(key, ext))
            return None

    def revoke_hit(self) -> None:
        """Correct the tally when a PAIRED read turns out unusable after this cache already counted
        a hit — the torn-pair case at the served-XML seam: the xml blob hit but its meta sibling
        missed, so the pair produced nothing and the station recomputes. The sibling's own get
        already tallied its miss; this only revokes the phantom hit (Amendment A1b/c — mirrors
        get_json's internal corrupt-payload discipline)."""
        self.hits -= 1

    def put_bytes(self, key: str, ext: str, data: bytes) -> None:
        """Write a blob to the cache as a SELF-VERIFYING entry (`<sha256-hex-of-payload>\\n<payload>`,
        A1b), temp-then-atomic-rename (design §2). No-op when disabled or in read-only (`ro`) mode.
        os.replace is atomic within a filesystem on both POSIX and Windows, so a concurrent or
        interrupted build never observes a half-written entry."""
        if not self.enabled or self.mode == "ro":
            return
        p = self._path(key, ext)
        tmp = None   # assigned inside the try: a mkdir failure must not leave the cleanup referencing it
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / f".{key}.{ext}.{os.getpid()}.{time.time_ns()}.tmp"
            tmp.write_bytes(hashlib.sha256(data).hexdigest().encode("ascii") + b"\n" + data)
            # A4: retry the rename — on Windows an AV/on-access scanner briefly holding the fresh tmp
            # (or the destination) raises a transient PermissionError, and a silently dropped entry
            # is a spurious miss on the next build (one C18c-flake candidate). Three attempts with a
            # short backoff clears a scanner hold; a still-failing write counts in write_errors.
            last_err = None
            for attempt in range(3):
                try:
                    os.replace(tmp, p)          # atomic rename (POSIX + Windows)
                    self.writes += 1
                    return
                except OSError as e:
                    last_err = e
                    if attempt < 2:
                        time.sleep(0.05 * (attempt + 1))
            raise last_err
        except OSError as e:  # noqa: BLE001  (a cache write must never break the build)
            self.write_errors += 1
            print(f"  [cache] WARN could not write {p.name}: {type(e).__name__}: {e}", file=sys.stderr)
            try:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def put_json(self, key: str, obj, ext: str = "json") -> None:
        """Write a JSON-serializable object as a cache blob (the parse-rows product)."""
        self.put_bytes(key, ext, json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def _touch(self, key: str, ext: str) -> None:
        """Bump the entry's mtime so the age/build prune keeps recently-USED entries, not just
        recently-written ones (a hit on an old-but-live station must not let it be pruned)."""
        try:
            os.utime(self._path(key, ext), None)
        except OSError:
            pass

    def counters(self) -> dict:
        """The deterministic hit/miss/write/corrupt tally for the build log + report (design §4.6).
        salt_fp (A4) fingerprints the fixed salt so cross-build key-space drift is observable."""
        return {"enabled": self.enabled, "mode": self.mode, "hits": self.hits,
                "misses": self.misses, "writes": self.writes, "corrupt": self.corrupt,
                "write_errors": self.write_errors, "read_errors": self.read_errors,
                "degenerate": self.degenerate, "reason": self.degenerate_reason,
                "salt_fp": self.salt_fp}

    # ---- lifecycle: prune at the end of a successful build (design §3) --------------------------

    def prune(self) -> dict:
        """Drop entries untouched for PRUNE_MAX_AGE_DAYS, then enforce the size cap oldest-first.
        Runs at the end of a successful build. A prune failure must never fail the build; returns a
        small summary. Adjudicated v1 policy (Amendment A1d): mtime-age + size cap ONLY — the
        design's original "20 builds" window is not implemented (the cache keeps no per-build
        ledger); age is the operator-meaningful bound, the size cap the hard ceiling."""
        if not self.enabled or self.mode == "ro" or not self.root.exists():
            return {"pruned_age": 0, "pruned_size": 0, "kept": 0, "bytes": 0}
        now = time.time()
        max_age = PRUNE_MAX_AGE_DAYS * 86400
        entries = []  # (mtime, size, path)
        for p in self.root.rglob("*"):
            if not p.is_file() or p.name.endswith(".tmp"):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append([st.st_mtime, st.st_size, p])
        pruned_age = 0
        kept = []
        for e in entries:
            if now - e[0] > max_age:
                if _safe_unlink(e[2]):
                    pruned_age += 1
            else:
                kept.append(e)
        # Size cap, oldest-first (smallest mtime evicted first).
        cap = self.max_mb * 1024 * 1024
        total = sum(e[1] for e in kept)
        pruned_size = 0
        if total > cap:
            for e in sorted(kept, key=lambda x: x[0]):
                if total <= cap:
                    break
                if _safe_unlink(e[2]):
                    total -= e[1]
                    pruned_size += 1
        _prune_empty_dirs(self.root)
        return {"pruned_age": pruned_age, "pruned_size": pruned_size,
                "kept": len(kept) - pruned_size, "bytes": total}


def _env_max_mb() -> int:
    """AUSMT_CACHE_MAX_MB (env) size cap in MB, else CACHE_MAX_MB_DEFAULT. A non-integer/negative
    value falls back to the default rather than crashing the build on a typo'd env var."""
    raw = os.environ.get("AUSMT_CACHE_MAX_MB")
    if raw is None:
        return CACHE_MAX_MB_DEFAULT
    try:
        v = int(str(raw).strip())
        return v if v > 0 else CACHE_MAX_MB_DEFAULT
    except (ValueError, TypeError):
        return CACHE_MAX_MB_DEFAULT


def _safe_unlink(p: Path) -> bool:
    try:
        p.unlink()
        return True
    except OSError:
        return False


def _prune_empty_dirs(root: Path) -> None:
    """Remove the now-empty <k[:2]> shard directories a prune can leave behind (cosmetic; the shard
    dirs are re-created on demand by put_bytes)."""
    for d in sorted(root.iterdir() if root.exists() else [], reverse=True):
        if d.is_dir():
            try:
                next(d.iterdir())
            except StopIteration:
                shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
