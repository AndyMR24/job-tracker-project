"""A requirement the profile does not list is unknown, not a confirmed gap.

The profile is not an exhaustive list of what the candidate knows, so an unlisted requirement is
recorded as unverified and left for manual review instead of being scored as missing. Degree and
years-of-experience requirements keep their own rules, and listed skills keep their bonus.
"""
import json
import unittest
from pathlib import Path

from job_agent.evaluator import DEFAULT_EVALUATION_SETTINGS, evaluate
from job_agent.models import Job, Requirement
from job_agent.profile import Profile

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import sample_config, sample_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import sample_config, sample_profile

BASELINE = Path(__file__).with_name("evaluation_baseline.json")

BASE = DEFAULT_EVALUATION_SETTINGS["base_score"]
ROLE = DEFAULT_EVALUATION_SETTINGS["weights"]["target_role"]
SKILL = DEFAULT_EVALUATION_SETTINGS["weights"]["confirmed_skill"]
DEGREE_PENALTY = DEFAULT_EVALUATION_SETTINGS["weights"]["degree_required_penalty"]
EXPERIENCE_PENALTY = DEFAULT_EVALUATION_SETTINGS["weights"]["experience_requirement"]["mandatory"]
LANGUAGE_TIER = DEFAULT_EVALUATION_SETTINGS["weights"]["preferred_language"]["requirement"]


class UnverifiedRequirementTests(unittest.TestCase):
    """`Requirement` carries text, a kind and a category that is always "skill" today, so a skill and
    a generic requirement cannot be told apart: every unlisted requirement is treated as unknown."""

    def setUp(self):
        self.profile = Profile(sample_profile())
        self.config = sample_config()

    def evaluate(self, requirements, **evaluation):
        config = dict(self.config, evaluation=evaluation) if evaluation else self.config
        return evaluate(Job("Data Analyst", requirements=list(requirements)), self.profile, config)

    def test_listed_skills_keep_their_positive_scoring(self):
        mandatory = self.evaluate([Requirement("Python", "mandatory")])
        preferred = self.evaluate([Requirement("SQL", "preferred")])
        self.assertEqual(mandatory.score, BASE + ROLE + SKILL["mandatory"] + LANGUAGE_TIER)
        self.assertEqual(preferred.score, BASE + ROLE + SKILL["other"])
        self.assertIn("Confirmed skill: Python.", mandatory.strong_matches)
        self.assertIn("Confirmed skill: SQL.", preferred.strong_matches)

    def test_unlisted_mandatory_requirement_is_unverified_without_a_penalty(self):
        result = self.evaluate([Requirement("Kubernetes", "mandatory")])
        self.assertEqual(result.score, BASE + ROLE)
        self.assertEqual(result.potential_gaps, [])
        self.assertIn("Mandatory requirement could not be verified from the profile: Kubernetes.", result.uncertainties)
        self.assertFalse(any("Kubernetes" in item for item in result.concerns))

    def test_unlisted_preferred_and_useful_requirements_are_unverified_without_a_penalty(self):
        for kind, label in (("preferred", "Preferred"), ("useful", "Useful")):
            with self.subTest(kind=kind):
                result = self.evaluate([Requirement("Kubernetes", kind)])
                self.assertEqual(result.score, BASE + ROLE)
                self.assertEqual(result.potential_gaps, [])
                self.assertIn(f"{label} requirement could not be verified from the profile: Kubernetes.", result.uncertainties)

    def test_an_unknown_kind_keeps_its_existing_review_message(self):
        result = self.evaluate([Requirement("Tableau")])
        self.assertEqual(result.score, BASE + ROLE)
        self.assertIn("Requirement needs review: Tableau.", result.uncertainties)

    def test_the_missing_requirement_weights_are_no_longer_applied(self):
        for kind in ("mandatory", "preferred", "useful"):
            with self.subTest(kind=kind):
                raised = self.evaluate([Requirement("Kubernetes", kind)], weights={"missing_requirement": {kind: 100}})
                self.assertEqual(raised.score, BASE + ROLE)

    def test_unlisted_requirements_are_not_scored_at_all(self):
        with_requirement = self.evaluate([Requirement("Kubernetes", "mandatory")])
        without_requirements = self.evaluate([])
        self.assertEqual(with_requirement.score, without_requirements.score + DEFAULT_EVALUATION_SETTINGS["weights"]["no_requirements"])

    def test_a_known_missing_degree_still_excludes_and_penalizes(self):
        result = self.evaluate([Requirement("Masters degree", "mandatory")])
        self.assertTrue(result.excluded)
        self.assertEqual(result.score, BASE + ROLE - DEGREE_PENALTY)
        self.assertTrue(any("Master's degree is explicitly required" in item for item in result.concerns))

    def test_confirmed_absent_experience_still_penalizes(self):
        result = self.evaluate([Requirement("5 years of experience", "mandatory")])
        self.assertFalse(result.excluded)
        self.assertEqual(result.score, BASE + ROLE - EXPERIENCE_PENALTY)
        self.assertIn("Professional-experience requirement is not satisfied by projects or thesis work.", result.concerns)

    def test_the_two_updated_baseline_cases_show_the_deliberate_change(self):
        baseline = {case["case"]: case["evaluation"] for case in json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]}
        mandatory = self.evaluate([Requirement("Python", "mandatory"), Requirement("Kubernetes", "mandatory")])
        self.assertEqual(mandatory.score, BASE + ROLE + SKILL["mandatory"] + LANGUAGE_TIER)
        self.assertEqual(mandatory.to_dict(), baseline["missing mandatory requirement"])
        self.assertEqual(mandatory.potential_gaps, [])
        self.assertTrue(any("Kubernetes" in item for item in mandatory.uncertainties))


if __name__ == "__main__":
    unittest.main()
