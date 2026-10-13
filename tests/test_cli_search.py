import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_profile
from job_agent.profile import ValidationError, load_config
from job_agent.storage import Store


class CliSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.profile = write_profile(root)
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"target_roles": ["Python Developer"], "locations": ["Aachen"], "work_arrangements": ["remote"], "location_preferences": {"origin": "Aachen", "max_distance_km": 225, "remote_only_beyond_distance": True}, "search_queries": {"primary": ["Primary A", "Primary B"], "secondary": ["Secondary A"]}}), encoding="utf-8")
        self.database = root / "jobs.sqlite"
        self.stores = []

    def tearDown(self):
        self.directory.cleanup()

    def args(self, *extra):
        return ["--profile", str(self.profile), "--config", str(self.config), "--database", str(self.database), "search", *extra]

    def store(self, path):
        store = Store(path)
        self.stores.append(store)
        return store

    def test_default_search_orders_families_combines_and_deduplicates_by_identity(self):
        jobs = {
            "Primary A": [{"title": "Same title", "source": "adzuna", "external_job_id": "1"}],
            "Primary B": [{"title": "Same title", "source": "adzuna", "external_job_id": "1"}, {"title": "Other", "source": "adzuna", "external_job_id": "2"}],
            "Secondary A": [{"title": "Same title", "source": "other", "external_job_id": "3"}],
        }
        class FakeSource:
            def __init__(self, *_): self.calls = []
            def search(self, query, location=None): calls.append((query, location)); return jobs[query]
        calls = []
        output = StringIO()
        with patch("job_agent.cli.AdzunaSource", FakeSource), patch("job_agent.cli.Nomado24Source", FakeSource), patch("job_agent.cli.HimalayasSource", FakeSource), patch("job_agent.cli.BASource", FakeSource), patch("job_agent.cli.Store", side_effect=self.store), redirect_stdout(output):
            main(self.args("--location", "Aachen"))
        self.assertEqual(calls, [(query, location) for query in ("Primary A", "Primary B", "Secondary A") for location in ("Aachen", "Aachen", None, "Aachen")])
        reopened = Store(self.database)
        self.assertEqual(len(reopened.list_jobs()), 3)
        reopened.close()
        self.assertIn("Search complete.\nQueries searched: 12\nUnique jobs found: 3\nNew: 3\nKnown: 0\nExcluded: 0", output.getvalue())
        for store in self.stores: store.close()

    def test_manual_query_bypasses_configured_queries(self):
        calls = []
        class FakeSource:
            def __init__(self, *_): pass
            def search(self, query, location=None): calls.append((query, location)); return []
        output = StringIO()
        with patch("job_agent.cli.AdzunaSource", FakeSource), patch("job_agent.cli.Store", side_effect=self.store), redirect_stdout(output):
            main(self.args("--query", "Data Engineer", "--location", "Berlin"))
        self.assertEqual(calls, [("Data Engineer", "Berlin")])
        self.assertIn("Search complete.\nQueries searched: 1\nUnique jobs found: 0\nNew: 0\nKnown: 0\nExcluded: 0", output.getvalue())
        for store in self.stores: store.close()

    def test_source_limits_automatic_search_to_selected_adapter(self):
        calls = []
        class FakeSource:
            def __init__(self, *_): pass
            def search(self, query, location=None): calls.append((query, location)); return []
        output = StringIO()
        with patch("job_agent.cli.AdzunaSource", FakeSource), patch("job_agent.cli.Nomado24Source", FakeSource), patch("job_agent.cli.HimalayasSource", FakeSource), patch("job_agent.cli.BASource", FakeSource), patch("job_agent.cli.Store", side_effect=self.store), redirect_stdout(output):
            main(self.args("--source", "ba", "--location", "Aachen"))
        self.assertEqual(calls, [(query, "Aachen") for query in ("Primary A", "Primary B", "Secondary A")])
        self.assertIn("Queries searched: 3", output.getvalue())
        for store in self.stores: store.close()

    def test_source_limits_manual_query_to_selected_adapter(self):
        calls = []
        class FakeSource:
            def __init__(self, *_): pass
            def search(self, query, location=None): calls.append((query, location)); return []
        output = StringIO()
        with patch("job_agent.cli.AdzunaSource", FakeSource), patch("job_agent.cli.Nomado24Source", FakeSource), patch("job_agent.cli.HimalayasSource", FakeSource), patch("job_agent.cli.BASource", FakeSource), patch("job_agent.cli.Store", side_effect=self.store), redirect_stdout(output):
            main(self.args("--query", "Data Engineer", "--source", "himalayas"))
        self.assertEqual(calls, [("Data Engineer", None)])
        self.assertIn("Queries searched: 1", output.getvalue())
        for store in self.stores: store.close()

    def test_invalid_search_queries_are_rejected(self):
        path = Path(self.directory.name) / "bad.json"
        config = {"target_roles": [], "locations": [], "work_arrangements": [], "location_preferences": {"origin": "Aachen", "max_distance_km": 225, "remote_only_beyond_distance": True}, "search_queries": {"primary": [""], "secondary": []}}
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaises(ValidationError):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
