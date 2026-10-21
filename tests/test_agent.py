import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from job_agent.cv import _escape_latex, _select_bullets, _select_projects, generate, versioned_output_path
from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.permissions import PermissionDenied, require_external_approval
from job_agent.profile import Profile, ValidationError, load_config, load_profile
from job_agent.storage import Store
from pypdf import PdfReader

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import SAMPLE_EMAIL, SAMPLE_GITHUB, SAMPLE_LINKEDIN, SAMPLE_PHONE, SAMPLE_PROJECT, SAMPLE_THESIS, fake_pdflatex, pdflatex_usable, write_config, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import SAMPLE_EMAIL, SAMPLE_GITHUB, SAMPLE_LINKEDIN, SAMPLE_PHONE, SAMPLE_PROJECT, SAMPLE_THESIS, fake_pdflatex, pdflatex_usable, write_config, write_profile


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

    def test_cv_uses_profile_facts_without_claiming_employment(self):
        output = self.root / "draft.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(Job("Junior Python Developer", requirements=[Requirement("Python", "mandatory")]), self.profile, output)
        self.assertGreater(output.stat().st_size, 0)
        text = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertIn("Python", text); self.assertNotIn("professional employment", text.lower()); self.assertNotIn("React", text)

    def test_cv_respects_output_path_and_escapes_latex(self):
        profile_data = dict(self.profile.data)
        profile_data["identity"] = dict(profile_data["identity"], name="A&B_50%")
        profile_path = self.root / "escape-profile.json"
        profile_path.write_text(json.dumps(profile_data), encoding="utf-8")
        profile = load_profile(profile_path)
        output = self.root / "nested" / "custom.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(Job("C++ Developer", requirements=[Requirement("Python")]), profile, output)
        self.assertTrue(output.exists())
        tex = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertIn(r"A\&B\_50\%", tex)
        self.assertIn(r"\documentclass", tex)
        self.assertEqual(_escape_latex("A&B_50%"), r"A\&B\_50\%")

    def test_missing_pdflatex_is_clear(self):
        with patch("job_agent.cv.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pdflatex was not found on PATH"):
                generate(Job("Role"), self.profile, self.root / "missing.pdf")

    def test_pdflatex_failure_is_reported(self):
        failed = type("Result", (), {"returncode": 1, "stdout": "MiKTeX setup required\n", "stderr": ""})()
        output = self.root / "failed.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "LaTeX CV compilation failed: MiKTeX setup required"):
                generate(Job("Role"), self.profile, output)

    @unittest.skipUnless(pdflatex_usable(), "working pdflatex is not available")
    def test_cv_real_pdf_compilation(self):
        output = self.root / "real.pdf"
        generate(Job("Python Developer", requirements=[Requirement("Python")]), self.profile, output)
        self.assertGreater(output.stat().st_size, 0)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
        self.assertIn("Python", text)

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

    def test_versioned_cv_outputs_remain_independent(self):
        first = versioned_output_path(self.root, 7)
        second = versioned_output_path(self.root, 7)
        self.assertNotEqual(first, second)
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(Job("Python Developer", description="First version"), self.profile, first)
            first_tex = first.with_suffix(".tex").read_text(encoding="utf-8")
            generate(Job("Data Analyst", description="Second version"), self.profile, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(first.with_suffix(".tex").read_text(encoding="utf-8"), first_tex)
        self.assertNotEqual(
            first.with_suffix(".tex").read_text(encoding="utf-8"),
            second.with_suffix(".tex").read_text(encoding="utf-8"),
        )

    def test_structured_project_bullets_are_selected_deterministically(self):
        projects = {item["name"]: item for item in self.profile.data["projects"]}
        churn = projects[SAMPLE_PROJECT]
        self.assertEqual(len(churn["candidate_bullets"]), 6)
        self.assertEqual(len(churn["general_bullets"]), 3)
        selected = _select_bullets(churn, {"python"})
        self.assertEqual(selected, churn["candidate_bullets"][:3])
        self.assertLessEqual(len(selected), 3)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertIn("technical_practice", self.profile.data)
        self.assertIn("Python", self.profile.data["technical_practice"])
        self.assertNotIn("technical_practice", self.profile.data.get("rendered_sections", {}))

    def test_cv_bullets_fill_to_three_and_prefer_relevant_bullets(self):
        item = {
            "candidate_bullets": ["Unrelated A", "Built the Python pipeline.", "Unrelated B"],
            "general_bullets": ["General A", "General B", "General C"],
        }
        selected = _select_bullets(item, {"python"})
        self.assertEqual(selected, ["Built the Python pipeline.", "Unrelated A", "Unrelated B"])

        short = {
            "candidate_bullets": ["Only A", "Only B"],
            "general_bullets": ["Extra C", "Extra D"],
        }
        self.assertEqual(_select_bullets(short, {"python"}), ["Only A", "Only B", "Extra C"])

        two_total = {"candidate_bullets": ["Only A"], "general_bullets": ["Only B"]}
        self.assertEqual(_select_bullets(two_total, {"python"}), ["Only A", "Only B"])

    def test_cv_project_selection_uses_vacancy_evidence_and_ranks_projects(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "Frontend Showcase", "technologies": ["JavaScript"], "candidate_bullets": ["Built a browser interface."]},
            {"name": "Unrelated Name", "technologies": ["Python", "SQL"], "candidate_bullets": ["Built a Python data pipeline."]},
            {"name": "Model Notebook", "technologies": ["pandas", "scikit-learn"], "candidate_bullets": ["Compared forecasting models."]},
        ]
        data_job = Job("Data Analyst", requirements=[Requirement("Python", "mandatory"), Requirement("SQL", "preferred")], responsibilities="Build data pipelines with pandas.")
        selected, heading = _select_projects(data_job, data)
        self.assertEqual([project["name"] for project in selected], ["Unrelated Name", "Model Notebook", "Frontend Showcase"])
        self.assertEqual(heading, "Relevant projects")

        software_job = Job("Java Developer", requirements=[Requirement("Java", "mandatory")])
        software_data = dict(data)
        software_data["projects"] = [
            {"name": "Data Notebook", "technologies": ["Python", "pandas"]},
            {"name": "Backend Service", "technologies": ["Java", "Spring"]},
            {"name": "Frontend Showcase", "technologies": ["JavaScript"]},
        ]
        selected, heading = _select_projects(software_job, software_data)
        self.assertEqual([project["name"] for project in selected], ["Backend Service", "Data Notebook", "Frontend Showcase"])
        self.assertEqual(heading, "Relevant projects")

    def test_cv_project_selection_uses_text_without_technology_metadata(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "Unrelated", "description": "Built a Python data pipeline."},
            {"name": "Other", "candidate_bullets": ["Designed a static web page."]},
        ]
        selected, heading = _select_projects(Job("Python Developer", description="Python services"), data)
        self.assertEqual([project["name"] for project in selected], ["Unrelated", "Other"])
        self.assertEqual(heading, "Relevant projects")

    def test_cv_project_selection_uses_names_as_supplementary_evidence(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "Generic Work", "technologies": []},
            {"name": "Python Utilities", "technologies": []},
        ]
        selected, heading = _select_projects(Job("Python Developer", requirements=[Requirement("Python")]), data)
        self.assertEqual([project["name"] for project in selected], ["Python Utilities", "Generic Work"])
        self.assertEqual(heading, "Relevant projects")

    def test_cv_project_selection_normalizes_compound_learning_technology(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "Python Only", "technologies": ["Python"]},
            {"name": "Learned Models", "technologies": ["scikit-learn"]},
        ]
        selected, heading = _select_projects(Job("Machine Learning Engineer"), data)
        self.assertEqual([project["name"] for project in selected], ["Learned Models", "Python Only"])
        self.assertEqual(heading, "Relevant projects")

    def test_cv_project_selection_limits_entries_and_preserves_ties(self):
        data = dict(self.profile.data)
        data["thesis"] = {"name": "Thesis Entry", "technologies": [], "candidate_bullets": []}
        data["projects"] = [
            {"name": "First Python", "technologies": ["Python"]},
            {"name": "Second Python", "technologies": ["Python"]},
            {"name": "Third Python", "technologies": ["Python"]},
            {"name": "Fourth Python", "technologies": ["Python"]},
        ]
        job = Job("Python Developer", requirements=[Requirement("Python", "mandatory")])
        selected, heading = _select_projects(job, data)
        self.assertEqual([project["name"] for project in selected], ["First Python", "Second Python", "Third Python"])
        self.assertEqual(heading, "Relevant projects")

        profile_data = dict(data)
        profile_path = self.root / "selection-profile.json"
        profile_path.write_text(json.dumps(profile_data), encoding="utf-8")
        profile = load_profile(profile_path)
        output = self.root / "selected.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(job, profile, output)
        tex = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertEqual(tex.count("Thesis Entry"), 1)
        self.assertIn("First Python", tex)
        self.assertIn("Second Python", tex)
        self.assertIn("Third Python", tex)
        self.assertNotIn("Fourth Python", tex)

    def test_cv_project_selection_honors_profile_order_and_stronger_matches(self):
        data = dict(self.profile.data)
        data["thesis"] = {"name": "Thesis Entry", "technologies": ["Python"], "candidate_bullets": ["Explored a general computing topic."]}
        data["projects"] = [
            {"name": "House Pricing Prediction", "technologies": ["Python", "scikit-learn", "pandas"], "candidate_bullets": ["Built regression models."]},
            {"name": "Customer Churn Prediction Project", "technologies": ["Python", "scikit-learn", "pandas"], "candidate_bullets": ["Built classification models."]},
            {"name": "Movie Score Prediction", "technologies": ["Python", "scikit-learn", "pandas"], "candidate_bullets": ["Built regression models."]},
            {"name": "Job Searching Agent", "technologies": ["Python", "SQLite", "HTML", "JavaScript", "unittest"], "candidate_bullets": ["Built a local software application with automated tests."]},
        ]
        ml_job = Job("Machine Learning Engineer", requirements=[Requirement("Python", "mandatory"), Requirement("scikit-learn", "mandatory"), Requirement("pandas", "preferred")], description="Build machine learning models.")
        selected, heading = _select_projects(ml_job, data)
        self.assertEqual([project["name"] for project in selected], ["House Pricing Prediction", "Customer Churn Prediction Project", "Movie Score Prediction"])
        self.assertEqual(heading, "Relevant projects")

        title_only_job = Job("(Junior) Data Scientist (m/w/d) in Vollzeit oder Teilzeit")
        selected, heading = _select_projects(title_only_job, data)
        self.assertEqual([project["name"] for project in selected], ["House Pricing Prediction", "Customer Churn Prediction Project", "Movie Score Prediction"])
        self.assertEqual(heading, "Projects")

        software_job = Job(
            "Python Software Developer",
            requirements=[
                Requirement("Python", "mandatory"),
                Requirement("JavaScript", "mandatory"),
                Requirement("HTML", "mandatory"),
                Requirement("SQLite", "mandatory"),
                Requirement("unittest", "mandatory"),
            ],
            description="Build local software, HTML dashboards and SQLite storage with automated tests.",
        )
        selected, heading = _select_projects(software_job, data)
        self.assertEqual([project["name"] for project in selected], ["Job Searching Agent", "House Pricing Prediction", "Customer Churn Prediction Project"])
        self.assertEqual(heading, "Relevant projects")

        profile_path = self.root / "ordered-profile.json"
        profile_path.write_text(json.dumps(data), encoding="utf-8")
        profile = load_profile(profile_path)
        output = self.root / "ordered.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(software_job, profile, output)
        tex = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertLess(tex.index("Thesis Entry"), tex.index("Job Searching Agent"))
        self.assertEqual(tex.count("Thesis Entry"), 1)
        self.assertIn("House Pricing Prediction", tex)
        self.assertIn("Customer Churn Prediction Project", tex)
        self.assertNotIn("Movie Score Prediction", tex)

    def test_cv_project_selection_uses_technical_evidence_before_generic_description(self):
        data = dict(self.profile.data)
        data["thesis"] = {"name": "Thesis Entry", "technologies": ["Python", "SQL"], "candidate_bullets": ["Completed a general computing thesis."]}
        data["projects"] = [
            {
                "name": "House Pricing",
                "technologies": ["Python", "scikit-learn", "pandas"],
                "candidate_bullets": ["Built regression models.", "Evaluated feature engineering results."],
            },
            {
                "name": "Customer Churn",
                "technologies": ["Python", "scikit-learn", "pandas"],
                "candidate_bullets": ["Built classification models.", "Compared model validation results."],
            },
            {
                "name": "Movie Scoring",
                "technologies": ["Python", "scikit-learn", "pandas"],
                "candidate_bullets": ["Built regression models.", "Documented model metrics."],
            },
            {
                "name": "Job Searching Agent",
                "technologies": ["Python", "SQLite", "HTML", "JavaScript"],
                "candidate_bullets": [
                    "Built data storage and evaluation workflows.",
                    "Documented role requirements, qualifications, skills and results.",
                    "Built a location-aware application with generation workflows.",
                ],
            },
        ]
        job = Job(
            "Machine Learning Engineer",
            requirements=[Requirement("Python", "unknown"), Requirement("scikit-learn", "unknown")],
            description=(
                "Build machine learning models and data pipelines. Analyze data, evaluate models and "
                "document role requirements, qualifications, skills, results, evaluation and workflows "
                "for a remote application project."
            ),
        )

        selected, heading = _select_projects(job, data)
        self.assertEqual([project["name"] for project in selected], ["House Pricing", "Customer Churn", "Movie Scoring"])
        self.assertEqual(heading, "Relevant projects")

        profile_path = self.root / "technical-ranking-profile.json"
        profile_path.write_text(json.dumps(data), encoding="utf-8")
        profile = load_profile(profile_path)
        output = self.root / "technical-ranking.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(job, profile, output)
        tex = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertEqual(tex.count("Thesis Entry"), 1)
        self.assertLess(tex.index("Thesis Entry"), tex.index("House Pricing"))
        self.assertLess(tex.index("House Pricing"), tex.index("Customer Churn"))
        self.assertLess(tex.index("Customer Churn"), tex.index("Movie Scoring"))
        self.assertNotIn("Job Searching Agent", tex)

    def test_cv_project_selection_generic_service_overlap_keeps_profile_order(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "House Pricing Prediction", "technologies": ["Python"], "candidate_bullets": ["Built data models."]},
            {"name": "Customer Churn Prediction Project", "technologies": ["Python"], "candidate_bullets": ["Built data models and customer service."]},
            {"name": "Movie Score Prediction", "technologies": ["Python"], "candidate_bullets": ["Built data models."]},
            {"name": "Job Searching Agent", "technologies": ["Python"], "candidate_bullets": ["Built Python data services."]},
        ]
        selected, heading = _select_projects(
            Job("Data Scientist", description="Full-Service Python data science team."),
            data,
        )
        self.assertEqual(
            [project["name"] for project in selected],
            [
                "House Pricing Prediction",
                "Customer Churn Prediction Project",
                "Movie Score Prediction",
                "Job Searching Agent",
            ],
        )
        self.assertEqual(heading, "Relevant projects")

    def test_cv_project_selection_falls_back_deterministically_without_matches(self):
        data = dict(self.profile.data)
        data["thesis"] = None
        data["projects"] = [
            {"name": "Alpha", "technologies": ["Java"]},
            {"name": "Beta", "technologies": ["C++"]},
            {"name": "Gamma", "technologies": ["Go"]},
            {"name": "Delta", "technologies": ["Rust"]},
        ]
        selected, heading = _select_projects(Job("Excel Analyst", requirements=[Requirement("Excel")]), data)
        self.assertEqual([project["name"] for project in selected], ["Alpha", "Beta", "Gamma", "Delta"])
        self.assertEqual(heading, "Projects")

        data["projects"] = data["projects"][:2]
        selected, heading = _select_projects(Job("Excel Analyst", requirements=[Requirement("Excel")]), data)
        self.assertEqual([project["name"] for project in selected], ["Alpha", "Beta"])
        self.assertEqual(heading, "Projects")

    def test_cv_project_selection_tolerates_sparse_and_malformed_metadata(self):
        data = dict(self.profile.data)
        data["thesis"] = {"name": "Incomplete Thesis"}
        data["projects"] = [
            {"name": "Sparse"},
            {"name": "Malformed", "technologies": ["Python", None], "candidate_bullets": "One factual bullet.", "general_bullets": None},
            {"name": "Incomplete Thesis", "technologies": ["Python"]},
        ]
        job = Job("Python Developer", requirements=[Requirement("Python", "mandatory")])
        selected, heading = _select_projects(job, data)
        self.assertEqual([project["name"] for project in selected], ["Malformed", "Sparse"])
        self.assertEqual(heading, "Relevant projects")

        profile_path = self.root / "sparse-profile.json"
        profile_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "projects\\[1\\]\\.technologies"):
            load_profile(profile_path)
        profile = Profile(data)
        output = self.root / "sparse.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(job, profile, output)
        tex = output.with_suffix(".tex").read_text(encoding="utf-8")
        self.assertEqual(tex.count("Incomplete Thesis"), 1)
        self.assertIn("Malformed", tex)
        self.assertIn("Sparse", tex)

        data.pop("projects")
        selected, heading = _select_projects(job, data)
        self.assertEqual(selected, [])
        self.assertEqual(heading, "Projects")
        no_projects_path = self.root / "no-projects-profile.json"
        no_projects_path.write_text(json.dumps(data), encoding="utf-8")
        no_projects_profile = load_profile(no_projects_path)
        no_projects_output = self.root / "no-projects.pdf"
        with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_pdflatex):
            generate(job, no_projects_profile, no_projects_output)
        self.assertTrue(no_projects_output.with_suffix(".tex").exists())

    def test_external_data_needs_specific_approval_and_application_is_blocked(self):
        with self.assertRaises(PermissionDenied): require_external_approval(action="send_cv", destination="Example GmbH", data_summary="CV", approved=False)
        self.assertTrue(require_external_approval(action="send_cv", destination="Example GmbH", data_summary="CV", approved=True)["approved"])
        with self.assertRaises(PermissionDenied): require_external_approval(action="submit_application", destination="Example GmbH", data_summary="application", approved=True)


if __name__ == "__main__": unittest.main()
