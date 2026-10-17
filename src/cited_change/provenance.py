"""SQLite provenance archive. Snapshot identity is raw XML SHA/date/source URL."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .validation import validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    source_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    UNIQUE(sha256, source_date, source_url)
);
CREATE TABLE IF NOT EXISTS section_texts (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL CHECK(length(text_sha256) = 64),
    PRIMARY KEY(snapshot_id, section)
);
CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    section TEXT NOT NULL,
    before_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    after_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    generated_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        connection.close()
        raise ValueError(f"unsupported provenance schema version: {version}")
    connection.executescript(SCHEMA)
    connection.execute("PRAGMA user_version = 1")
    return connection


def record_comparison(connection: sqlite3.Connection, report: dict) -> None:
    errors = validate(report)
    if errors:
        raise ValueError("invalid comparison: " + "; ".join(errors))
    snapshot_ids = []
    with connection:
        for side in ("before", "after"):
            source = report[side]
            identity = (source["snapshot_sha256"], source["date"], source["url"])
            connection.execute("INSERT OR IGNORE INTO snapshots(sha256, source_date, source_url) VALUES (?, ?, ?)", identity)
            identifier = connection.execute("SELECT id FROM snapshots WHERE sha256=? AND source_date=? AND source_url=?", identity).fetchone()[0]
            snapshot_ids.append(identifier)
            existing = connection.execute("SELECT text FROM section_texts WHERE snapshot_id=? AND section=?", (identifier, report["section"])).fetchone()
            if existing and existing[0] != source["text"]:
                raise ValueError("conflicting section text for identical snapshot provenance")
            connection.execute("INSERT OR IGNORE INTO section_texts VALUES (?, ?, ?, ?)",
                               (identifier, report["section"], source["text"],
                                hashlib.sha256(source["text"].encode("utf-8")).hexdigest()))
        serialized = json.dumps(report, ensure_ascii=False, allow_nan=False)
        # Append-only comparison identity; never silently overwrite prior evidence.
        existing = connection.execute("SELECT report_json FROM comparisons WHERE id=?", (report["id"],)).fetchone()
        if existing:
            if json.loads(existing[0]) != report:
                raise ValueError("comparison id already exists with different content")
            return
        connection.execute("INSERT INTO comparisons VALUES (?, ?, ?, ?, ?, ?)",
                           (report["id"], report["section"], *snapshot_ids,
                            report["analysis"]["generated_at"], serialized))
