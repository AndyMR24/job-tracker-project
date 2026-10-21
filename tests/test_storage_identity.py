"""Source-aware job identity and legacy database migration."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.models import Job
from job_agent.storage import JobIdentityConflict, Store


LEGACY_SCHEMA = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source_url TEXT UNIQUE,
    external_job_id TEXT UNIQUE,
    payload TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    viewed INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'discovered',
    rejection_reason TEXT
);
CREATE TABLE evaluations (job_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE applications (job_id INTEGER PRIMARY KEY, status TEXT NOT NULL, application_date TEXT, notes TEXT, updated_at TEXT NOT NULL);
CREATE TABLE cv_versions (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, path TEXT NOT NULL, source_facts TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE audit_events (id INTEGER PRIMARY KEY, event TEXT NOT NULL, job_id INTEGER, details TEXT, created_at TEXT NOT NULL);
"""


def payload(title, source="adzuna", external_job_id=None, source_url=None):
    return json.dumps({
        "title": title,
        "source": source,
        "external_job_id": external_job_id,
        "source_url": source_url,
        "metadata": {},
    })


def create_legacy(path: Path, rows):
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA)
    connection.executemany(
        "INSERT INTO jobs(id,source_url,external_job_id,payload,discovered_at,last_seen_at,viewed,status,rejection_reason) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    connection.commit()
    connection.close()


class SourceAwareIdentityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def save(self, title, *, source, external=None, url=None):
        job = Job(title, source=source, external_job_id=external, source_url=url)
        return self.store.save_job(job, {"score": 50, "assessment": "borderline", "excluded": False})

    def test_same_source_and_external_id_updates_one_row(self):
        first, created = self.save("First", source="adzuna", external="1", url="https://a.test/1")
        second, created_again = self.save("Updated", source="adzuna", external="1", url="https://a.test/1")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_jobs()), 1)
        self.assertEqual(json.loads(self.store.list_jobs()[0]["payload"])["title"], "Updated")

    def test_same_external_id_or_url_from_different_sources_remains_separate(self):
        first, _ = self.save("Adzuna", source="adzuna", external="same", url="https://same.test/job")
        second, _ = self.save("BA", source="ba", external="same", url="https://same.test/job")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.store.list_jobs()), 2)

    def test_changed_url_updates_the_indexed_value_on_the_same_job(self):
        job_id, _ = self.save("Role", source="adzuna", external="1", url="https://a.test/old")
        same_id, _ = self.save("Role", source="adzuna", external="1", url="https://a.test/new")
        row = self.store.connection.execute("SELECT source_url,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(job_id, same_id)
        self.assertEqual(row["source_url"], "https://a.test/new")
        self.assertEqual(json.loads(row["payload"])["source_url"], "https://a.test/new")
        self.assertEqual(len(self.store.list_jobs()), 1)

    def test_same_source_url_conflict_is_rejected_without_overwrite(self):
        first, _ = self.save("First", source="adzuna", external="1", url="https://a.test/shared")
        with self.assertRaisesRegex(JobIdentityConflict, "already belongs to external job '1'"):
            self.save("Second", source="adzuna", external="2", url="https://a.test/shared")
        rows = self.store.list_jobs()
        self.assertEqual([row["id"] for row in rows], [first])
        self.assertEqual(json.loads(rows[0]["payload"])["title"], "First")

    def test_changing_url_to_another_jobs_url_is_rejected_without_overwrite(self):
        first, _ = self.save("First", source="adzuna", external="1", url="https://a.test/one")
        second, _ = self.save("Second", source="adzuna", external="2", url="https://a.test/two")
        self.store.set_decision(first, "save")
        self.store.set_decision(second, "reject", "keep")
        with self.assertRaisesRegex(JobIdentityConflict, "already belongs to external job '2'"):
            self.save("First changed", source="adzuna", external="1", url="https://a.test/two")
        rows = {
            row["id"]: (row["source_url"], row["status"], row["rejection_reason"], json.loads(row["payload"])["title"])
            for row in self.store.list_jobs()
        }
        self.assertEqual(rows[first], ("https://a.test/one", "saved", None, "First"))
        self.assertEqual(rows[second], ("https://a.test/two", "rejected_by_user", "keep", "Second"))

    def test_url_only_jobs_use_source_and_url_fallback(self):
        first, _ = self.save("First", source="nomado24", url="https://n.test/1")
        second, _ = self.save("Updated", source="nomado24", url="https://n.test/1")
        other, _ = self.save("Other source", source="himalayas", url="https://n.test/1")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(self.store.list_jobs()), 2)

    def test_url_only_reingest_preserves_existing_external_id_in_payload(self):
        job_id, _ = self.save("First", source="adzuna", external="known-id", url="https://a.test/1")
        same_id, _ = self.save("Updated without ID", source="adzuna", external=None, url="https://a.test/1")
        row = self.store.connection.execute("SELECT external_job_id,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(job_id, same_id)
        self.assertEqual(row["external_job_id"], "known-id")
        self.assertEqual(json.loads(row["payload"])["external_job_id"], "known-id")

    def test_missing_identifiers_create_explicit_independent_rows(self):
        first, _ = self.save("No identity one", source="")
        second, _ = self.save("No identity two", source="unknown")
        rows = self.store.list_jobs()
        self.assertNotEqual(first, second)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source"] for row in rows}, {"unknown"})

    def test_source_identifier_is_normalized_without_aliases(self):
        job_id, _ = self.save("Role", source=" Adzuna ", external="1")
        row = self.store.connection.execute("SELECT source,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["source"], "adzuna")
        self.assertEqual(json.loads(row["payload"])["source"], "adzuna")


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "legacy.sqlite3"

    def tearDown(self):
        self.directory.cleanup()

    def test_migration_preserves_jobs_dependents_and_creates_backup(self):
        create_legacy(self.database, [
            (10, "https://a.test/1", "a-1", payload("Adzuna role", "adzuna", "a-1", "https://a.test/1"), "2026-01-01", "2026-02-01", 1, "saved", "keep"),
            (20, None, "b-1", payload("BA role", "ba", "b-1"), "2026-01-02", "2026-02-02", 0, "rejected_by_user", "too far"),
        ])
        connection = sqlite3.connect(self.database)
        connection.executemany("INSERT INTO evaluations(job_id,payload,created_at) VALUES (?,?,?)", [(10, '{"score":70}', "t"), (20, '{"score":20}', "t")])
        connection.execute("INSERT INTO applications(job_id,status,application_date,notes,updated_at) VALUES (10,'applied','2026-01-03','notes','t')")
        connection.execute("INSERT INTO cv_versions(job_id,path,source_facts,created_at) VALUES (10,'draft.pdf','[\"skills\"]','t')")
        connection.executemany("INSERT INTO audit_events(event,job_id,details,created_at) VALUES (?,?,?,?)", [("old_one", 10, "a", "t"), ("old_two", 20, "b", "t")])
        connection.commit()
        before = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("jobs", "evaluations", "applications", "cv_versions", "audit_events")
        }
        connection.close()

        store = Store(self.database)
        self.assertEqual(store._columns("jobs"), ("id", "source", "source_url", "external_job_id", "payload", "discovered_at", "last_seen_at", "viewed", "status", "rejection_reason"))
        self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(
            {(row[0], row[1]) for row in store.connection.execute("SELECT source,external_job_id FROM jobs")},
            {("adzuna", "a-1"), ("ba", "b-1")},
        )
        self.assertEqual(
            [tuple(row) for row in store.connection.execute("SELECT id,source_url,external_job_id,payload,discovered_at,last_seen_at,viewed,status,rejection_reason FROM jobs ORDER BY id")],
            [
                (10, "https://a.test/1", "a-1", payload("Adzuna role", "adzuna", "a-1", "https://a.test/1"), "2026-01-01", "2026-02-01", 1, "saved", "keep"),
                (20, None, "b-1", payload("BA role", "ba", "b-1"), "2026-01-02", "2026-02-02", 0, "rejected_by_user", "too far"),
            ],
        )
        for table in ("evaluations", "applications", "cv_versions", "audit_events"):
            after = [tuple(row) for row in store.connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
            self.assertEqual(after, [tuple(row) for row in before[table]])
        store.close()

        backup = Path(str(self.database) + ".pre-identity-v1.bak")
        self.assertTrue(backup.exists())
        backup_connection = sqlite3.connect(backup)
        self.assertEqual(backup_connection.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertNotIn("source", [row[1] for row in backup_connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(backup_connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
        self.assertEqual(backup_connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(backup_connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 2)
        backup_connection.close()

    def test_migration_is_idempotent_and_does_not_create_another_backup(self):
        create_legacy(self.database, [(10, None, "1", payload("Role", "adzuna", "1"), "t", "t", 0, "discovered", None)])
        Store(self.database).close()
        backups_before = list(Path(self.directory.name).glob("*.pre-identity-v1.bak*"))
        reopened = Store(self.database)
        self.assertEqual(reopened.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        reopened.close()
        self.assertEqual(list(Path(self.directory.name).glob("*.pre-identity-v1.bak*")), backups_before)

    def test_missing_or_malformed_payload_source_uses_unknown(self):
        create_legacy(self.database, [
            (10, None, "1", '{"title":"No source"}', "t", "t", 0, "discovered", None),
            (20, None, "2", '{"title":', "t", "t", 0, "discovered", None),
        ])
        store = Store(self.database)
        rows = store.connection.execute("SELECT id,source,payload FROM jobs ORDER BY id").fetchall()
        self.assertEqual([(row["id"], row["source"]) for row in rows], [(10, "unknown"), (20, "unknown")])
        self.assertEqual(rows[1]["payload"], '{"title":')
        store.close()

    def test_identity_collision_aborts_without_changing_legacy_database(self):
        create_legacy(self.database, [
            (10, None, "1", payload("One", "adzuna", "1"), "t", "t", 0, "discovered", None),
            (20, None, " 1 ", payload("Two", "adzuna", " 1 "), "t", "t", 0, "discovered", None),
        ])
        with self.assertRaisesRegex(RuntimeError, "duplicate source-aware external ID"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        connection.close()

    def test_unknown_source_identity_collision_aborts(self):
        create_legacy(self.database, [
            (10, None, "1", '{"title":"One"}', "t", "t", 0, "discovered", None),
            (20, None, " 1 ", '{"title":"Two"}', "t", "t", 0, "discovered", None),
        ])
        with self.assertRaisesRegex(RuntimeError, r"duplicate source-aware external ID \('unknown', '1'\)"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        connection.close()

    def test_source_url_collision_aborts_without_replacing_legacy_table(self):
        create_legacy(self.database, [
            (10, "https://same", "1", payload("One", "adzuna", "1", "https://same"), "t", "t", 0, "discovered", None),
            (20, " https://same ", "2", payload("Two", "adzuna", "2", " https://same "), "t", "t", 0, "discovered", None),
        ])
        with self.assertRaisesRegex(RuntimeError, "duplicate source-aware source URL"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        connection.close()

    def test_transaction_rolls_back_when_migration_cannot_finish(self):
        create_legacy(self.database, [(10, None, "1", payload("Role", "adzuna", "1"), "t", "t", 0, "discovered", None)])
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE jobs_identity_v1 (id INTEGER)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "temporary jobs table already exists"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(connection.execute("SELECT ext_stub FROM (SELECT external_job_id AS ext_stub FROM jobs)").fetchone()[0], "1")
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        connection.close()

    def test_backup_failure_prevents_schema_changes(self):
        create_legacy(self.database, [(10, None, "1", payload("Role", "adzuna", "1"), "t", "t", 0, "discovered", None)])
        with patch.object(Store, "_backup_before_migration", side_effect=OSError("backup unavailable")):
            with self.assertRaisesRegex(OSError, "backup unavailable"):
                Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        connection.close()

    def test_unexpected_legacy_unique_index_is_rejected(self):
        create_legacy(self.database, [(10, None, "1", payload("Role", "adzuna", "1"), "t", "t", 0, "discovered", None)])
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE UNIQUE INDEX unexpected_jobs_title ON jobs(viewed,status)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "expected definition"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        connection.close()

    def test_dependent_orphan_aborts_before_legacy_table_is_replaced(self):
        create_legacy(self.database, [(10, None, "1", payload("Role", "adzuna", "1"), "t", "t", 0, "discovered", None)])
        connection = sqlite3.connect(self.database)
        connection.execute("INSERT INTO evaluations(job_id,payload,created_at) VALUES (999,'{}','t')")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "evaluations has 1 orphaned job reference"):
            Store(self.database)
        connection = sqlite3.connect(self.database)
        self.assertNotIn("source", [row[1] for row in connection.execute("PRAGMA table_info(jobs)")])
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 1)
        connection.close()

    def test_new_and_in_memory_databases_use_version_one_directly(self):
        memory = Store(":memory:")
        self.assertEqual(memory.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(
            memory._unique_indexes("jobs"),
            {("source", "external_job_id"), ("source", "source_url")},
        )
        memory.close()

        file_store = Store(self.database)
        self.assertEqual(file_store.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        file_store.close()
        self.assertEqual(list(Path(self.directory.name).glob("*.pre-identity-v1.bak*")), [])


if __name__ == "__main__":
    unittest.main()
