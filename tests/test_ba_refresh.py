"""BA detail refreshes repair only missing locations without touching user-managed state."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from job_agent.ba import BAError
from job_agent.cli import main as cli_main
from job_agent.evaluator import evaluate
from job_agent.maintenance import refresh_ba_locations, refresh_evaluations
from job_agent.models import Job
from job_agent.profile import load_config, load_profile
from job_agent.storage import Store

try:
    from support import write_config, write_profile
except ImportError:  # pragma: no cover
    from tests.support import write_config, write_profile


class FakeBA:
    def __init__(self, details=None, errors=None):
        self.details = details or {}
        self.errors = errors or {}
        self.calls = []

    def detail(self, reference):
        self.calls.append(reference)
        if reference in self.errors:
            raise self.errors[reference]
        return self.details.get(reference, {})


def ba_detail(location="Aachen", ref="ba-1", coordinates=(50.7753, 6.0839)):
    return {
        "stellenangebotsTitel": "BA Data Role",
        "referenznummer": ref,
        "stellenlokationen": [{
            "adresse": {"plz": "52062", "ort": location, "region": "NRW", "land": "DEUTSCHLAND"},
            "breite": coordinates[0],
            "laenge": coordinates[1],
        }],
    }


class BARefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.profile_path = write_profile(root)
        self.config_path = write_config(root)
        self.profile = load_profile(self.profile_path)
        self.config = load_config(self.config_path)
        self.database = root / "jobs.sqlite"
        self.store = Store(self.database)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def add_job(self, reference="ba-1", location=None):
        job = Job("BA Data Role", source="ba", source_url="https://ba.test/%s" % reference, external_job_id=reference, location=location, arrangement="hybrid")
        job_id, _ = self.store.save_job(job, evaluate(job, self.profile, self.config).to_dict())
        return job_id

    def snapshot(self):
        jobs = self.store.connection.execute("SELECT id,payload,status,rejection_reason,viewed,last_seen_at FROM jobs ORDER BY id").fetchall()
        evaluations = self.store.connection.execute("SELECT job_id,payload FROM evaluations ORDER BY job_id").fetchall()
        applications = self.store.connection.execute("SELECT job_id,status,application_date,notes FROM applications ORDER BY job_id").fetchall()
        cv_versions = self.store.connection.execute("SELECT job_id,path,source_facts FROM cv_versions ORDER BY job_id").fetchall()
        audit = self.store.connection.execute("SELECT event,job_id,details FROM audit_events ORDER BY id").fetchall()
        return {"jobs": jobs, "evaluations": evaluations, "applications": applications, "cv_versions": cv_versions, "audit": audit}

    def test_dry_run_recovers_location_without_writing(self):
        job_id = self.add_job()
        source = FakeBA({"ba-1": ba_detail()})
        before = self.snapshot()
        summary = refresh_ba_locations(self.store, self.profile, self.config, apply=False, source=source)
        self.assertEqual(summary["examined"], 1)
        self.assertEqual(summary["locations_recovered"], 1)
        self.assertEqual(summary["would_update"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(source.calls, ["ba-1"])
        self.assertEqual(self.snapshot(), before)
        payload = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"])
        self.assertIsNone(payload["location"])

    def test_apply_recovers_nested_location_and_preserves_user_state(self):
        job_id = self.add_job()
        self.store.set_decision(job_id, "reject", "keep this reason")
        self.store.update_application(job_id, "applied", "2026-01-02", "manual application")
        self.store.get_job(job_id)
        self.store.save_cv(job_id, "draft.pdf", ["education"])
        before = self.snapshot()
        source = FakeBA({"ba-1": ba_detail()})
        summary = refresh_ba_locations(self.store, self.profile, self.config, apply=True, source=source)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["locations_recovered"], 1)
        self.assertGreaterEqual(summary["score_changed"], 1)
        row = self.store.connection.execute("SELECT payload,status,rejection_reason,viewed FROM jobs WHERE id=?", (job_id,)).fetchone()
        payload = json.loads(row["payload"])
        self.assertEqual(payload["location"], "Aachen")
        self.assertEqual(payload["metadata"]["postal_code"], "52062")
        self.assertEqual(payload["metadata"]["latitude"], 50.7753)
        self.assertEqual((row["status"], row["rejection_reason"], row["viewed"]), ("applied", "keep this reason", 1))
        self.assertEqual(self.store.connection.execute("SELECT status,application_date,notes FROM applications WHERE job_id=?", (job_id,)).fetchone()[:], ("applied", "2026-01-02", "manual application"))
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM cv_versions WHERE job_id=?", (job_id,)).fetchone()[0], 1)
        events = [item["event"] for item in self.store.history()]
        self.assertIn("ba_location_refreshed", events)
        self.assertTrue(set(item["event"] for item in before["audit"]).issubset(set(events)))
        self.assertEqual(refresh_evaluations(self.store, self.profile, self.config)["changed"], 0)

        second = refresh_ba_locations(self.store, self.profile, self.config, apply=True, source=source)
        self.assertEqual(second["examined"], 0)
        self.assertEqual(second["already_located"], 1)

    def test_refresh_uses_recovered_coordinates_for_geographic_evaluation(self):
        job_id = self.add_job()
        source = FakeBA({"ba-1": ba_detail(location="Unresolvable district", coordinates=(52.52, 13.405))})
        summary = refresh_ba_locations(self.store, self.profile, self.config, apply=True, source=source)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["newly_excluded"], 1)
        evaluation = json.loads(self.store.connection.execute("SELECT payload FROM evaluations WHERE job_id=?", (job_id,)).fetchone()["payload"])
        self.assertTrue(evaluation["excluded"])
        self.assertTrue(any("outside the configured geographic radius" in concern for concern in evaluation["concerns"]))
        self.assertEqual(refresh_evaluations(self.store, self.profile, self.config)["changed"], 0)

    def test_detail_failures_do_not_stop_other_jobs(self):
        good_id = self.add_job("good")
        bad_id = self.add_job("bad")
        source = FakeBA({"good": ba_detail(ref="good")}, {"bad": BAError("detail unavailable")})
        summary = refresh_ba_locations(self.store, self.profile, self.config, apply=True, source=source)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(len(summary["failed"]), 1)
        self.assertEqual(summary["failed"][0]["job_id"], bad_id)
        good = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (good_id,)).fetchone()["payload"])
        bad = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (bad_id,)).fetchone()["payload"])
        self.assertEqual(good["location"], "Aachen")
        self.assertIsNone(bad["location"])

    def test_existing_location_is_not_overwritten(self):
        job_id = self.add_job(location="Berlin")
        source = FakeBA({"ba-1": ba_detail(location="Aachen")})
        summary = refresh_ba_locations(self.store, self.profile, self.config, apply=True, source=source)
        self.assertEqual(summary["already_located"], 1)
        self.assertEqual(source.calls, [])
        payload = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"])
        self.assertEqual(payload["location"], "Berlin")

    def test_cli_is_dry_run_by_default_and_apply_writes(self):
        job_id = self.add_job()
        source = FakeBA({"ba-1": ba_detail()})
        with patch("job_agent.maintenance.BASource", lambda: source):
            output = io.StringIO()
            with redirect_stdout(output):
                cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "refresh-ba-locations"])
            self.assertIn("Dry run only", output.getvalue())
            payload = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"])
            self.assertIsNone(payload["location"])
            output = io.StringIO()
            with redirect_stdout(output):
                cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "refresh-ba-locations", "--apply"])
            self.assertIn("updated", output.getvalue())
            payload = json.loads(self.store.connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"])
            self.assertEqual(payload["location"], "Aachen")


if __name__ == "__main__":
    unittest.main()
