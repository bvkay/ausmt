#!/usr/bin/env python3
"""Content-addressed build cache for per-station products.

A full portal build re-parses every EDI through mt_metadata and re-runs normalize()'s served-XML
round-trip for every served station, even when a one-line survey.yaml edit changed nothing about
those stations. This module is a content-addressed cache of the two expensive per-station products
so an incremental rebuild skips the parse and the round-trip for unchanged stations.

Design: maintainer/C18-BuildCacheDesign.md. The invariants this module upholds:

  * The cache may only ever change build SPEED, never output bytes. `scripts/verify.py` stays full,
    byte-re-hashing and cache-blind; a warm build is byte-identical to the build that populated its
    cache, and so is an INDEPENDENT full build of the same inputs (proven by test; the served XML's
    CreateTime is pinned to the date its source declares, so no served artifact carries a build
    clock).
  * The key is derived from the SOURCE EDI content sha + the engine SOURCE digest (a content
    hash of the product-producing code, see engine_source_digest) + library versions + the
    positional/schema contract + the whole survey.yaml digest. A byte-changed EDI, any edit to the
    digested code, a library upgrade, a contract change, or ANY survey.yaml edit all miss. The
    engine git commit is NOT a key component: an image built from a commit that changed only
    deploy scripts, docs or tests keys identically to its predecessor and stays warm.
  * A DEGENERATE salt (unknown engine commit, a dirty checkout where a git checkout exists, or an
    engine tree that yields no source digest) silently DISABLES the cache for that build - no
    reads, no writes. The commit and dirty-tree rules are identity gates, not key inputs: a build
    that cannot state which engine produced it, or that ran from a half-edited tree, never seeds a
    store. --raw builds are a POLICY exclusion with the same inert behaviour (--seed-meta feeds
    served citations but is not a key component).
  * Entries are SELF-VERIFYING: each file is `<sha256-hex-of-payload>\n<payload>`,
    written temp-then-atomic-rename. Every read re-hashes the payload; a mismatch (disk corruption,
    tampering) DELETES the entry, counts in the `corrupt` counter, tallies as a MISS, and the
    caller recomputes - a poisoned VALUE can never ship. This is the cache's own job: the
    content-addressed KEY derives from inputs, while verify.py's manifest check (whose shas are
    computed FROM the served bytes) cannot see a poisoned value that flowed through the build; it
    guards post-build tampering of the served tree only.

  * FILE entries (the two MTH5 tiers) keep the payload RAW so it can be hardlinked into the build
    tree, beside a self-verifying JSON sidecar `<key>.<kind>.ref` that carries the payload's sha256
    and the seam's meta. A read links the payload to a temporary name in the build tree, re-hashes
    THAT inode against the sidecar and only then renames it into place, so what was hashed is what
    is served. Neither the cache nor a build ever writes into an existing inode (every write is a
    new file renamed over the old name), so a payload shared by a cache entry and any number of
    served trees cannot change under either of them; unlinking one name never touches the others.

The cache is a passive store: it makes no policy decisions about WHAT is cacheable, only about
whether a given key is present and readable. The build seams decide what to compute-and-put.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Prune policy defaults - operator-tunable, single-sourced here. Adjudicated v1 policy:
# an mtime-age window + a size cap, oldest-first. The design's "20 builds" window is
# NOT implemented (the cache keeps no per-build ledger); age is the operator-meaningful bound.
CACHE_MAX_MB_DEFAULT = 8192          # AUSMT_CACHE_MAX_MB overrides (size cap, oldest-first eviction)
PRUNE_MAX_AGE_DAYS = 90              # drop entries untouched for this many days

CACHE_MODES = ("rw", "ro", "refresh")

# The per-kind counter buckets. parse and xml are the JSON/bytes entries; the MTH5 tiers are FILE
# entries (raw payload + sidecar). The corpus-total hits/misses/writes/corrupt stay the parse+xml
# tally, so their meaning does not move under the per-survey lines and the deploy alerting.
KINDS = ("parse", "xml", "station_h5", "survey_h5")
FILE_KINDS = ("station_h5", "survey_h5")
_KIND_FIELDS = ("hits", "misses", "writes", "corrupt", "link_fallbacks", "evicted")
_REF = "ref"   # sidecar suffix of a file entry: <key>.<kind>.ref

# Which bucket an entry file belongs to, by its name after the key. The prune reads this to count
# evictions per kind; a name the table does not know is still an entry and still counts to the cap.
_KIND_OF_EXT = {"json": "parse", "xml": "xml", "meta": "xml",
                **{k: k for k in FILE_KINDS}, **{f"{k}.{_REF}": k for k in FILE_KINDS}}
_ENTRY_NAME = re.compile(r"^([0-9a-f]{64})\.(.+)$")


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
    """Integrity gate: is the cache salt degenerate, so incremental must be DISABLED
    for this build (treated as full — no reads, no writes)?

    Degenerate iff EITHER:
      * the engine commit is unknown/None/the literal "unknown" (an unresolvable build identity), OR
      * a git checkout EXISTS at `checkout_dir` and is dirty (uncommitted changes).
    Neither is a key component (the key carries the engine SOURCE digest, which describes the
    working tree exactly). They are identity gates: a build that cannot name its engine commit in
    build.json, or that ran from a tree with uncommitted edits, must not seed a shared store.

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
    """sha256 over the positional-column contract + the product schema versions. A
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


# Product code the cached entries depend on: the three package roots under engine/, plus the
# sibling column contract. Bytecode, tool caches, dotfiles and any tests directory cannot change a
# served product, so they are not hashed; hashing them would cold the cache on a pytest run.
SOURCE_DIGEST_ROOTS = ("extract", "ausmt_science", "schema")
_SOURCE_DIGEST_SKIP_DIRS = frozenset({"__pycache__", "tests", ".pytest_cache", ".ruff_cache", ".mypy_cache"})


def engine_source_digest(engine_root) -> str:
    """The coarse salt: sha256 over (relative path, content sha256) of every regular file under the
    SOURCE_DIGEST_ROOTS of `engine_root`, plus contract/columns.json beside it. Sorted by path, so
    walk order and mtimes never enter it, and a rename moves it. Returns "" when no digested root
    exists or a file cannot be read: such a tree cannot describe the code that produced an entry,
    and BuildCache treats "" as degenerate."""
    root = Path(engine_root)
    files: list[tuple[str, Path]] = []
    for sub in SOURCE_DIGEST_ROOTS:
        base = root / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix == ".pyc" or p.name.startswith("."):
                continue
            rel = p.relative_to(root)
            if any(part in _SOURCE_DIGEST_SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                continue
            files.append((rel.as_posix(), p))
    if not files:
        return ""
    contract = root.parent / "contract" / "columns.json"
    if contract.is_file():
        files.append(("../contract/columns.json", contract))
    h = hashlib.sha256()
    try:
        for rel, p in sorted(files):
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode("ascii"))
            h.update(b"\0")
    except OSError:
        return ""
    return h.hexdigest()


# NOTE: the per-survey yaml digest is not derived here. It is
# computed in build_portal.discover_work from the SAME bytes the survey metadata is parsed from,
# one read feeds both, so a mid-build survey.yaml edit can never key products under a digest their
# metadata does not match. The path-taking helper that stood here was deliberately DELETED, not
# deprecated: any reappearance of a read-the-yaml-again digest call site reopens that window.


class BuildCache:
    """A content-addressed store of per-station products under `<root>/<k[:2]>/<k>.<ext>`.

    One instance per build. Holds the shared salt (engine source digest + library versions +
    contract + per-survey survey.yaml digest) and derives a per-station key from it plus the source
    EDI sha. `engine_commit` and `checkout_dir` feed the identity gate only.
    Tracks hit/miss/write counters (deterministic, asserted by tests — never wall-clock). When the
    salt is degenerate the instance is INERT: enabled is False, get() always misses and put() is a
    no-op, and the counters prove no reads or writes happened.
    """

    def __init__(self, root: Path, *, engine_commit, lib_versions: dict,
                 contract_digest: str, mode: str = "rw", checkout_dir: Path | None = None,
                 max_mb: int | None = None, disabled_reason: str = "",
                 source_digest: str | None = None):
        self.root = Path(root)
        self.mode = mode if mode in CACHE_MODES else "rw"
        self.engine_commit = engine_commit
        # None derives the digest of the engine tree this module lives in (the value build_portal
        # passes for the same tree); an explicit "" is a tree with nothing to digest.
        if source_digest is None:
            source_digest = engine_source_digest(Path(__file__).resolve().parent.parent)
        self.source_digest = str(source_digest)
        self.lib_versions = dict(lib_versions or {})
        self.contract_digest = contract_digest or ""
        self.max_mb = int(max_mb) if max_mb is not None else _env_max_mb()
        # Counters: deterministic build-report evidence, NOT wall-clock timing.
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.corrupt = 0   # Entries whose embedded payload checksum failed on read (deleted+recomputed)
        # Forensics: environment-induced I/O failures, distinct from content-addressed misses.
        # write_errors = puts dropped after the rename retries were exhausted (AV/indexer lock class);
        # read_errors  = present-but-unreadable entries (counted as misses for the arithmetic,
        # but attributable — a lock-induced spurious miss is not a cold miss).
        self.write_errors = 0
        self.read_errors = 0
        self.kinds = {k: dict.fromkeys(_KIND_FIELDS, 0) for k in KINDS}
        # Entries touched or written at or after this instant were used by THIS build; an eviction
        # of one of them means the next build misses it (the cap is too small for the corpus).
        self.started = time.time()
        self.last_prune: dict | None = None
        # `disabled_reason` is a POLICY exclusion (e.g. --raw builds, whose seed-meta
        # citations feed served XML but are not a key component) — behaviourally identical to a
        # degenerate salt: the cache is inert, no reads, no writes.
        if disabled_reason:
            self.degenerate, self.degenerate_reason = True, disabled_reason
        else:
            self.degenerate, self.degenerate_reason = is_salt_degenerate(engine_commit, checkout_dir)
        if not self.degenerate and not self.source_digest:
            self.degenerate = True
            self.degenerate_reason = ("engine source digest unavailable (no digestable engine tree) "
                                      "- the salt cannot describe the code producing the entries")
        # The stable, per-survey salt component is injected via key(); the fixed part is precomputed.
        self._fixed_salt = "\x00".join([
            # Cache-format version tag. v2 = self-verifying entries (digest-line + payload);
            # v3 = the served-XML meta blob carries `survey_digest` (the digest
            # the entry was KEYED under), consumed by the digest-stamp sidecar + the verify.py
            # consistency gate; v4 = the parse product changed SHAPE - tf.json rows grew 10 -> 18
            # (rho/phase error columns + full complex tipper) and the placeholder-tipper mask now
            # withholds filler tippers, so a pre-v4 cached parse would replay 10-wide/unmasked rows.
            # Bumping the tag re-keys EVERY blob, so pre-v4 entries never resolve - a clean MISS,
            # counted as a miss, never a replay of a stale-shape parse. One full re-derive on the first
            # build after this lands; then warm again. (The contract_digest below ALSO shifts on the
            # column append; the tag bump is the explicit, self-documenting belt-and-suspenders.)
            # Old-format entries age out via the prune.
            # v5 = the served-XML CONTENT changed corpus-wide: the EMTF-XML Copyright block now
            # carries the survey's real licence-derived release_status + conditions_of_use instead of
            # mt_metadata's default "Unrestricted Release"/"may be copied freely" boilerplate (a truth
            # fix in ausmt_science.ingest.normalize.condition_tf). That formatter change is not captured
            # by the source-EDI sha, the survey.yaml digest, or the contract digest, so a warm pre-v5
            # cache would REPLAY the boilerplate XML for an unchanged EDI on the same engine commit.
            # Bumping the tag forces one clean full re-derive so every served XML is the truthful form.
            # v6 (station promotion) = the parse product changed SHAPE again: the per-EDI parse now
            # carries the presence-rule notes and the >INFO dialect run facts that runs[] is emitted
            # from, so a pre-v6 entry would replay a parse with neither and serve a station.json
            # with no runs at all. Same clean-MISS discipline as v4/v5: one full re-derive on the
            # first build after this lands, then warm again.
            # v7 = the coarse salt is the engine SOURCE digest instead of the git commit, so a new
            # image whose product code is unchanged keys identically to its predecessor. Pre-v7
            # entries are keyed under a commit and can never resolve: a clean MISS, then warm.
            "ausmt-c47-cache-v7",
            self.source_digest,                                      # coarse engine-source salt
            json.dumps(self.lib_versions, sort_keys=True),           # mt_metadata (+ mth5) versions
            self.contract_digest,                                    # columns + schema digest
        ])
        # Forensics: a short fingerprint of the FULL fixed salt (version tag + engine source digest +
        # lib versions + contract digest). Two builds that should key identically expose identical
        # fingerprints; a mid-process salt flip (the flake class: moving HEAD, transient
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
        EVERY salt field: source EDI sha + engine source digest + lib versions + contract + this
        survey's whole-yaml digest."""
        material = "\x00".join([self._fixed_salt, str(edi_sha), str(survey_digest or ""), str(kind)])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def key_parts(self, kind: str, parts) -> str:
        """The key of an entry whose material the SEAM enumerates: the fixed salt, the kind, then
        every part in the given order. The seam owns completeness (which inputs reach the product);
        this only guarantees that the salt is always bound and that two kinds never share a key."""
        material = "\x00".join([self._fixed_salt, "parts", str(kind), *(str(x) for x in parts)])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _path(self, key: str, ext: str) -> Path:
        return self.root / key[:2] / f"{key}.{ext}"

    def _tally(self, kind, field: str, n: int = 1) -> None:
        if kind in self.kinds:
            self.kinds[kind][field] += n

    def _read_entry(self, p: Path):
        """(status, payload) for one self-verifying entry file: "ok", "absent" (a cold miss),
        "unreadable" (present but not readable, counted in read_errors) or "corrupt" (malformed or
        digest mismatch, already deleted). Touches no hit/miss counter: the callers tally."""
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            return "absent", None
        except OSError:
            self.read_errors += 1
            return "unreadable", None
        head, sep, payload = raw.partition(b"\n")
        if not sep or head != hashlib.sha256(payload).hexdigest().encode("ascii"):
            _safe_unlink(p)
            return "corrupt", None
        return "ok", payload

    def get_bytes(self, key: str, ext: str, kind: str | None = None) -> bytes | None:
        """Read a cached blob's PAYLOAD, or None on miss / disabled / refresh-mode / integrity
        failure. Increments hits on a verified read, misses otherwise. `refresh` mode forces a miss
        (ignore hits and rewrite): the forced-full-rebuild escape hatch that still repopulates.
        `kind` names the per-kind bucket the read is tallied in as well as the corpus totals.

        Integrity: the entry is `<sha256-hex>\\n<payload>`; the payload is RE-HASHED on every
        read. A malformed entry or a digest mismatch (bit rot, tampering) is deleted, counted in
        `corrupt`, tallied as a MISS, and None returned so the caller recomputes — fail-safe.
        A PRESENT-but-unreadable entry (Windows AV/indexer lock, permissions) is tallied as a miss
        too, but counted in read_errors so a lock-induced spurious miss is attributable from the
        build report instead of masquerading as content drift."""
        if not self.enabled or self.mode == "refresh":
            self.misses += 1
            self._tally(kind, "misses")
            return None
        status, payload = self._read_entry(self._path(key, ext))
        if status != "ok":
            if status == "corrupt":
                self.corrupt += 1
                self._tally(kind, "corrupt")
            self.misses += 1
            self._tally(kind, "misses")
            return None
        self.hits += 1
        self._tally(kind, "hits")
        self._touch(key, ext)   # mark recently-used for the age prune policy
        return payload

    def get_json(self, key: str, ext: str = "json", kind: str | None = None):
        """Read a cached JSON blob (the parse-rows / xml-meta product), or None on miss. Shares the
        get_bytes counter + integrity semantics. A checksum-VALID payload that fails to decode is a
        put-side defect (put_json always writes valid JSON), handled with the same fail-safe
        discipline: revoke the counted hit, count corrupt + miss, drop the entry, recompute."""
        raw = self.get_bytes(key, ext, kind)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.hits -= 1
            self.misses += 1
            self.corrupt += 1
            self._tally(kind, "hits", -1)
            self._tally(kind, "misses")
            self._tally(kind, "corrupt")
            _safe_unlink(self._path(key, ext))
            return None

    def revoke_hit(self, kind: str | None = None) -> None:
        """Correct the tally when a PAIRED read turns out unusable after this cache already counted
        a hit - the torn-pair case at the served-XML seam: the xml blob hit but its meta sibling
        missed, so the pair produced nothing and the station recomputes. The sibling's own get
        already tallied its miss; this only revokes the phantom hit (mirrors
        get_json's internal corrupt-payload discipline)."""
        self.hits -= 1
        self._tally(kind, "hits", -1)

    def _replace_into(self, tmp: Path, p: Path) -> bool:
        """os.replace with retries: on Windows an AV/on-access scanner briefly holding the fresh
        tmp (or the destination) raises a transient PermissionError, and a silently dropped entry
        is a spurious miss on the next build. Three attempts with a short backoff clear a scanner
        hold; a still-failing write counts in write_errors and never breaks the build."""
        last_err = None
        for attempt in range(3):
            try:
                os.replace(tmp, p)          # atomic rename (POSIX + Windows)
                return True
            except OSError as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
        self.write_errors += 1
        print(f"  [cache] WARN could not write {p.name}: {type(last_err).__name__}: {last_err}",
              file=sys.stderr)
        _safe_unlink(tmp)
        return False

    def _write_entry(self, p: Path, data: bytes) -> bool:
        """Write one self-verifying entry file (`<sha256-hex-of-payload>\\n<payload>`),
        temp-then-atomic-rename. os.replace is atomic within a filesystem on both POSIX and
        Windows, so a concurrent or interrupted build never observes a half-written entry."""
        tmp = None   # assigned inside the try: a mkdir failure must not leave the cleanup referencing it
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / f".{p.name}.{os.getpid()}.{time.time_ns()}.tmp"
            tmp.write_bytes(hashlib.sha256(data).hexdigest().encode("ascii") + b"\n" + data)
        except OSError as e:  # noqa: BLE001  (a cache write must never break the build)
            self.write_errors += 1
            print(f"  [cache] WARN could not write {p.name}: {type(e).__name__}: {e}", file=sys.stderr)
            if tmp is not None:
                _safe_unlink(tmp)
            return False
        return self._replace_into(tmp, p)

    def put_bytes(self, key: str, ext: str, data: bytes, kind: str | None = None) -> None:
        """Write a blob to the cache as a SELF-VERIFYING entry. No-op when disabled or in
        read-only (`ro`) mode."""
        if not self.enabled or self.mode == "ro":
            return
        if self._write_entry(self._path(key, ext), data):
            self.writes += 1
            self._tally(kind, "writes")

    def put_json(self, key: str, obj, ext: str = "json", kind: str | None = None) -> None:
        """Write a JSON-serializable object as a cache blob (the parse-rows product)."""
        self.put_bytes(key, ext, json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                       kind)

    # ---- file entries: a raw payload that can be hardlinked, plus its self-verifying sidecar -----

    def _link_or_copy(self, src: Path, dst: Path, kind: str) -> None:
        """Place `src`'s inode at `dst` by hardlink; a filesystem that refuses (cross-device EXDEV,
        no hardlink support, a link-count limit) gets a byte copy instead, counted in
        link_fallbacks. A missing `src` raises FileNotFoundError to the caller."""
        try:
            os.link(src, dst)
        except FileNotFoundError:
            raise
        except OSError:
            shutil.copyfile(src, dst)
            self._tally(kind, "link_fallbacks")

    def link_file(self, key: str, kind: str, dest: Path):
        """Place a file entry's payload at `dest` and return the meta its seam stored, or None on a
        miss. The payload is linked to a temporary name beside `dest` and THAT inode is re-hashed
        against the sidecar before it is renamed into place: what was verified is what is served.
        A malformed sidecar, a sidecar whose payload is gone, or a digest mismatch deletes the
        whole entry, counts corrupt and misses, exactly like a corrupt JSON entry. Tallies only
        the per-kind bucket; `refresh` mode and an inert cache always miss."""
        if not self.enabled or self.mode == "refresh":
            self._tally(kind, "misses")
            return None
        payload, ref = self._path(key, kind), self._path(key, f"{kind}.{_REF}")
        status, raw = self._read_entry(ref)
        side = None
        if status == "ok":
            try:
                side = json.loads(raw.decode("utf-8"))
                if not (isinstance(side, dict) and isinstance(side.get("sha256"), str)):
                    side = None
            except (ValueError, UnicodeDecodeError):
                side = None
            if side is None:
                status = "corrupt"
        if status != "ok":
            if status == "corrupt":
                self._drop_file_entry(key, kind)
            self._tally(kind, "misses")
            return None
        dest = Path(dest)
        tmp = dest.parent / f".{dest.name}.{os.getpid()}.{time.time_ns()}.tmp"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._link_or_copy(payload, tmp, kind)
        except FileNotFoundError:
            self._drop_file_entry(key, kind)
            self._tally(kind, "misses")
            return None
        except OSError:
            self.read_errors += 1
            _safe_unlink(tmp)
            self._tally(kind, "misses")
            return None
        if _file_sha256(tmp) != side["sha256"]:
            _safe_unlink(tmp)
            self._drop_file_entry(key, kind)
            self._tally(kind, "misses")
            return None
        try:
            os.replace(tmp, dest)
        except OSError:
            self.read_errors += 1
            _safe_unlink(tmp)
            self._tally(kind, "misses")
            return None
        self._tally(kind, "hits")
        # Only the sidecar is touched: the payload inode is also a served file, whose mtime is the
        # instant it was written and must not move with cache bookkeeping.
        self._touch(key, f"{kind}.{_REF}")
        return side.get("meta")

    def _drop_file_entry(self, key: str, kind: str) -> None:
        self._tally(kind, "corrupt")
        _safe_unlink(self._path(key, kind))
        _safe_unlink(self._path(key, f"{kind}.{_REF}"))

    def reject_file(self, key: str, kind: str) -> None:
        """Revoke a link_file hit whose meta the seam cannot use: the entry is dropped and the read
        re-tallied as corrupt + miss, so the seam recomputes. The seam unlinks what it placed."""
        self._tally(kind, "hits", -1)
        self._tally(kind, "misses")
        self._drop_file_entry(key, kind)

    def put_file(self, key: str, kind: str, src: Path, meta=None) -> None:
        """Store the file at `src` as a file entry. The payload is linked (copy on refusal) to a
        temporary name, hashed there, renamed into place, and only THEN is the sidecar written, so
        a reader never finds a sidecar naming a payload that is not yet in place. A concurrent
        writer of the same key can interleave the two renames; the reader then sees a digest
        mismatch, drops the entry and recomputes, never serving an unverified file. No-op when
        disabled or in `ro` mode."""
        if not self.enabled or self.mode == "ro":
            return
        payload = self._path(key, kind)
        tmp = payload.parent / f".{payload.name}.{os.getpid()}.{time.time_ns()}.tmp"
        try:
            payload.parent.mkdir(parents=True, exist_ok=True)
            self._link_or_copy(Path(src), tmp, kind)
            digest, size = _file_sha256(tmp), tmp.stat().st_size
        except OSError as e:  # noqa: BLE001  (a cache write must never break the build)
            self.write_errors += 1
            print(f"  [cache] WARN could not write {payload.name}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            _safe_unlink(tmp)
            return
        if not self._replace_into(tmp, payload):
            return
        side = json.dumps({"sha256": digest, "size": size, "meta": meta},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
        if self._write_entry(self._path(key, f"{kind}.{_REF}"), side):
            self._tally(kind, "writes")
        else:
            _safe_unlink(payload)

    def _touch(self, key: str, ext: str) -> None:
        """Bump the entry's mtime so the age/build prune keeps recently-USED entries, not just
        recently-written ones (a hit on an old-but-live station must not let it be pruned)."""
        try:
            os.utime(self._path(key, ext), None)
        except OSError:
            pass

    def counters(self) -> dict:
        """The deterministic hit/miss/write/corrupt tally for the build log + report.
        hits/misses/writes/corrupt are the parse+xml totals; `kinds` breaks every kind out,
        the MTH5 file entries included. salt_fp fingerprints the fixed salt so cross-build
        key-space drift is observable. `prune` is the end-of-build prune summary, or None before
        it has run."""
        return {"enabled": self.enabled, "mode": self.mode, "hits": self.hits,
                "misses": self.misses, "writes": self.writes, "corrupt": self.corrupt,
                "write_errors": self.write_errors, "read_errors": self.read_errors,
                "degenerate": self.degenerate, "reason": self.degenerate_reason,
                "salt_fp": self.salt_fp, "max_mb": self.max_mb,
                "kinds": {k: dict(v) for k, v in self.kinds.items()},
                "prune": self.last_prune}

    # ---- lifecycle: prune at the end of a successful build ---------------------------------------

    def _entries(self) -> dict:
        """{key: [mtime, size, [paths], kind]} over the cache's own entries: files named
        `<64-hex key>.<ext>` inside a `<key[:2]>` shard directory. Anything else under the root
        (temporary files, a file an operator keeps beside the shards) is not an entry and is never
        counted, aged or evicted. An entry is every file of one key, so a file entry's payload and
        sidecar live and die together."""
        groups: dict = {}
        if not self.root.is_dir():
            return groups
        for shard in self.root.iterdir():
            if not shard.is_dir() or len(shard.name) != 2:
                continue
            for p in shard.iterdir():
                m = _ENTRY_NAME.match(p.name)
                if not m or not m.group(1).startswith(shard.name) or not p.is_file():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                g = groups.setdefault(m.group(1), [0.0, 0, [], None])
                g[0] = max(g[0], st.st_mtime)
                g[1] += st.st_size
                g[2].append(p)
                g[3] = g[3] or _KIND_OF_EXT.get(m.group(2))
        return groups

    def prune(self) -> dict:
        """Drop entries untouched for PRUNE_MAX_AGE_DAYS, then enforce the size cap oldest-first.
        Runs at the end of a successful build. A prune failure must never fail the build; returns a
        small summary. Adjudicated v1 policy: mtime-age + size cap ONLY - the
        design's original "20 builds" window is not implemented (the cache keeps no per-build
        ledger); age is the operator-meaningful bound, the size cap the hard ceiling.

        The size is the sum of entry file sizes. A payload hardlinked into retained builds is
        counted in full although the disk holds it once, so the cap bounds what the cache could
        cost if every build that shares it were pruned. Evictions are tallied per kind;
        `evicted_live` counts the evicted entries this build used, which the next build misses."""
        empty = {"pruned_age": 0, "pruned_size": 0, "evicted_live": 0, "kept": 0, "bytes": 0}
        if not self.enabled or self.mode == "ro" or not self.root.exists():
            return empty
        now = time.time()
        max_age = PRUNE_MAX_AGE_DAYS * 86400
        pruned_age = 0
        kept = []
        for key, (mtime, size, paths, kind) in self._entries().items():
            if now - mtime > max_age:
                for p in paths:
                    _safe_unlink(p)
                pruned_age += 1
            else:
                kept.append((mtime, size, paths, kind))
        cap = self.max_mb * 1024 * 1024
        total = sum(e[1] for e in kept)
        pruned_size = evicted_live = 0
        if total > cap:
            for mtime, size, paths, kind in sorted(kept, key=lambda x: x[0]):
                if total <= cap:
                    break
                for p in paths:
                    _safe_unlink(p)
                total -= size
                pruned_size += 1
                self._tally(kind, "evicted")
                if mtime >= self.started:
                    evicted_live += 1
        _prune_empty_dirs(self.root)
        self.last_prune = {"pruned_age": pruned_age, "pruned_size": pruned_size,
                           "evicted_live": evicted_live, "kept": len(kept) - pruned_size,
                           "bytes": total}
        return dict(self.last_prune)


def _file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
