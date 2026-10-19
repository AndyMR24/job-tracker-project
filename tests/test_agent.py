import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from job_agent.cv import _escape_latex, _select_bullets, generate
from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.permissions import PermissionDenied, require_external_approval
from job_agent.profile import ValidationError, load_config, load_profile
from job_agent.storage import Store
from pypdf import PdfReader

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import SAMPLE_EMAIL, SAMPLE_GITHUB, SAMPLE_LINKEDIN, SAMPLE_PHONE, SAMPLE_PROJECT, SAMPLE_THESIS, write_config, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import SAMPLE_EMAIL, SAMPLE_GITHUB, SAMPLE_LINKEDIN, SAMPLE_PHONE, SAMPLE_PROJECT, SAMPLE_THESIS, write_config, write_profile


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.root = Path(self.directory.name)
        self.profile = load_profile(write_profile(self.root)); self.config = load_config(write_config(self.root))

    def tearDown(self): self.directory.cleanup()

    def test_profile_rejects_missing_facts(self):
        path = self.root / "bad.json"; path.write_text('{"identity":{}}')
        with self.assertRaises(ValidationError): load_profile(path)

    def test_junior_match_is_better_than_senior(self):
        junior = Job("Junior Python Developer", location="Aachen", arrangement="hybrid", requirements=[Requirement("Python", "mandatory")])
        senior = Job("Senior Python Developer", requirements=[Requirement("Python", "mandatory")])
        self.assertGreater(evaluate(junior, self.profile, self.config).score, evaluate(senior, self.profile, self.config).score)
        self.assertTrue(evaluate(senior, self.profile, self.config).excluded)

    def test_required_master_is_excluded_but_preferred_is_not(self):
        required = evaluate(Job("Data Analyst", requirements=[Requirement("Master's degree", "mandatory")]), self.profile, self.config)
        preferred = evaluate(Job("Data Analyst", requirements=[Requirement("Master's degree", "preferred")]), self.profile, self.config)
        self.assertTrue(required.excluded); self.assertFalse(preferred.excluded); self.assertLess(required.score, preferred.score)

    def test_mandatory_gap_is_stronger_than_optional_gap(self):
        must = evaluate(Job("Data Analyst", requirements=[Requirement("5 years of experience", "mandatory")]), self.profile, self.config)
        nice = evaluate(Job("Data Analyst", requirements=[Requirement("5 years of experience", "preferred")]), self.profile, self.config)
        self.assertLess(must.score, nice.score)
        # a requirement the profile does not list is unknown, so its kind carries no penalty
        unlisted_mandatory = evaluate(Job("Data Analyst", requirements=[Requirement("R", "mandatory")]), self.profile, self.config)
        unlisted_preferred = evaluate(Job("Data Analyst", requirements=[Requirement("R", "preferred")]), self.profile, self.config)
        self.assertEqual(unlisted_mandatory.score, unlisted_preferred.score); self.assertNotIn("r", self.profile.skills)

    def test_unknown_and_location_are_visible(self):
        result = evaluate(Job("Data Analyst", location="Berlin", arrangement="onsite"), self.profile, self.config)
        self.assertTrue(result.uncertainties); self.assertTrue(result.concerns)

    def test_store_persists_and_exact_url_deduplicates(self):
        database = self.root / "agent.sqlite"; store = Store(database)
        job = Job("Junior Python Developer", source_url="https://example.test/1", requirements=[Requirement("Python", "mandatory")])
        first, created = store.save_job(job, evaluate(job, self.profile, self.config).to_dict()); second, duplicate = store.save_job(job, evaluate(job, self.profile, self.config).to_dict())
        self.assertTrue(created); self.assertFalse(duplicate); self.assertEqual(first, second); self.assertEqual(len(store.list_jobs()), 1)
        store.set_decision(first, "reject", "role mismatch")
        store.close()
        reopened = Store(database)
        self.assertEqual(reopened.get_job(first)[2]["status"], "rejected_by_user")
        reopened.close()

    def test_application_statuses_and_invalid_status(self):
        store = Store(self.root / "agent.sqlite"); job_id, _ = store.save_job(Job("Role"), {"score": 10})
        store.update_application(job_id, "applied", "2026-01-01", "Manual only")
        self.assertEqual(store.applications()[0]["status"], "applied")
        with self.assertRaises(ValueError): store.update_application(job_id, "saved", None, None)
        store.close()

    def test_application_date_defaults_for_applied_and_is_preserved(self):
        store = Store(self.root / "agent.sqlite")
        try:
            job_id, _ = store.save_job(Job("Role"), {"score": 10})
            today = date.today().isoformat()
            store.update_application(job_id, "applied", None, None)
            self.assertEqual(store.applications()[0]["application_date"], today)
            store.update_application(job_id, "interview", None, None)
            self.assertEqual(store.applications()[0]["application_date"], today)
            store.update_application(job_id, "offer", "2026-02-03", None)
            self.assertEqual(store.applications()[0]["application_date"], "2026-02-03")
            store.update_application(job_id, "withdrawn", None, None)
            self.assertEqual(store.applications()[0]["application_date"], "2026-02-03")

            other_id, _ = store.save_job(Job("Other"), {"score": 10})
            store.update_application(other_id, "interview", None, None)
            other = next(row for row in store.applications() if row["job_id"] == other_id)
            self.assertIsNone(other["application_date"])
            store.update_application(other_id, "applied", None, None)
            other = next(row for row in store.applications() if row["job_id"] == other_id)
            self.assertEqual(other["application_date"], today)
        finally:
            store.close()

    def test_remove_from_shortlist_restores_status_without_deleting_records(self):
        store = Store(self.root / "agent.sqlite")
        try:
            plain_id, _ = store.save_job(Job("Plain"), {"score": 10})
            store.set_decision(plain_id, "save")
            store.remove_from_shortlist(plain_id)
            plain = store.connection.execute("SELECT status,rejection_reason FROM jobs WHERE id=?", (plain_id,)).fetchone()
            self.assertEqual((plain["status"], plain["rejection_reason"]), ("discovered", None))

            applied_id, _ = store.save_job(Job("Applied"), {"score": 10})
            store.update_application(applied_id, "applied", "2026-01-02", "sent manually")
            store.set_decision(applied_id, "save", "stale reason")
            store.save_cv(applied_id, "draft.pdf", [])
            before_jobs = store.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            before_applications = store.connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            before_cv = store.connection.execute("SELECT COUNT(*) FROM cv_versions").fetchone()[0]
            before_audit = len(store.history())

            store.remove_from_shortlist(applied_id)
            row = store.connection.execute("SELECT status,rejection_reason FROM jobs WHERE id=?", (applied_id,)).fetchone()
            self.assertEqual((row["status"], row["rejection_reason"]), ("applied", None))
            application = next(item for item in store.applications() if item["job_id"] == applied_id)
            self.assertEqual((application["status"], application["application_date"], application["notes"]), ("applied", "2026-01-02", "sent manually"))
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], before_jobs)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0], before_applications)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM cv_versions").fetchone()[0], before_cv)
            events = [item["event"] for item in store.history()]
            self.assertEqual(len(events), before_audit + 1)
            self.assertEqual(events[0], "job_removed_from_shortlist")
        finally:
            store.close()

    def test_remove_from_shortlist_rejects_a_job_that_is_not_saved(self):
        store = Store(self.root / "agent.sqlite")
        try:
            job_id, _ = store.save_job(Job("Role"), {"score": 10})
            with self.assertRaises(ValueError):
                store.remove_from_shortlist(job_id)
        finally:
            store.close()

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed in this test environment")
    def test_cv_uses_profile_facts_without_claiming_employment(self):
        output = self.root / "draft.pdf"; generate(Job("Junior Python Developer", requirements=[Requirement("Python", "mandatory")]), self.profile, output)
        self.assertGreater(output.stat().st_size, 0)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
        self.assertIn("Python", text); self.assertNotIn("professional employment", text.lower()); self.assertNotIn("React", text)

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed in this test environment")
    def test_cv_respects_output_path_and_escapes_latex(self):
        output = self.root / "nested" / "custom.pdf"
        generate(Job("C++ Developer", requirements=[Requirement("Python")]), self.profile, output)
        self.assertTrue(output.exists())
        self.assertEqual(_escape_latex("A&B_50%"), r"A\&B\_50\%")

    def test_missing_pdflatex_is_clear(self):
        with patch("job_agent.cv.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pdflatex was not found on PATH"):
                generate(Job("Role"), self.profile, self.root / "missing.pdf")

    def test_tex_output_contact_thesis_and_missing_contact_fields(self):
        def fake_compile(command, cwd, **kwargs):
            self.assertTrue((Path(cwd) / "resume.tex").exists())
            (Path(cwd) / "resume.pdf").write_bytes(b"fake pdf")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        output = self.root / "nested" / "cv_job_7.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_compile):
            generate(Job("Python Developer", requirements=[Requirement("Python")]), self.profile, output)
        tex_path = output.with_suffix(".tex")
        tex = tex_path.read_text(encoding="utf-8")
        self.assertTrue(tex_path.exists())
        self.assertIn(SAMPLE_EMAIL, tex)
        self.assertIn(SAMPLE_PHONE, tex)
        self.assertNotIn(r"\href{tel:" + SAMPLE_PHONE + "}{" + SAMPLE_PHONE + "}", tex)
        self.assertIn(r"\href{mailto:" + SAMPLE_EMAIL + "}{" + SAMPLE_EMAIL + "}", tex)
        self.assertIn(r"\href{" + SAMPLE_GITHUB + "}{github.com/example-user}", tex)
        self.assertIn(r"\href{" + SAMPLE_LINKEDIN + "}{www.linkedin.com/in/example-user}", tex)
        self.assertIn(SAMPLE_THESIS, tex)
        self.assertEqual(tex.count(SAMPLE_THESIS), 1)
        self.assertIn(SAMPLE_PROJECT, tex)
        self.assertGreaterEqual(tex.count("\\item "), 2)

        profile_data = dict(self.profile.data)
        profile_data["contact"] = {"email": "only@example.test"}
        profile_path = self.root / "profile-no-social.json"
        profile_path.write_text(json.dumps(profile_data), encoding="utf-8")
        profile_without_social = load_profile(profile_path)
        output_without_social = self.root / "no-social.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_compile):
            generate(Job("Python Developer"), profile_without_social, output_without_social)
        tex_without_social = output_without_social.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertIn("only@example.test", tex_without_social)
        self.assertNotIn("github.com", tex_without_social)
        self.assertNotIn("linkedin.com", tex_without_social)

    def test_structured_project_bullets_are_selected_deterministically(self):
        projects = {item["name"]: item for item in self.profile.data["projects"]}
        churn = projects[SAMPLE_PROJECT]
        self.assertEqual(len(churn["candidate_bullets"]), 6)
        self.assertEqual(len(churn["general_bullets"]), 3)
        selected = _select_bullets(churn, {"python"})
        self.assertEqual(selected, churn["general_bullets"])
        self.assertLessEqual(len(selected), 3)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertIn("technical_practice", self.profile.data)
        self.assertIn("Python", self.profile.data["technical_practice"])
        self.assertNotIn("technical_practice", self.profile.data.get("rendered_sections", {}))

    def test_external_data_needs_specific_approval_and_application_is_blocked(self):
        with self.assertRaises(PermissionDenied): require_external_approval(action="send_cv", destination="Example GmbH", data_summary="CV", approved=False)
        self.assertTrue(require_external_approval(action="send_cv", destination="Example GmbH", data_summary="CV", approved=True)["approved"])
        with self.assertRaises(PermissionDenied): require_external_approval(action="submit_application", destination="Example GmbH", data_summary="application", approved=True)


if __name__ == "__main__": unittest.main()
