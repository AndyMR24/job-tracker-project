"""Country eligibility remains separate from office location and remote-work details."""
import json
import tempfile
import unittest
from pathlib import Path

from job_agent.location import EligibilityStatus, resolve_eligibility
from job_agent.normalizer import normalize
from job_agent.storage import Store


class RemoteEligibilityPersistenceTests(unittest.TestCase):
    def test_restriction_metadata_survives_normalization_and_storage(self):
        raw = {
            "title": "Backend Developer",
            "source": "himalayas",
            "source_url": "https://example.test/eligibility",
            "external_job_id": "eligibility-1",
            "arrangement": "remote",
            "metadata": {
                "location_restrictions": ["France"],
                "timezone_restrictions": ["CET"],
                "company_country": "France",
            },
        }
        job = normalize(raw)
        self.assertEqual(resolve_eligibility(job.metadata, "Germany").status, EligibilityStatus.RESTRICTED)

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "jobs.sqlite")
            try:
                job_id, _ = store.save_job(job, {"score": 50, "assessment": "borderline", "excluded": False})
                stored_payload = store.connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()["payload"]
                stored = json.loads(stored_payload)
            finally:
                store.close()

        self.assertEqual(stored["metadata"]["location_restrictions"], ["France"])
        self.assertEqual(stored["metadata"]["timezone_restrictions"], ["CET"])
        self.assertEqual(stored["metadata"]["company_country"], "France")


if __name__ == "__main__":
    unittest.main()
