"""SQLite persistence and audit events. No credentials are stored."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from .models import Job

STATUSES = {"discovered", "saved", "rejected_by_user", "applied", "interview", "offer", "rejected_by_company", "withdrawn"}
SCHEMA_VERSION = 1
_SOURCE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LEGACY_JOB_COLUMNS = ("id", "source_url", "external_job_id", "payload", "discovered_at", "last_seen_at", "viewed", "status", "rejection_reason")
_V1_JOB_COLUMNS = ("id", "source", "source_url", "external_job_id", "payload", "discovered_at", "last_seen_at", "viewed", "status", "rejection_reason")
_LEGACY_JOB_SIGNATURE = (
    ("id", "INTEGER", 0, 1), ("source_url", "TEXT", 0, 0), ("external_job_id", "TEXT", 0, 0),
    ("payload", "TEXT", 1, 0), ("discovered_at", "TEXT", 1, 0), ("last_seen_at", "TEXT", 1, 0),
    ("viewed", "INTEGER", 0, 0), ("status", "TEXT", 1, 0), ("rejection_reason", "TEXT", 0, 0),
)
_V1_JOB_SIGNATURE = (
    ("id", "INTEGER", 0, 1), ("source", "TEXT", 1, 0), ("source_url", "TEXT", 0, 0),
    ("external_job_id", "TEXT", 0, 0), ("payload", "TEXT", 1, 0), ("discovered_at", "TEXT", 1, 0),
    ("last_seen_at", "TEXT", 1, 0), ("viewed", "INTEGER", 0, 0), ("status", "TEXT", 1, 0),
    ("rejection_reason", "TEXT", 0, 0),
)
_DEPENDENT_TABLES = ("evaluations", "applications", "cv_versions", "audit_events")


class JobIdentityConflict(ValueError):
    """Raised when source URL evidence conflicts with the canonical job identity."""


def _normalize_source(value: object) -> str:
    if isinstance(value, str):
        source = value.strip().lower()
        if source and _SOURCE_IDENTIFIER.fullmatch(source):
            return source
    return "unknown"


def _identity_value(value: object, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.lower() if lower else normalized


def _create_jobs_v1(name: str = "jobs") -> str:
    return f"""CREATE TABLE {name} (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_url TEXT,
        external_job_id TEXT,
        payload TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        viewed INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'discovered',
        rejection_reason TEXT,
        UNIQUE(source, external_job_id),
        UNIQUE(source, source_url)
    )"""


_SCHEMA_V1 = _create_jobs_v1() + """;
CREATE TABLE IF NOT EXISTS evaluations (job_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (job_id INTEGER PRIMARY KEY, status TEXT NOT NULL, application_date TEXT, notes TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cv_versions (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, path TEXT NOT NULL, source_facts TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY, event TEXT NOT NULL, job_id INTEGER, details TEXT, created_at TEXT NOT NULL);
"""


def now() -> str: return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = None if str(path) == ":memory:" else Path(path)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        try:
            self._initialize_schema()
        except Exception:
            self.connection.close()
            raise

    def _table_names(self) -> set[str]:
        return {row["name"] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def _columns(self, table: str) -> tuple[str, ...]:
        return tuple(row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})"))

    def _column_signature(self, table: str) -> tuple[tuple[str, str, int, int], ...]:
        return tuple(
            (row["name"], str(row["type"]).upper(), int(row["notnull"]), int(row["pk"]))
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        )

    def _unique_indexes(self, table: str) -> set[tuple[str, ...]]:
        return {
            tuple(item["name"] for item in self.connection.execute(f"PRAGMA index_info('{row['name']}')"))
            for row in self.connection.execute(f"PRAGMA index_list({table})")
            if row["unique"]
        }

    def _initialize_schema(self) -> None:
        tables = self._table_names()
        if not tables:
            self.connection.executescript(_SCHEMA_V1)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.connection.commit()
            return
        if "jobs" not in tables or not set(_DEPENDENT_TABLES).issubset(tables):
            raise RuntimeError("Database schema is incomplete or unfamiliar; refusing to initialize it.")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        columns = self._columns("jobs")
        indexes = self._unique_indexes("jobs")
        if columns == _V1_JOB_COLUMNS:
            expected = {("source", "external_job_id"), ("source", "source_url")}
            if indexes != expected or self._column_signature("jobs") != _V1_JOB_SIGNATURE:
                raise RuntimeError("Schema version 1 does not match its expected source-aware definition.")
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}.")
            if version != SCHEMA_VERSION:
                self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self.connection.commit()
            return
        if columns == _LEGACY_JOB_COLUMNS:
            expected = {("source_url",), ("external_job_id",)}
            if indexes != expected or self._column_signature("jobs") != _LEGACY_JOB_SIGNATURE:
                raise RuntimeError("Legacy jobs schema does not match its expected definition.")
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Legacy database reports unsupported schema version {version}.")
            self._migrate_legacy_jobs_schema()
            return
        raise RuntimeError("Database jobs schema is unfamiliar; refusing to migrate it automatically.")

    def _backup_before_migration(self) -> Path | None:
        if self.path is None:
            return None
        base = self.path.with_name(self.path.name + ".pre-identity-v1.bak")
        backup_path = base
        counter = 1
        while backup_path.exists():
            backup_path = base.with_name(base.name + str(counter))
            counter += 1
        source = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
        except Exception:
            backup.close()
            source.close()
            backup_path.unlink(missing_ok=True)
            raise
        backup.close()
        source.close()
        return backup_path

    @staticmethod
    def _verify_backup(path: Path, expected_jobs: list[tuple], expected_dependents: dict[str, list[tuple]]) -> None:
        connection = sqlite3.connect(path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Migration backup integrity check returned {integrity!r}.")
            backup_columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(jobs)"))
            if backup_columns != _LEGACY_JOB_COLUMNS:
                raise RuntimeError("Migration backup validation failed: jobs schema does not match the legacy schema.")
            actual_jobs = [tuple(row) for row in connection.execute(
                "SELECT id,source_url,external_job_id,payload,discovered_at,last_seen_at,viewed,status,rejection_reason FROM jobs ORDER BY id"
            )]
            if actual_jobs != expected_jobs:
                raise RuntimeError("Migration backup validation failed: job rows do not match.")
            for table, expected in expected_dependents.items():
                actual = [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
                if actual != expected:
                    raise RuntimeError(f"Migration backup validation failed: {table} rows do not match.")
        finally:
            connection.close()

    @staticmethod
    def _migration_source(payload: str) -> str:
        try:
            value = json.loads(payload)
            return _normalize_source(value.get("source") if isinstance(value, dict) else None)
        except (TypeError, json.JSONDecodeError):
            return "unknown"

    def _migrate_legacy_jobs_schema(self) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute(
                "SELECT id, source_url, external_job_id, payload, discovered_at, last_seen_at, viewed, status, rejection_reason FROM jobs ORDER BY id"
            ).fetchall()
            expected_jobs = [tuple(row) for row in rows]
            migrated = []
            seen_external = set()
            seen_url = set()
            for row in rows:
                source = self._migration_source(row["payload"])
                external = _identity_value(row["external_job_id"])
                url = _identity_value(row["source_url"])
                if external is not None:
                    key = (source, external)
                    if key in seen_external:
                        raise RuntimeError(f"Migration aborted: duplicate source-aware external ID {key!r}.")
                    seen_external.add(key)
                if url is not None:
                    key = (source, url)
                    if key in seen_url:
                        raise RuntimeError(f"Migration aborted: duplicate source-aware source URL {key!r}.")
                    seen_url.add(key)
                migrated.append((row["id"], source, url, external, row["payload"], row["discovered_at"], row["last_seen_at"], row["viewed"], row["status"], row["rejection_reason"]))
            expected_ids = [item[0] for item in migrated]
            dependent_rows = {
                table: [tuple(row) for row in self.connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in _DEPENDENT_TABLES
            }
            dependent_counts = {table: len(rows) for table, rows in dependent_rows.items()}
            backup_path = self._backup_before_migration()
            if backup_path is not None:
                self._verify_backup(backup_path, expected_jobs, dependent_rows)
            if "jobs_identity_v1" in self._table_names():
                raise RuntimeError("Migration aborted: temporary jobs table already exists.")
            self.connection.execute(_create_jobs_v1("jobs_identity_v1"))
            self.connection.executemany(
                "INSERT INTO jobs_identity_v1(id,source,source_url,external_job_id,payload,discovered_at,last_seen_at,viewed,status,rejection_reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                migrated,
            )
            new_ids = [row[0] for row in self.connection.execute("SELECT id FROM jobs_identity_v1 ORDER BY id")]
            if new_ids != expected_ids:
                raise RuntimeError("Migration validation failed: copied job IDs do not match the legacy table.")
            after_counts = {
                table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in _DEPENDENT_TABLES
            }
            if after_counts != dependent_counts:
                raise RuntimeError("Migration validation failed: dependent-table counts changed.")
            for table in _DEPENDENT_TABLES:
                orphan_count = self.connection.execute(
                    f"SELECT COUNT(*) FROM {table} c LEFT JOIN jobs_identity_v1 j ON j.id=c.job_id "
                    "WHERE c.job_id IS NOT NULL AND j.id IS NULL"
                ).fetchone()[0]
                if orphan_count:
                    raise RuntimeError(f"Migration validation failed: {table} has {orphan_count} orphaned job reference(s).")
            self.connection.execute("DROP TABLE jobs")
            self.connection.execute("ALTER TABLE jobs_identity_v1 RENAME TO jobs")
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Migration validation failed: SQLite integrity check returned {integrity!r}.")
            foreign_keys = self.connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise RuntimeError(f"Migration validation failed: {len(foreign_keys)} foreign-key violation(s).")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        try:
            post_ids = [row[0] for row in self.connection.execute("SELECT id FROM jobs ORDER BY id")]
            post_version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if post_ids != expected_ids or post_version != SCHEMA_VERSION:
                raise RuntimeError("Migrated ID or schema-version values differ from the validated values.")
        except Exception as exc:
            raise RuntimeError(
                "Migration committed, but post-commit verification failed. Do not assume the migration "
                "was rolled back; inspect the database and the pre-migration backup before retrying."
            ) from exc

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def audit(self, event: str, job_id: int | None = None, details: str | None = None) -> None:
        self.connection.execute("INSERT INTO audit_events(event,job_id,details,created_at) VALUES (?,?,?,?)", (event, job_id, details, now())); self.connection.commit()

    def _ensure_job_exists(self, job_id: int) -> None:
        if not self.connection.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
            raise KeyError(f"Job {job_id} was not found.")

    def save_job(self, job: Job, evaluation: dict) -> tuple[int, bool]:
        stamp = now()
        source = _normalize_source(job.source)
        source_url = _identity_value(job.source_url)
        external_id = _identity_value(job.external_job_id)
        payload_data = job.to_dict()
        payload_data.update({"source": source, "source_url": source_url, "external_job_id": external_id})
        existing = None
        if external_id:
            existing = self.connection.execute(
                "SELECT id,external_job_id FROM jobs WHERE source=? AND external_job_id=?",
                (source, external_id),
            ).fetchone()
        if not existing and source_url:
            url_match = self.connection.execute(
                "SELECT id,external_job_id FROM jobs WHERE source=? AND source_url=?",
                (source, source_url),
            ).fetchone()
            if url_match:
                if external_id and url_match["external_job_id"] not in {None, external_id}:
                    raise JobIdentityConflict(
                        f"Source {source!r} URL {source_url!r} already belongs to external job "
                        f"{url_match['external_job_id']!r}; refusing to overwrite it with {external_id!r}."
                    )
                existing = url_match
        try:
            if existing:
                job_id = existing["id"]
                if source_url:
                    conflict = self.connection.execute(
                        "SELECT external_job_id FROM jobs WHERE source=? AND source_url=? AND id<>?",
                        (source, source_url, job_id),
                    ).fetchone()
                    if conflict:
                        raise JobIdentityConflict(
                            f"Source {source!r} URL {source_url!r} already belongs to external job "
                            f"{conflict['external_job_id']!r}; refusing to reassign it to {external_id!r}."
                        )
                stored_external_id = external_id or existing["external_job_id"]
                payload_data["external_job_id"] = stored_external_id
                payload = json.dumps(payload_data)
                self.connection.execute(
                    "UPDATE jobs SET source=?,source_url=?,external_job_id=?,payload=?,last_seen_at=? WHERE id=?",
                    (source, source_url, stored_external_id, payload, stamp, job_id),
                )
                created = False
            else:
                payload = json.dumps(payload_data)
                cursor = self.connection.execute(
                    "INSERT INTO jobs(source,source_url,external_job_id,payload,discovered_at,last_seen_at) VALUES (?,?,?,?,?,?)",
                    (source, source_url, external_id, payload, stamp, stamp),
                )
                job_id = cursor.lastrowid
                created = True
            self.connection.execute(
                "INSERT OR REPLACE INTO evaluations(job_id,payload,created_at) VALUES (?,?,?)",
                (job_id, json.dumps(evaluation), stamp),
            )
            self.connection.execute(
                "INSERT INTO audit_events(event,job_id,details,created_at) VALUES (?,?,?,?)",
                ("job_discovered" if created else "job_seen_again", job_id, None, stamp),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise JobIdentityConflict(
                f"Job identity conflict for source {source!r}, external ID {external_id!r}, URL {source_url!r}."
            ) from exc
        except Exception:
            self.connection.rollback()
            raise
        return job_id, created

    def get_job(self, job_id: int) -> tuple[Job, dict, sqlite3.Row]:
        row = self.connection.execute("SELECT j.*,e.payload evaluation FROM jobs j LEFT JOIN evaluations e ON j.id=e.job_id WHERE j.id=?", (job_id,)).fetchone()
        if not row: raise KeyError(f"Job {job_id} was not found.")
        self.connection.execute("UPDATE jobs SET viewed=1 WHERE id=?", (job_id,)); self.connection.commit(); self.audit("job_viewed", job_id)
        return Job.from_dict(json.loads(row["payload"])), json.loads(row["evaluation"]), row

    def list_jobs(self, include_rejected: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT j.*,e.payload evaluation FROM jobs j LEFT JOIN evaluations e ON j.id=e.job_id"
        if not include_rejected: sql += " WHERE j.status != 'rejected_by_user' AND COALESCE(json_extract(e.payload,'$.excluded'),0) != 1"
        return self.connection.execute(sql + " ORDER BY json_extract(e.payload,'$.score') DESC, j.last_seen_at DESC").fetchall()

    def set_decision(self, job_id: int, decision: str, reason: str | None = None) -> None:
        status = {"save": "saved", "reject": "rejected_by_user"}.get(decision)
        if not status: raise ValueError("Decision must be save or reject.")
        self._ensure_job_exists(job_id)
        self.connection.execute("UPDATE jobs SET status=?,rejection_reason=? WHERE id=?", (status, reason, job_id)); self.connection.commit(); self.audit(f"job_{decision}d", job_id, reason)

    def remove_from_shortlist(self, job_id: int) -> None:
        self._ensure_job_exists(job_id)
        row = self.connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row["status"] != "saved":
            raise ValueError(f"Job {job_id} is not on the shortlist.")
        application = self.connection.execute("SELECT status FROM applications WHERE job_id=?", (job_id,)).fetchone()
        status = application["status"] if application else "discovered"
        self.connection.execute("UPDATE jobs SET status=?,rejection_reason=NULL WHERE id=?", (status, job_id))
        self.connection.commit()
        self.audit("job_removed_from_shortlist", job_id)

    def update_application(self, job_id: int, status: str, application_date: str | None, notes: str | None) -> None:
        if status not in STATUSES - {"discovered", "saved", "rejected_by_user"}: raise ValueError(f"Invalid application status: {status}")
        self._ensure_job_exists(job_id)
        existing = self.connection.execute("SELECT application_date FROM applications WHERE job_id=?", (job_id,)).fetchone()
        effective_date = application_date or (existing["application_date"] if existing else None)
        if status == "applied" and not effective_date:
            effective_date = date.today().isoformat()
        self.connection.execute("INSERT INTO applications(job_id,status,application_date,notes,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,application_date=COALESCE(excluded.application_date,applications.application_date),notes=COALESCE(excluded.notes,applications.notes),updated_at=excluded.updated_at", (job_id,status,effective_date,notes,now()))
        self.connection.execute("UPDATE jobs SET status=? WHERE id=?", (status,job_id)); self.connection.commit(); self.audit("application_status_changed", job_id, status)

    def applications(self): return self.connection.execute("SELECT a.*,j.payload FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.updated_at DESC").fetchall()
    def history(self): return self.connection.execute("SELECT * FROM audit_events ORDER BY id DESC").fetchall()
    def save_cv(self, job_id: int, path: str, facts: list[str]) -> None:
        self._ensure_job_exists(job_id)
        self.connection.execute("INSERT INTO cv_versions(job_id,path,source_facts,created_at) VALUES(?,?,?,?)", (job_id,path,json.dumps(facts),now())); self.connection.commit(); self.audit("cv_generated",job_id)

    def replace_evaluation(self, job_id: int, evaluation: dict) -> bool:
        """Replace one stored evaluation, leaving listing facts, decisions and audit history alone.

        Returns True when the row was rewritten and False when the stored evaluation already matches,
        so maintenance work does not touch records that are unchanged.
        """
        self._ensure_job_exists(job_id)
        existing = self.connection.execute("SELECT payload FROM evaluations WHERE job_id=?", (job_id,)).fetchone()
        if existing and json.loads(existing["payload"]) == evaluation:
            return False
        self.connection.execute("INSERT OR REPLACE INTO evaluations(job_id,payload,created_at) VALUES (?,?,?)", (job_id, json.dumps(evaluation), now()))
        self.connection.commit()
        return True

    def cv_versions(self, job_id: int | None = None) -> list[sqlite3.Row]:
        if job_id is None: return self.connection.execute("SELECT * FROM cv_versions ORDER BY id DESC").fetchall()
        return self.connection.execute("SELECT * FROM cv_versions WHERE job_id=? ORDER BY id DESC", (job_id,)).fetchall()
