"""The shipped example files must stay valid so a fresh clone has a working setup path."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.cv import generate
from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.profile import load_config, load_profile
from job_agent.normalizer import normalize
from job_agent.storage import Store

PROFILE_EXAMPLE = Path("data/profile.example.json")
CONFIG_EXAMPLE = Path("data/search_config.example.json")


class ExampleFilesTests(unittest.TestCase):
    def test_example_files_load_with_the_application_loaders(self):
        profile = load_profile(PROFILE_EXAMPLE)
        config = load_config(CONFIG_EXAMPLE)
        self.assertFalse(profile.data["professional_experience"])
        self.assertTrue(profile.skills)
        self.assertTrue(config["target_roles"])
        self.assertTrue(config["search_queries"]["primary"])
        self.assertTrue(config["search_queries"]["secondary"])
        self.assertIn("origin", config["location_preferences"])

    def test_example_profile_can_generate_a_cv_draft(self):
        profile = load_profile(PROFILE_EXAMPLE)

        def fake_compile(command, cwd, **kwargs):
            (Path(cwd) / "resume.pdf").write_bytes(b"fake pdf")
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cv.pdf"
            with patch("job_agent.cv.shutil.which", return_value="pdflatex"), patch("job_agent.cv.subprocess.run", side_effect=fake_compile):
                path, facts = generate(Job("Python Developer", requirements=[Requirement("Python")]), profile, output)
            self.assertTrue(path.exists())
            self.assertTrue(output.with_suffix(".tex").exists())
            self.assertIn(profile.data["identity"]["name"], output.with_suffix(".tex").read_text(encoding="utf-8"))
            self.assertTrue(facts)

    def test_example_config_drives_evaluation_and_storage(self):
        profile = load_profile(PROFILE_EXAMPLE)
        config = load_config(CONFIG_EXAMPLE)
        job = normalize({"title": config["target_roles"][0], "source": "example", "external_job_id": "example-1", "location": config["locations"][0]})
        evaluation = evaluate(job, profile, config)
        self.assertIsInstance(evaluation.score, int)
        self.assertIn(evaluation.assessment, {"recommended", "borderline", "rejected"})
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "jobs.sqlite") as store:
                job_id, created = store.save_job(job, evaluation.to_dict())
                self.assertTrue(created)
                rows = store.list_jobs()
                self.assertEqual([row["id"] for row in rows], [job_id])
                self.assertEqual(json.loads(rows[0]["payload"])["source"], "example")


if __name__ == "__main__":
    unittest.main()
