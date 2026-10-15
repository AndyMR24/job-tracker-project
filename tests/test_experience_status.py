"""Professional experience is true, false or unknown: the profile is the only source of this fact.

A missing status never becomes an assumed disqualification, and recorded experience is not evidence
of a particular number of years. The current sample profile records `false`, so every confirmed
absence path must keep its previous score and wording.
"""
import json
import tempfile
import unittest
from pathlib import Path

from job_agent.evaluator import evaluate
from job_agent.models import Job, Requirement
from job_agent.profile import Profile, ValidationError, load_profile

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import sample_config, sample_profile, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import sample_config, sample_profile, write_profile

BASELINE = Path(__file__).with_name("evaluation_baseline.json")

SENIOR_TITLE = "Senior Data Analyst"
JUNIOR_TITLE = "Junior Data Analyst"
YEARS_REQUIRED = [Requirement("5 years of experience", "mandatory")]
YEARS_PREFERRED = [Requirement("3 years of experience", "preferred")]

EARLY_CAREER_MESSAGE = "Seniority appears compatible with an early-career search."
SENIOR_CONCERN = "The posting is explicitly senior-level while the profile has no professional employment experience."
YEARS_CONCERN = "Professional-experience requirement is not satisfied by projects or thesis work."

ABSENT = object()  # sentinel for "the profile does not carry the key at all"


def profile_with(value=ABSENT) -> Profile:
    """A sample profile whose professional-experience status is the given value."""
    data = dict(sample_profile())
    if value is ABSENT:
        data.pop("professional_experience")
    else:
        data["professional_experience"] = value
    return Profile(data)


class ProfileValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def load(self, data):
        return load_profile(write_profile(self.directory.name, data))

    def test_true_false_and_null_are_accepted(self):
        for value, expected in ((True, True), (False, False), (None, None)):
            with self.subTest(value=value):
                profile = self.load({**sample_profile(), "professional_experience": value})
                self.assertIs(profile.has_professional_experience, expected)

    def test_an_absent_key_means_unknown(self):
        data = dict(sample_profile())
        data.pop("professional_experience")
        self.assertIsNone(self.load(data).has_professional_experience)

    def test_existing_profiles_that_record_false_still_load(self):
        self.assertIs(self.load({**sample_profile(), "professional_experience": False}).has_professional_experience, False)

    def test_invalid_values_are_rejected_without_coercion(self):
        for value in ("yes", "true", "false", 1, 0, 0.0, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.load({**sample_profile(), "professional_experience": value})


class AccessorTests(unittest.TestCase):
    def test_the_accessor_reports_all_three_states(self):
        self.assertIs(profile_with(False).has_professional_experience, False)
        self.assertIs(profile_with(True).has_professional_experience, True)
        self.assertIsNone(profile_with(None).has_professional_experience)
        self.assertIsNone(profile_with(ABSENT).has_professional_experience)


class SeniorRoleTests(unittest.TestCase):
    def setUp(self):
        self.config = sample_config()

    def evaluate(self, profile, title=SENIOR_TITLE, requirements=(), **evaluation):
        config = dict(self.config, evaluation=evaluation) if evaluation else self.config
        return evaluate(Job(title, requirements=list(requirements)), profile, config)

    def test_confirmed_absence_keeps_the_existing_exclusion_exactly(self):
        none_recorded = self.evaluate(profile_with(False))
        experience_recorded = self.evaluate(profile_with(True))
        self.assertTrue(none_recorded.excluded)
        self.assertEqual(none_recorded.assessment, "rejected")
        self.assertEqual(none_recorded.score, experience_recorded.score - 45)
        self.assertIn(SENIOR_CONCERN, none_recorded.concerns)
        self.assertNotIn(SENIOR_CONCERN, experience_recorded.concerns + experience_recorded.uncertainties)

    def test_recorded_experience_is_a_match_without_penalty_or_exclusion(self):
        result = self.evaluate(profile_with(True))
        self.assertFalse(result.excluded)
        self.assertNotEqual(result.assessment, "rejected")
        self.assertIn("The posting is explicitly senior-level and the profile records professional experience.", result.strong_matches)
        self.assertEqual(result.score, self.evaluate(profile_with(True), title=JUNIOR_TITLE).score)

    def test_unknown_status_is_not_excluded_and_not_penalized(self):
        for profile in (profile_with(None), profile_with(ABSENT)):
            with self.subTest(state=profile.data.get("professional_experience", "absent")):
                result = self.evaluate(profile)
                self.assertFalse(result.excluded)
                self.assertNotEqual(result.assessment, "rejected")
                self.assertEqual(result.score, self.evaluate(profile_with(True)).score)
                self.assertTrue(any("does not record whether the candidate has professional experience" in item for item in result.uncertainties))
                self.assertNotIn(SENIOR_CONCERN, result.concerns + result.uncertainties)

    def test_the_senior_penalty_weight_only_applies_to_confirmed_absence(self):
        for profile in (profile_with(True), profile_with(None)):
            with self.subTest(state=profile.data.get("professional_experience")):
                self.assertEqual(self.evaluate(profile, weights={"senior_penalty": 100}).score, self.evaluate(profile).score)


class EarlyCareerMessageTests(unittest.TestCase):
    def setUp(self):
        self.config = sample_config()

    def evaluate(self, profile):
        return evaluate(Job(JUNIOR_TITLE), profile, self.config)

    def test_the_current_message_is_kept_for_confirmed_absence(self):
        self.assertIn(EARLY_CAREER_MESSAGE, self.evaluate(profile_with(False)).strong_matches)

    def test_recorded_experience_uses_neutral_wording(self):
        result = self.evaluate(profile_with(True))
        self.assertNotIn(EARLY_CAREER_MESSAGE, result.strong_matches)
        self.assertIn("Seniority wording is compatible with the profile's recorded professional experience.", result.strong_matches)

    def test_unknown_status_makes_no_early_career_claim(self):
        for profile in (profile_with(None), profile_with(ABSENT)):
            with self.subTest(state=profile.data.get("professional_experience", "absent")):
                result = self.evaluate(profile)
                self.assertNotIn(EARLY_CAREER_MESSAGE, result.strong_matches)
                self.assertTrue(any("does not record whether the candidate has professional experience" in item for item in result.uncertainties))

    def test_the_status_never_changes_the_score_of_an_early_career_title(self):
        self.assertEqual({self.evaluate(profile_with(value)).score for value in (False, True, None)}, {60})


class YearsOfExperienceTests(unittest.TestCase):
    def setUp(self):
        self.config = sample_config()

    def evaluate(self, profile, requirements=YEARS_REQUIRED, **evaluation):
        config = dict(self.config, evaluation=evaluation) if evaluation else self.config
        return evaluate(Job("Data Analyst", requirements=list(requirements)), profile, config)

    def test_confirmed_absence_keeps_the_existing_penalty_and_concern(self):
        none_recorded = self.evaluate(profile_with(False))
        experience_recorded = self.evaluate(profile_with(True))
        self.assertFalse(none_recorded.excluded)
        self.assertEqual(none_recorded.score, experience_recorded.score - 25)
        self.assertIn(YEARS_CONCERN, none_recorded.concerns)

    def test_optional_requirements_keep_their_smaller_penalty(self):
        none_recorded = self.evaluate(profile_with(False), YEARS_PREFERRED)
        experience_recorded = self.evaluate(profile_with(True), YEARS_PREFERRED)
        self.assertEqual(none_recorded.score, experience_recorded.score - 8)

    def test_recorded_experience_is_not_evidence_of_a_duration(self):
        result = self.evaluate(profile_with(True))
        self.assertFalse(result.excluded)
        self.assertNotIn(YEARS_CONCERN, result.concerns + result.uncertainties)
        self.assertTrue(any("records professional experience but not the years stated by" in item for item in result.uncertainties))
        self.assertEqual(result.score, self.evaluate(profile_with(None)).score)

    def test_unknown_status_is_flagged_without_a_penalty(self):
        for profile in (profile_with(None), profile_with(ABSENT)):
            with self.subTest(state=profile.data.get("professional_experience", "absent")):
                result = self.evaluate(profile)
                self.assertFalse(result.excluded)
                self.assertNotIn(YEARS_CONCERN, result.concerns + result.uncertainties)
                self.assertTrue(any("does not record whether the candidate meets the years stated by" in item for item in result.uncertainties))

    def test_the_experience_weight_only_applies_to_confirmed_absence(self):
        configured = {"experience_requirement": {"mandatory": 100}}
        for profile in (profile_with(True), profile_with(None)):
            with self.subTest(state=profile.data.get("professional_experience")):
                self.assertEqual(self.evaluate(profile, weights=configured).score, self.evaluate(profile).score)


class CurrentProfileCompatibilityTests(unittest.TestCase):
    def test_the_sample_profile_records_no_professional_experience(self):
        self.assertIs(Profile(sample_profile()).has_professional_experience, False)

    def test_seniority_and_experience_outputs_match_the_captured_baseline(self):
        baseline = {case["case"]: case["evaluation"] for case in json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]}
        profile, config = Profile(sample_profile()), sample_config()
        cases = {
            "senior title excluded": Job("Senior Data Engineer", requirements=[Requirement("Python", "mandatory")]),
            "experience in years mandatory": Job("Data Analyst", requirements=[Requirement("5 years of experience", "mandatory")]),
        }
        for case, job in cases.items():
            with self.subTest(case=case):
                self.assertEqual(evaluate(job, profile, config).to_dict(), baseline[case])


if __name__ == "__main__":
    unittest.main()
