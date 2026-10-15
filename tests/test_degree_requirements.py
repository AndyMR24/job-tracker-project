"""Degree requirements are compared with the candidate's highest completed degree.

The profile is the only source of candidate education. A level the application does not recognize
means "unknown", and unknown must never become a degree penalty or an exclusion: the job stays
eligible on that dimension and the uncertainty is recorded instead.
"""
import json
import unittest
from pathlib import Path

from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.profile import Profile, degree_meets

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import sample_config, sample_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import sample_config, sample_profile

BASELINE = Path(__file__).with_name("evaluation_baseline.json")

MASTER_REQUIRED = [Requirement("Master's degree", "mandatory")]
MASTER_MENTIONED = [Requirement("Master's degree", "preferred")]

BACHELOR = {"level": "bachelor", "degree": "BSc", "institution": "Example", "period": "2019-2025", "detail": ""}
MASTER = {"level": "master", "degree": "MSc", "institution": "Example", "period": "2025-2027", "detail": ""}
DOCTORATE = {"level": "doctorate", "degree": "PhD", "institution": "Example", "period": "2027-2031", "detail": ""}
COURSE = {"level": "additional education", "degree": "Course", "institution": "Example", "period": "2018", "detail": ""}


def profile_with(*entries) -> Profile:
    """A sample profile whose education list is replaced by the given entries."""
    return Profile({**sample_profile(), "education": list(entries)})


class DegreeLevelTests(unittest.TestCase):
    def test_the_highest_recognized_level_wins_regardless_of_order(self):
        self.assertEqual(profile_with(COURSE, MASTER, BACHELOR).degree_level, "master")
        self.assertEqual(profile_with(BACHELOR, COURSE).degree_level, "bachelor")
        self.assertEqual(profile_with(BACHELOR, DOCTORATE).degree_level, "doctorate")

    def test_levels_are_normalized_before_comparison(self):
        self.assertEqual(profile_with({"level": " Master "}).degree_level, "master")

    def test_unrecognized_or_missing_levels_are_unknown(self):
        self.assertIsNone(profile_with(COURSE).degree_level)
        self.assertIsNone(profile_with({"degree": "No level recorded"}).degree_level)
        self.assertIsNone(profile_with({}).degree_level)
        self.assertIsNone(profile_with().degree_level)

    def test_degree_meets_compares_known_levels_only(self):
        self.assertFalse(degree_meets("bachelor", "master"))
        self.assertTrue(degree_meets("master", "master"))
        self.assertTrue(degree_meets("doctorate", "master"))
        self.assertIsNone(degree_meets(None, "master"))
        self.assertIsNone(degree_meets("additional education", "master"))


class DegreeRequirementTests(unittest.TestCase):
    def setUp(self):
        self.config = sample_config()

    def evaluate(self, profile, requirements=MASTER_REQUIRED, **evaluation):
        config = dict(self.config, evaluation=evaluation) if evaluation else self.config
        return evaluate(Job("Data Analyst", requirements=list(requirements)), profile, config)

    def test_a_known_bachelor_keeps_the_existing_penalty_and_exclusion(self):
        bachelor = self.evaluate(profile_with(BACHELOR))
        master = self.evaluate(profile_with(MASTER))
        self.assertTrue(bachelor.excluded)
        self.assertEqual(bachelor.assessment, "rejected")
        self.assertEqual(bachelor.score, master.score - 50)
        self.assertIn("A Master's degree is explicitly required; the profile records a Bachelor's degree.", bachelor.concerns)

    def test_a_known_master_or_doctorate_satisfies_the_requirement(self):
        scores = []
        for entry in (MASTER, DOCTORATE):
            with self.subTest(level=entry["level"]):
                result = self.evaluate(profile_with(entry))
                scores.append(result.score)
                self.assertFalse(result.excluded)
                self.assertNotEqual(result.assessment, "rejected")
                self.assertTrue(any("A Master's degree is required and the profile records" in item for item in result.strong_matches))
                self.assertFalse([item for item in result.concerns + result.potential_gaps if "Master" in item])
                self.assertEqual(result.score, self.evaluate(profile_with(entry), weights={"degree_required_penalty": 100}).score)
        self.assertEqual(scores[0], scores[1], "a doctorate must not score differently from a master's for a master's requirement")

    def test_an_unknown_degree_is_not_excluded_and_not_penalized(self):
        unknown = self.evaluate(profile_with(COURSE))
        master = self.evaluate(profile_with(MASTER))
        self.assertFalse(unknown.excluded)
        self.assertNotEqual(unknown.assessment, "rejected")
        self.assertEqual(unknown.score, master.score)
        self.assertTrue(any("not recognized" in item for item in unknown.uncertainties))
        self.assertFalse([item for item in unknown.concerns + unknown.potential_gaps if "Master" in item])
        self.assertNotIn("Bachelor", " ".join(unknown.concerns + unknown.potential_gaps + unknown.uncertainties))

    def test_a_missing_level_key_is_treated_as_unknown(self):
        result = self.evaluate(profile_with({"degree": "No level recorded"}))
        self.assertFalse(result.excluded)
        self.assertTrue(any("not recognized" in item for item in result.uncertainties))

    def test_a_known_insufficient_degree_still_follows_the_configured_penalty(self):
        zeroed = self.evaluate(profile_with(BACHELOR), weights={"degree_required_penalty": 0})
        self.assertTrue(zeroed.excluded)
        self.assertEqual(zeroed.assessment, "rejected")
        self.assertEqual(zeroed.score, self.evaluate(profile_with(MASTER)).score)

    def test_a_mentioned_requirement_penalizes_only_a_known_insufficient_degree(self):
        bachelor = self.evaluate(profile_with(BACHELOR), MASTER_MENTIONED)
        master = self.evaluate(profile_with(MASTER), MASTER_MENTIONED)
        unknown = self.evaluate(profile_with(COURSE), MASTER_MENTIONED)
        self.assertEqual(bachelor.score, master.score - 10)
        self.assertIn("A Master's degree is mentioned but the profile records a Bachelor's degree.", bachelor.potential_gaps)
        self.assertEqual(unknown.score, master.score)
        self.assertEqual(unknown.potential_gaps, [])
        self.assertTrue(any("not recognized" in item for item in unknown.uncertainties))

    def test_the_current_profile_output_is_unchanged(self):
        baseline = {case["case"]: case["evaluation"] for case in json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]}
        live = evaluate(Job("Data Analyst", requirements=list(MASTER_REQUIRED)), Profile(sample_profile()), self.config)
        self.assertEqual(live.to_dict(), baseline["mandatory master excluded"])


if __name__ == "__main__":
    unittest.main()
