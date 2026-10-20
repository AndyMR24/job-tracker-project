"""Re-evaluation maintenance: stored evaluations refresh without touching listing facts or user state."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from job_agent.cli import main as cli_main
from job_agent.evaluator import evaluate
from job_agent.maintenance import refresh_evaluations
from job_agent.normalizer import normalize
from job_agent.profile import load_config, load_profile
from job_agent.storage import Store

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile

STALE = {"score": 93, "assessment": "recommended", "excluded": False, "strong_matches": ["Title is related to a configured target role."], "potential_gaps": [], "concerns": [], "uncertainties": []}


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile_path = write_profile(self.directory.name); self.config_path = write_config(self.directory.name)
        self.profile = load_profile(self.profile_path)
        self.config = load_config(self.config_path)
        self.database = Path(self.directory.name) / "jobs.sqlite"
        self.store = Store(self.database)
        self.ids = {}
        fixtures = {
            "restricted": {"title": "Python Developer", "source": "himalayas", "external_job_id": "h1", "source_url": "https://himalayas.test/1", "metadata": {"location_restrictions": ["United States"]}},
            "current": {"title": "Junior Data Analyst", "source": "adzuna", "external_job_id": "a1", "source_url": "https://adzuna.test/1", "location": "Aachen", "arrangement": "hybrid"},
            "saved": {"title": "Junior Data Scientist", "source": "ba", "external_job_id": "b1", "source_url": "https://ba.test/1", "location": "Aachen", "arrangement": "hybrid"},
            "rejected": {"title": "Werkstudent Data Science", "source": "nomado24", "external_job_id": "n1", "source_url": "https://nomado24.test/1", "location": "Aachen", "arrangement": "hybrid"},
        }
        for name, fixture in fixtures.items():
            job = normalize(dict(fixture))
            evaluation = evaluate(job, self.profile, self.config).to_dict() if name == "current" else dict(STALE)
            job_id, _ = self.store.save_job(job, evaluation)
            self.ids[name] = job_id
        self.store.set_decision(self.ids["saved"], "save")
        self.store.set_decision(self.ids["rejected"], "reject", "too far")
        self.store.update_application(self.ids["saved"], "applied", "2026-09-20", "sent manually")
        self.store.save_cv(self.ids["saved"], "draft.pdf", ["education"])
        self.before = self.snapshot()

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def snapshot(self):
        jobs = {row["id"]: (row["payload"], row["status"], row["rejection_reason"], row["viewed"], row["last_seen_at"]) for row in self.store.list_jobs(include_rejected=True)}
        evaluations = {row["job_id"]: (row["payload"], row["created_at"]) for row in self.store.connection.execute("SELECT * FROM evaluations")}
        applications = [(row["job_id"], row["status"], row["application_date"], row["notes"]) for row in self.store.applications()]
        cv_versions = [(row["job_id"], row["path"], row["source_facts"]) for row in self.store.cv_versions()]
        audit = [(row["event"], row["job_id"], row["details"]) for row in self.store.history()]
        return {"jobs": jobs, "evaluations": evaluations, "applications": applications, "cv_versions": cv_versions, "audit": audit}

    def evaluation_of(self, job_id):
        return json.loads(self.store.connection.execute("SELECT payload FROM evaluations WHERE job_id=?", (job_id,)).fetchone()["payload"])

    def test_refresh_updates_only_changed_evaluations(self):
        summary = refresh_evaluations(self.store, self.profile, self.config)
        self.assertEqual(summary["examined"], 4)
        self.assertEqual(summary["changed"], 3)
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["newly_excluded"], 1)
        self.assertEqual(summary["score_changed"], 3)

        restricted = self.evaluation_of(self.ids["restricted"])
        self.assertTrue(restricted["excluded"])
        self.assertEqual(restricted["assessment"], "rejected")
        self.assertTrue(any("United States" in concern for concern in restricted["concerns"]))
        self.assertNotIn("recommended", restricted["assessment"])

        self.assertEqual(self.evaluation_of(self.ids["saved"]), evaluate(normalize({"title": "Junior Data Scientist", "source": "ba", "external_job_id": "b1", "source_url": "https://ba.test/1", "location": "Aachen", "arrangement": "hybrid"}), self.profile, self.config).to_dict())
        self.assertEqual(self.snapshot()["evaluations"][self.ids["current"]], self.before["evaluations"][self.ids["current"]])

    def test_refresh_preserves_listing_facts_decisions_and_history(self):
        refresh_evaluations(self.store, self.profile, self.config)
        after = self.snapshot()
        self.assertEqual(after["jobs"], self.before["jobs"])
        self.assertEqual(after["applications"], self.before["applications"])
        self.assertEqual(after["cv_versions"], self.before["cv_versions"])
        self.assertEqual(after["audit"], self.before["audit"])
        self.assertEqual(after["jobs"][self.ids["saved"]][1], "applied")
        self.assertEqual(after["jobs"][self.ids["rejected"]][1:3], ("rejected_by_user", "too far"))

    def test_refresh_applies_a_new_radius_without_touching_user_managed_state(self):
        fixture = {
            "title": "Data Analyst",
            "source": "adzuna",
            "external_job_id": "frankfurt",
            "source_url": "https://adzuna.test/frankfurt",
            "location": "Frankfurt am Main, Hessen",
            "arrangement": "hybrid",
        }
        job = normalize(fixture)
        old_result = evaluate(job, self.profile, self.config)
        self.assertFalse(old_result.excluded)
        job_id, _ = self.store.save_job(job, old_result.to_dict())
        before = self.snapshot()
        config = {
            **self.config,
            "location_preferences": {**self.config["location_preferences"], "max_distance_km": 100},
        }
        refresh_evaluations(self.store, self.profile, config)
        after = self.snapshot()
        refreshed = self.evaluation_of(job_id)
        self.assertTrue(refreshed["excluded"])
        self.assertTrue(any("Frankfurt am Main" in concern for concern in refreshed["concerns"]))
        for field in ("jobs", "applications", "cv_versions", "audit"):
            with self.subTest(field=field):
                self.assertEqual(after[field], before[field])

    def test_refresh_is_idempotent(self):
        refresh_evaluations(self.store, self.profile, self.config)
        second = refresh_evaluations(self.store, self.profile, self.config)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["unchanged"], 4)

    def test_cli_command_reports_and_records_a_maintenance_event(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "re-evaluate"])
        text = output.getvalue()
        self.assertIn("Re-evaluated 4 stored job(s): 3 updated, 1 unchanged.", text)
        self.assertIn("Newly excluded: 1", text)
        self.assertIn("himalayas: 1 examined, 1 updated, 1 newly excluded", text)
        after = self.snapshot()
        maintenance = [item for item in after["audit"] if item[0] == "evaluations_refreshed"]
        self.assertEqual(len(maintenance), 1)
        self.assertEqual(maintenance[0][1], None)
        self.assertEqual([item for item in after["audit"] if item[0] != "evaluations_refreshed"], self.before["audit"])
        self.assertEqual(after["jobs"], self.before["jobs"])
        self.assertEqual(after["applications"], self.before["applications"])

        repeated = io.StringIO()
        with contextlib.redirect_stdout(repeated):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "re-evaluate"])
        self.assertIn("0 updated, 4 unchanged", repeated.getvalue())
        self.assertEqual([item for item in self.snapshot()["audit"] if item[0] == "evaluations_refreshed"], maintenance)

    def test_cli_listing_reflects_the_refreshed_evaluation(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "list"])
        self.assertIn("Python Developer", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "re-evaluate"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "list"])
        self.assertNotIn("Python Developer", output.getvalue())


if __name__ == "__main__":
    unittest.main()
