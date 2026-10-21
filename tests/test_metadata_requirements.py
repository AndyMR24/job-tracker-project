"""Nomado24 technology tags are used only for exact matches against known skills."""
import unittest

from job_agent.evaluator import evaluate
from job_agent.normalizer import normalize
from job_agent.profile import Profile

try:
    from support import sample_config, sample_profile
except ImportError:  # pragma: no cover
    from tests.support import sample_config, sample_profile


class MetadataRequirementTests(unittest.TestCase):
    def setUp(self):
        profile_data = sample_profile()
        profile_data["skills"] = [
            {"name": name, "evidence": "Synthetic evidence used by the test suite."}
            for name in ("Python", "Django", "FastAPI", "SQL")
        ]
        self.profile = Profile(profile_data)
        self.config = sample_config()

    def normalize(self, role, **values):
        raw = {"title": role, **values}
        raw["known_requirement_terms"] = [skill["name"] for skill in self.profile.data["skills"]]
        return normalize(raw)

    def test_python_and_fastapi_are_detected_in_description(self):
        job = self.normalize("Junior Backend Developer", description="Build services with Python and FastAPI.")
        self.assertEqual([(item.text, item.kind) for item in job.requirements], [("Python", "unknown"), ("FastAPI", "unknown")])
        result = evaluate(job, self.profile, self.config)
        self.assertIn("Confirmed skill: Python.", result.strong_matches)
        self.assertIn("Confirmed skill: FastAPI.", result.strong_matches)

    def test_nomado24_tags_detect_known_python_and_django_skills(self):
        job = self.normalize(
            "Backend Developer",
            source="nomado24",
            metadata={"tags": ["Python", "Django"]},
        )
        self.assertEqual([(item.text, item.kind) for item in job.requirements], [("Python", "unknown"), ("Django", "unknown")])
        result = evaluate(job, self.profile, self.config)
        self.assertIn("Confirmed skill: Python.", result.strong_matches)
        self.assertIn("Confirmed skill: Django.", result.strong_matches)

    def test_description_and_tags_do_not_duplicate_a_requirement(self):
        job = self.normalize(
            "Backend Developer",
            source="nomado24",
            description="Build services with Python.",
            metadata={"tags": ["Python"]},
        )
        self.assertEqual([(item.text, item.kind) for item in job.requirements], [("Python", "unknown")])
        result = evaluate(job, self.profile, self.config)
        self.assertEqual(result.strong_matches.count("Confirmed skill: Python."), 1)

    def test_explicit_requirements_are_not_duplicated_by_tags(self):
        job = self.normalize(
            "Backend Developer",
            source="nomado24",
            requirements=[{"text": "Python", "kind": "preferred"}],
            metadata={"tags": ["Python", "Django"]},
        )
        self.assertEqual(
            [(item.text, item.kind) for item in job.requirements],
            [("Python", "preferred"), ("Django", "unknown")],
        )

    def test_generic_tags_require_an_exact_known_skill_match(self):
        job = self.normalize(
            "Backend Developer",
            source="nomado24",
            metadata={"tags": ["Engineering", "Software Development"]},
        )
        self.assertEqual(job.requirements, [])

        raw = {
            "title": "Backend Developer",
            "source": "nomado24",
            "metadata": {"tags": ["Engineering"]},
            "known_requirement_terms": ["Engineering"],
        }
        engineering = normalize(raw)
        self.assertEqual([(item.text, item.kind) for item in engineering.requirements], [("Engineering", "unknown")])

    def test_unknown_vocabulary_is_not_invented_from_tags(self):
        raw = {
            "title": "Backend Developer",
            "source": "nomado24",
            "metadata": {"tags": ["FastAPI"]},
            "known_requirement_terms": ["Python"],
        }
        self.assertEqual(normalize(raw).requirements, [])

    def test_malformed_tags_are_ignored(self):
        malformed = (None, {"Python": True}, [["Python"]], ["Python", None], [123], "Python")
        for tags in malformed:
            with self.subTest(tags=tags):
                raw = {
                    "title": "Backend Developer",
                    "source": "nomado24",
                    "metadata": {"tags": tags},
                    "known_requirement_terms": ["Python"],
                }
                self.assertEqual(normalize(raw).requirements, [])

    def test_other_source_metadata_tags_are_not_treated_as_technology_tags(self):
        raw = {
            "title": "Backend Developer",
            "source": "adzuna",
            "metadata": {"tags": ["Python"]},
            "known_requirement_terms": ["Python"],
        }
        self.assertEqual(normalize(raw).requirements, [])

    def test_seniority_exclusion_still_takes_precedence(self):
        job = self.normalize(
            "Senior Backend Developer",
            source="nomado24",
            metadata={"tags": ["Python"]},
        )
        result = evaluate(job, self.profile, self.config)
        self.assertTrue(result.excluded)
        self.assertTrue(any("senior-level" in concern for concern in result.concerns))

    def test_missing_mandatory_skill_remains_uncertain(self):
        job = self.normalize(
            "Backend Developer",
            source="nomado24",
            requirements=[{"text": "Kubernetes", "kind": "mandatory"}],
            metadata={"tags": ["Python"]},
        )
        result = evaluate(job, self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertIn(
            "Mandatory requirement could not be verified from the profile: Kubernetes.",
            result.uncertainties,
        )


if __name__ == "__main__":
    unittest.main()
