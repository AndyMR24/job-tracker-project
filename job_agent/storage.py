"""SQLite persistence and audit events. No credentials are stored."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Job

STATUSES = {"discovered", "saved", "rejected_by_user", "applied", "interview", "offer", "rejected_by_company", "withdrawn"}


def now() -> str: return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, source_url TEXT UNIQUE, external_job_id TEXT UNIQUE,
          payload TEXT NOT NULL, discovered_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, viewed INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'discovered', rejection_reason TEXT);
        CREATE TABLE IF NOT EXISTS evaluations (job_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS applications (job_id INTEGER PRIMARY KEY, status TEXT NOT NULL, application_date TEXT, notes TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cv_versions (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, path TEXT NOT NULL, source_facts TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY, event TEXT NOT NULL, job_id INTEGER, details TEXT, created_at TEXT NOT NULL);
        """)
        self.connection.commit()

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
        stamp = now(); payload = json.dumps(job.to_dict())
        existing = None
        if job.source_url: existing = self.connection.execute("SELECT id FROM jobs WHERE source_url=?", (job.source_url,)).fetchone()
        if not existing and job.external_job_id: existing = self.connection.execute("SELECT id FROM jobs WHERE external_job_id=?", (job.external_job_id,)).fetchone()
        if existing:
            job_id = existing["id"]; self.connection.execute("UPDATE jobs SET payload=?,last_seen_at=? WHERE id=?", (payload, stamp, job_id)); created = False
        else:
            cursor = self.connection.execute("INSERT INTO jobs(source_url,external_job_id,payload,discovered_at,last_seen_at) VALUES (?,?,?,?,?)", (job.source_url, job.external_job_id, payload, stamp, stamp)); job_id = cursor.lastrowid; created = True
        self.connection.execute("INSERT OR REPLACE INTO evaluations(job_id,payload,created_at) VALUES (?,?,?)", (job_id, json.dumps(evaluation), stamp)); self.connection.commit()
        self.audit("job_discovered" if created else "job_seen_again", job_id); return job_id, created

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

    def update_application(self, job_id: int, status: str, application_date: str | None, notes: str | None) -> None:
        if status not in STATUSES - {"discovered", "saved", "rejected_by_user"}: raise ValueError(f"Invalid application status: {status}")
        self._ensure_job_exists(job_id)
        self.connection.execute("INSERT INTO applications(job_id,status,application_date,notes,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,application_date=COALESCE(excluded.application_date,applications.application_date),notes=COALESCE(excluded.notes,applications.notes),updated_at=excluded.updated_at", (job_id,status,application_date,notes,now()))
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