"""Schema-version stamp + migration runner + forward-compat guard (audit Angle 1 minor / Angle 4 §3).

gateway/db.py created its schema with no version stamp, so the first future schema change would have
had no migration path. db.Database now stamps PRAGMA user_version and refuses a DB written by a newer
build.

NON-VACUOUS failure criteria (each fails against the pre-stamp db.py):
  * a fresh DB opens stamped at SCHEMA_VERSION (pre-fix: user_version stayed 0);
  * a legacy DB carrying the current tables at user_version 0 upgrades to SCHEMA_VERSION cleanly and
    its existing rows survive;
  * a DB stamped 99 (newer than this build) is REFUSED with SchemaTooNew (pre-fix: opened blind).
"""
from __future__ import annotations

import sqlite3

import pytest

from gateway import db


def _user_version(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def test_fresh_db_is_stamped_at_schema_version(tmp_path):
    path = tmp_path / "gateway.sqlite"
    database = db.Database(path)
    database.close()
    assert _user_version(path) == db.SCHEMA_VERSION


def test_legacy_unstamped_db_upgrades_cleanly(tmp_path):
    """A DB that already carries the current tables but was never stamped (user_version 0, the
    pre-fix on-disk state) must upgrade to SCHEMA_VERSION without losing data."""
    path = tmp_path / "gateway.sqlite"
    # Build the real schema, seed a row, then reset the stamp to 0 to simulate a pre-fix DB on disk.
    seeded = db.Database(path)
    sid = db.new_id()
    seeded.insert_submission(
        submission_id=sid, zip_sha256="a" * 64, zip_bytes=1,
        submitter_name="Tester", submitter_email="t@example.org", submitter_orcid=None,
        token_hash="b" * 64,
    )
    seeded.close()
    raw = sqlite3.connect(str(path))
    raw.execute("PRAGMA user_version=0")
    raw.commit()
    raw.close()
    assert _user_version(path) == 0

    reopened = db.Database(path)             # must run the migration path, not choke
    try:
        assert _user_version(path) == db.SCHEMA_VERSION
        assert reopened.get(sid) is not None, "existing rows must survive the upgrade"
    finally:
        reopened.close()


def test_db_from_newer_build_is_refused(tmp_path):
    path = tmp_path / "gateway.sqlite"
    db.Database(path).close()
    raw = sqlite3.connect(str(path))
    raw.execute("PRAGMA user_version=99")     # written by a hypothetical future build
    raw.commit()
    raw.close()

    with pytest.raises(db.SchemaTooNew):
        db.Database(path)


def _table_columns(path, table: str) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def test_fresh_db_lands_at_v2_with_uploader_keys(tmp_path):
    """A fresh DB is stamped at the current SCHEMA_VERSION (>= 2) and carries the uploader_keys table
    (the feat/uploader-key-management migration), INCLUDING the v3 `note` column (C43 D7). Fails if the
    migration never ran on a fresh DB, or a schema change dropped/renamed a column."""
    path = tmp_path / "gateway.sqlite"
    db.Database(path).close()
    assert db.SCHEMA_VERSION >= 3
    assert _user_version(path) == db.SCHEMA_VERSION
    cols = _table_columns(path, "uploader_keys")
    assert cols == {"id", "name", "email", "key_sha256", "created_utc", "created_by",
                    "revoked_utc", "revoked_by", "last_used_utc", "note"}


def test_v2_db_with_data_upgrades_to_v3_adding_note(tmp_path):
    """A v2 DB (uploader_keys WITHOUT the note column, stamped 2) with an existing key row upgrades to
    v3 cleanly: the migration ADDS the `note` column (defaulting existing rows to NULL) and the
    existing row survives with its other fields intact. Fails if the v3 migration drops data, does not
    add `note`, or the ALTER is not additive. Simulates the C43 D7 migration on an already-deployed v2
    DB. NON-VACUOUS: the pre-fix state genuinely lacks the column, so a no-op migration would leave
    user_version at 2 and the note assertion would KeyError/mismatch."""
    path = tmp_path / "gateway.sqlite"
    seeded = db.Database(path)
    kid = seeded.create_uploader_key(
        name="field-team-1", email="t@example.org", key_sha256="c" * 64, created_by="curator-a")
    seeded.close()
    # Force the on-disk state back to a real v2: drop the v3 `note` column (SQLite lacks DROP COLUMN on
    # old versions, so rebuild the v2-shape table) and reset the stamp so the v3 migration has real work.
    raw = sqlite3.connect(str(path))
    raw.executescript(
        """
        CREATE TABLE uploader_keys_v2 (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, email TEXT,
            key_sha256 TEXT NOT NULL UNIQUE, created_utc TEXT NOT NULL, created_by TEXT NOT NULL,
            revoked_utc TEXT, revoked_by TEXT, last_used_utc TEXT);
        INSERT INTO uploader_keys_v2 (id, name, email, key_sha256, created_utc, created_by,
            revoked_utc, revoked_by, last_used_utc)
          SELECT id, name, email, key_sha256, created_utc, created_by,
            revoked_utc, revoked_by, last_used_utc FROM uploader_keys;
        DROP TABLE uploader_keys;
        ALTER TABLE uploader_keys_v2 RENAME TO uploader_keys;
        PRAGMA user_version=2;
        """
    )
    raw.commit()
    raw.close()
    assert _user_version(path) == 2
    assert "note" not in _table_columns(path, "uploader_keys")

    reopened = db.Database(path)
    try:
        assert _user_version(path) == db.SCHEMA_VERSION
        assert "note" in _table_columns(path, "uploader_keys")
        row = [k for k in reopened.list_uploader_keys() if k.id == kid][0]
        assert row.note is None, "an existing row's note defaults to NULL after the additive ALTER"
        assert row.name == "field-team-1" and row.created_by == "curator-a", "other fields survive"
    finally:
        reopened.close()


def test_v1_db_with_data_upgrades_to_v2(tmp_path):
    """A v1 DB (current tables, stamped 1) with an existing submission row upgrades to v2 cleanly:
    the migration adds uploader_keys and the existing row survives. Fails if the migration drops data
    or does not create uploader_keys. Simulates the FIRST real migration on an already-deployed DB."""
    path = tmp_path / "gateway.sqlite"
    seeded = db.Database(path)
    sid = db.new_id()
    seeded.insert_submission(
        submission_id=sid, zip_sha256="a" * 64, zip_bytes=1,
        submitter_name="Tester", submitter_email="t@example.org", submitter_orcid=None,
        token_hash="b" * 64,
    )
    seeded.close()
    # Force the on-disk stamp back to 1 (a real v1 deployment) and drop uploader_keys so the migration
    # has genuine work to do — not a no-op that would pass vacuously.
    raw = sqlite3.connect(str(path))
    raw.execute("DROP TABLE IF EXISTS uploader_keys")
    raw.execute("PRAGMA user_version=1")
    raw.commit()
    raw.close()
    assert _user_version(path) == 1

    reopened = db.Database(path)
    try:
        assert _user_version(path) == db.SCHEMA_VERSION
        assert reopened.get(sid) is not None, "existing rows must survive the v1->v2 upgrade"
        assert "uploader_keys" in {
            r[0] for r in reopened._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        reopened.close()
