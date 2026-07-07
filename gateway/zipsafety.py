"""Zip central-directory safety checks (design §4.3). This is the DEEPEST the gateway ever looks
into submitted bytes: names, sizes, and external attributes from the central directory only — never
member contents (house rule: the gateway never parses EDI/YAML). The same rules are re-applied by
the runner during extraction (design §5, belt-and-braces), so this module is imported by both the
gateway and the runner and must stay content-blind and dependency-free (stdlib zipfile only).

Every guard returns a distinct reason string so a rejected upload tells the submitter exactly which
rule fired and the test contract can assert on the specific reason (design §8).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass

# Design §4.3 numeric limits. Kept as named constants because the test contract asserts the exact
# boundary behaviour (a 2001-member zip rejects, a ratio-101 member rejects).
MAX_MEMBERS = 2000
MAX_TOTAL_UNCOMPRESSED_FACTOR = 4      # declared uncompressed total <= 4 x max-upload
RATIO_LIMIT = 100                      # per-member compression ratio cap (zip-bomb)
RATIO_CHECK_MIN_COMPRESSED = 1024 * 1024  # only ratio-check members > 1 MiB compressed

# Nested-archive extensions rejected outright (design §4.3): a submission is ONE survey package,
# never an archive-of-archives. Checked on the lowercased basename suffix.
_NESTED_ARCHIVE_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")

# Allowed member-name character class (design §4.3). Space is allowed (survey packages have
# human-named files); backslash is NOT (a Windows-style separator smuggling a traversal). The check
# is on the raw zip name, which always uses forward slashes per the zip spec.
_ALLOWED_NAME_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._ /-"
)

# External-attr high bits carry the unix mode in the top 16 bits; S_IFLNK (0o120000) marks a
# symlink, other non-regular types (block/char/fifo/socket) are equally rejected. A zip member
# should be a regular file or a directory and nothing else.
_S_IFMT = 0o170000
_S_IFREG = 0o100000
_S_IFDIR = 0o040000


@dataclass(frozen=True)
class ZipRejection(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


def _external_unix_mode(info: zipfile.ZipInfo) -> int:
    """Unix file-type bits from the external attributes, or 0 if the archive carries none (e.g. a
    zip written by a DOS/Windows tool). 0 means 'no type info' -> treated as a regular file, since
    a missing mode cannot itself be a symlink."""
    return (info.external_attr >> 16) & _S_IFMT


def check_member(info: zipfile.ZipInfo) -> None:
    """Raise ZipRejection if a single member violates any §4.3 name/type/ratio rule. Directory
    entries (trailing slash) are allowed structurally but still name-checked."""
    name = info.filename

    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ZipRejection(reason=f"absolute path in member: {name!r}")
    if "\\" in name:
        raise ZipRejection(reason=f"backslash in member name: {name!r}")
    # `..` as a whole path segment only — a filename like `a..b.edi` is legitimate.
    if ".." in name.split("/"):
        raise ZipRejection(reason=f"parent-directory segment in member: {name!r}")
    if any(c not in _ALLOWED_NAME_CHARS for c in name):
        raise ZipRejection(reason=f"disallowed character in member name: {name!r}")

    lower = name.rstrip("/").lower()
    if lower.endswith(_NESTED_ARCHIVE_SUFFIXES):
        raise ZipRejection(reason=f"nested archive not allowed: {name!r}")

    mode = _external_unix_mode(info)
    if mode not in (0, _S_IFREG, _S_IFDIR):
        raise ZipRejection(reason=f"non-regular member (symlink/special) not allowed: {name!r}")

    if info.compress_size > RATIO_CHECK_MIN_COMPRESSED and info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > RATIO_LIMIT:
            raise ZipRejection(
                reason=f"compression ratio {ratio:.0f}:1 exceeds {RATIO_LIMIT}:1 (zip bomb): {name!r}"
            )


def inspect(zip_path, max_upload_bytes: int) -> list[str]:
    """Full central-directory inspection of a zip at `zip_path`. Returns the list of member names
    (used by the caller for the second clamd sweep bound). Raises ZipRejection on the first rule
    that fires. Never extracts — reads the central directory only.

    Package-shape rules (design §4.3): exactly one top-level directory, at most one survey.yaml at
    depth <= 2, at least one .edi member.
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipRejection(reason="not a valid zip archive") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ZipRejection(reason=f"member count {len(infos)} exceeds {MAX_MEMBERS}")

        total_uncompressed = 0
        top_level_dirs: set[str] = set()
        survey_yaml_count = 0
        edi_count = 0
        seen_names: set[str] = set()

        for info in infos:
            check_member(info)
            total_uncompressed += info.file_size

            name = info.filename
            # Duplicate member names (review #13): a zip may legally carry two entries with the same
            # name, and extraction is last-wins — so the file the validator/engine reads can differ
            # from what a reviewer saw in the central-directory listing. Reject outright: one survey
            # package has no legitimate reason to name a file twice.
            if name in seen_names:
                raise ZipRejection(reason=f"duplicate member name: {name!r}")
            seen_names.add(name)

            parts = [p for p in name.split("/") if p]
            if parts:
                top_level_dirs.add(parts[0])

            # depth of the file component: number of directory segments above it. survey.yaml at the
            # package root (<top>/survey.yaml) is depth 2; a nested one deeper is not the manifest.
            if not name.endswith("/"):
                lower_base = parts[-1].lower() if parts else ""
                if lower_base == "survey.yaml" and len(parts) <= 2:
                    survey_yaml_count += 1
                if lower_base.endswith(".edi"):
                    edi_count += 1

        limit = MAX_TOTAL_UNCOMPRESSED_FACTOR * max_upload_bytes
        if total_uncompressed > limit:
            raise ZipRejection(
                reason=f"declared uncompressed total {total_uncompressed} exceeds {limit}"
            )
        if len(top_level_dirs) > 1:
            raise ZipRejection(reason=f"more than one top-level directory: {sorted(top_level_dirs)}")
        if survey_yaml_count > 1:
            raise ZipRejection(reason=f"more than one survey.yaml at depth <= 2 ({survey_yaml_count})")
        if edi_count == 0:
            raise ZipRejection(reason="no .edi members in package")

        return [i.filename for i in infos]
