import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.adzuna import AdzunaError, AdzunaSource
from job_agent.storage import Store


class FakeResponse:
    def __init__(self, payload, status=200, content_type="application/json"):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode("utf-8")


class AdzunaTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "id": 5818515565,
            "title": "Lead Developer (m/w/d) Python",
            "description": "Python 3.13, AWS and Terraform experience.",
            "redirect_url": "https://www.adzuna.de/details/5818515565",
            "created": "2026-07-28T17:39:52Z",
            "contract_time": "full_time",
            "salary_min": 50000,
            "salary_max": 70000,
            "salary_is_predicted": 0,
            "company": {"display_name": "Talent Tree"},
            "location": {"display_name": "Bickendorf, Köln"},
            "category": {"label": "IT-Stellen", "tag": "it-jobs"},
        }

    def source(self):
        return AdzunaSource(Path(tempfile.mktemp()))

    def test_successful_mapping_and_public_request_parameters(self):
        with patch.dict("os.environ", {"ADZUNA_APP_ID": "id-value", "ADZUNA_APP_KEY": "key-value"}, clear=True):
            with patch("job_agent.adzuna.urllib.request.urlopen", return_value=FakeResponse({"count": 1, "results": [self.job]})) as mocked:
                jobs = self.source().search("Python", "Köln", results_per_page=1)
        self.assertEqual(len(jobs), 1)
        mapped = jobs[0]
        self.assertEqual(mapped["external_job_id"], "5818515565")
        self.assertEqual(mapped["source"], "adzuna")
        self.assertEqual(mapped["title"], self.job["title"])
        self.assertEqual(mapped["company"], "Talent Tree")
        self.assertEqual(mapped["location"], "Bickendorf, Köln")
        self.assertEqual(mapped["source_url"], self.job["redirect_url"])
        self.assertEqual(mapped["employment_type"], "full_time")
        self.assertEqual(mapped["salary"], "50000-70000")
        self.assertEqual(mapped["metadata"]["category"]["tag"], "it-jobs")
        request_url = mocked.call_args.args[0].full_url
        self.assertIn("what=Python", request_url)
        self.assertIn("where=K%C3%B6ln", request_url)
        self.assertNotIn("Andr", request_url)
        self.assertNotIn("hotmail", request_url)

    def test_missing_optional_fields_remain_unknown(self):
        minimal = {"id": "x1", "title": "Python developer"}
        with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=True), patch("job_agent.adzuna.urllib.request.urlopen", return_value=FakeResponse({"results": [minimal]})):
            mapped = self.source().search("Python")[0]
        self.assertIsNone(mapped["company"]); self.assertIsNone(mapped["location"]); self.assertIsNone(mapped["salary"]); self.assertIsNone(mapped["employment_type"]); self.assertEqual(mapped["metadata"]["category"], {})

    def test_empty_results(self):
        with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=True), patch("job_agent.adzuna.urllib.request.urlopen", return_value=FakeResponse({"count": 0, "results": []})):
            self.assertEqual(self.source().search("Python"), [])

    def test_missing_credentials_and_invalid_response(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AdzunaError): self.source()
        with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=True), patch("job_agent.adzuna.urllib.request.urlopen", return_value=FakeResponse({"unexpected": []})):
            with self.assertRaises(AdzunaError): self.source().search("Python")

    def test_repeated_adzuna_job_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "jobs.sqlite")
            with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=True), patch("job_agent.adzuna.urllib.request.urlopen", return_value=FakeResponse({"results": [self.job]})):
                mapped = self.source().search("Python")[0]
            first = store.save_job(__import__("job_agent.normalizer", fromlist=["normalize"]).normalize(mapped), {"score": 50})
            second = store.save_job(__import__("job_agent.normalizer", fromlist=["normalize"]).normalize(mapped), {"score": 50})
            self.assertTrue(first[1]); self.assertFalse(second[1]); self.assertEqual(len(store.list_jobs()), 1)
            store.close()


if __name__ == "__main__": unittest.main()
