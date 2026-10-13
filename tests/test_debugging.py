import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.adzuna import AdzunaSource
from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.normalizer import normalize
from job_agent.profile import load_config, load_profile
from job_agent.storage import Store


try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile  # noqa: F401
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile  # noqa: F401


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode()


class DebuggingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.profile = load_profile(write_profile(cls.directory.name))
        cls.config = load_config(write_config(cls.directory.name))

    def test_multiword_data_analyst_query_reaches_adzuna_without_special_case(self):
        payload = {"results": [{"id": "a1", "title": "Junior Data Analyst", "description": "SQL"}]}
        with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=True), patch("job_agent.adzuna.urllib.request.urlopen", return_value=Response(payload)) as mocked:
            jobs = AdzunaSource(Path(tempfile.mktemp())).search("junior data analyst")
        self.assertEqual(jobs[0]["title"], "Junior Data Analyst")
        self.assertIn("what=junior+data+analyst", mocked.call_args.args[0].full_url)

    def test_sparse_adzuna_listing_reports_uncertainty(self):
        job = Job("Junior Python Developer", requirements=[Requirement("Python")], metadata={"description_is_snippet": True})
        result = evaluate(job, self.profile, self.config)
        self.assertTrue(result.uncertainties)
        self.assertTrue(any("snippet" in item.lower() for item in result.uncertainties))
        self.assertLess(result.score, 90)

    def test_senior_titles_are_excluded_and_hidden_from_default_list(self):
        senior_titles = ["Senior Python Developer", "Senior Data Scientist", "Lead Data Analyst", "Principal Machine Learning Engineer", "Staff Software Engineer"]
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "jobs.sqlite")
            for index, title in enumerate(senior_titles):
                job = normalize({"title": title, "source_url": f"https://example.test/{index}"})
                result = evaluate(job, self.profile, self.config)
                self.assertTrue(result.excluded, title)
                store.save_job(job, result.to_dict())
            self.assertEqual(store.list_jobs(include_rejected=False), [])
            self.assertEqual(len(store.list_jobs(include_rejected=True)), len(senior_titles))
            store.close()

    def test_early_career_titles_remain_eligible(self):
        titles = ["Junior Python Developer", "Junior Data Analyst", "Junior Data Scientist", "Graduate Data Scientist", "Associate Data Scientist", "Entry-Level Python Developer"]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(evaluate(normalize({"title": title}), self.profile, self.config).excluded)
        self.assertFalse(evaluate(normalize({"title": "Seniority Analyst"}), self.profile, self.config).excluded)


if __name__ == "__main__": unittest.main()


