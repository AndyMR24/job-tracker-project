"""The optional `evaluation` configuration block overrides the shipped scoring defaults.

`tests/evaluation_baseline.json` holds the serialized evaluations of `support.evaluation_cases()`
as produced *before* the weights became configurable, so the first test here proves that omitting the
block reproduces the previous output exactly.
"""
import json
import tempfile
import unittest
from pathlib import Path

from job_agent.evaluator import DEFAULT_EVALUATION_SETTINGS, evaluate, evaluation_settings
from job_agent.normalizer import normalize
from job_agent.profile import EVALUATION_WEIGHT_SCHEMA, Profile, ValidationError, load_config

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import evaluation_cases, sample_config, sample_profile, write_config
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import evaluation_cases, sample_config, sample_profile, write_config

BASELINE = Path(__file__).with_name("evaluation_baseline.json")
CONFIG_EXAMPLE = Path("data/search_config.example.json")


class BaselineTests(unittest.TestCase):
    def test_omitting_the_block_reproduces_the_captured_baseline(self):
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]
        cases = evaluation_cases()
        profile, config = Profile(sample_profile()), sample_config()
        self.assertEqual([case["case"] for case in cases], [case["case"] for case in baseline])
        for expected, case in zip(baseline, cases):
            with self.subTest(case=case["case"]):
                evaluation = evaluate(normalize(dict(case["job"])), profile, config)
                self.assertEqual(evaluation.to_dict(), expected["evaluation"])

    def test_baseline_covers_every_assessment_and_an_exclusion(self):
        evaluations = [case["evaluation"] for case in json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]]
        self.assertEqual({item["assessment"] for item in evaluations}, {"recommended", "borderline", "rejected"})
        self.assertTrue(any(item["excluded"] for item in evaluations))
        self.assertTrue(all(isinstance(item["score"], int) for item in evaluations))


class SettingsResolutionTests(unittest.TestCase):
    def test_absent_block_returns_the_shipped_defaults(self):
        self.assertEqual(evaluation_settings(sample_config()), DEFAULT_EVALUATION_SETTINGS)

    def test_partial_override_keeps_every_other_default(self):
        resolved = evaluation_settings({**sample_config(), "evaluation": {"base_score": 10, "weights": {"remote": 1, "confirmed_skill": {"mandatory": 0}}}})
        self.assertEqual(resolved["base_score"], 10)
        self.assertEqual(resolved["recommended_threshold"], DEFAULT_EVALUATION_SETTINGS["recommended_threshold"])
        self.assertEqual(resolved["weights"]["remote"], 1)
        self.assertEqual(resolved["weights"]["confirmed_skill"], {"mandatory": 0, "other": 4})
        self.assertEqual(resolved["weights"]["missing_requirement"], DEFAULT_EVALUATION_SETTINGS["weights"]["missing_requirement"])

    def test_resolution_leaves_the_defaults_untouched(self):
        evaluation_settings({**sample_config(), "evaluation": {"weights": {"confirmed_skill": {"mandatory": 0}, "missing_requirement": {"mandatory": 0}}}})
        self.assertEqual(DEFAULT_EVALUATION_SETTINGS["weights"]["confirmed_skill"], {"mandatory": 8, "other": 4})
        self.assertEqual(DEFAULT_EVALUATION_SETTINGS["weights"]["missing_requirement"]["mandatory"], 18)

    def test_validation_schema_and_defaults_stay_in_sync(self):
        def shape(schema):
            return {key: shape(value) if isinstance(value, dict) else True for key, value in schema.items()}
        self.assertEqual(shape(EVALUATION_WEIGHT_SCHEMA), shape(DEFAULT_EVALUATION_SETTINGS["weights"]))


class OverrideTests(unittest.TestCase):
    """Scoring behaviour with an `evaluation` block present."""

    JUNIOR = {"title": "Data Analyst", "location": "Aachen", "arrangement": "hybrid", "requirements": [{"text": "Python", "kind": "mandatory"}]}

    def setUp(self):
        self.profile = Profile(sample_profile())
        self.base = sample_config()

    def score(self, raw_job, **evaluation):
        config = dict(self.base, evaluation=evaluation) if evaluation else self.base
        return evaluate(normalize(dict(raw_job)), self.profile, config)

    def test_base_score_override_shifts_the_score_and_assessment(self):
        self.assertEqual(self.score(self.JUNIOR).score, 80)
        lowered = self.score(self.JUNIOR, base_score=0)
        self.assertEqual(lowered.score, 30)
        self.assertEqual(lowered.assessment, "borderline")

    def test_recommended_threshold_changes_only_the_label(self):
        default = self.score(self.JUNIOR)
        raised = self.score(self.JUNIOR, recommended_threshold=100)
        lowered = self.score(self.JUNIOR, recommended_threshold=0)
        self.assertEqual(default.assessment, "recommended")
        self.assertEqual(raised.assessment, "borderline")
        self.assertEqual(lowered.assessment, "recommended")
        self.assertEqual(raised.score, default.score)
        self.assertEqual(lowered.score, default.score)

    def test_threshold_never_labels_an_excluded_job_as_recommended(self):
        excluded = self.score({"title": "Senior Data Engineer"}, recommended_threshold=0)
        self.assertTrue(excluded.excluded)
        self.assertEqual(excluded.assessment, "rejected")

    def test_nested_weight_overrides_replace_only_that_weight(self):
        job = self.JUNIOR
        default = self.score(job).score
        mandatory_bonus = DEFAULT_EVALUATION_SETTINGS["weights"]["confirmed_skill"]["mandatory"]
        self.assertEqual(self.score(job, weights={"confirmed_skill": {"mandatory": 0}}).score, default - mandatory_bonus)
        self.assertEqual(self.score(job, weights={"confirmed_skill": {"other": 0}}).score, default)
        bare = {"title": "Data Analyst"}
        self.assertEqual(self.score(bare).score, 60)
        self.assertEqual(self.score(bare, weights={"no_requirements": 0}).score, 65)

    def test_a_job_with_every_bonus_disabled_scores_the_base_score(self):
        result = self.score(self.JUNIOR, weights={"target_role": 0, "confirmed_skill": {"mandatory": 0}, "onsite_or_hybrid_within_radius": 0, "preferred_language": {"requirement": 0}})
        self.assertEqual(result.score, 50)

    def test_language_tier_weight_override(self):
        job = {"title": "Data Analyst", "qualifications": "Python and SQL"}
        self.assertEqual(self.score(job).score - self.score(job, weights={"preferred_language": {"qualification": 0}}).score, 2)

    def test_penalty_overrides_do_not_disable_exclusions(self):
        senior = self.score({"title": "Senior Data Engineer"}, weights={"senior_penalty": 0})
        degree = self.score({"title": "Data Analyst", "requirements": [{"text": "Master's degree", "kind": "mandatory"}]}, weights={"degree_required_penalty": 0})
        self.assertTrue(senior.excluded)
        self.assertTrue(degree.excluded)
        self.assertEqual(senior.assessment, "rejected")
        self.assertEqual(degree.assessment, "rejected")
        self.assertEqual(degree.score, 65)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def load(self, evaluation):
        config = dict(sample_config(), evaluation=evaluation)
        return load_config(write_config(self.root, config))

    def test_a_configuration_without_the_block_still_loads(self):
        config = load_config(write_config(self.root, sample_config()))
        self.assertNotIn("evaluation", config)

    def test_partial_and_fractional_values_are_accepted(self):
        config = self.load({"base_score": 25.5, "recommended_threshold": 0, "weights": {"remote": 0, "preferred_language": {"description": 1.5}}})
        self.assertEqual(config["evaluation"]["base_score"], 25.5)
        self.assertEqual(config["evaluation"]["weights"]["preferred_language"]["description"], 1.5)

    def test_invalid_blocks_are_rejected(self):
        for evaluation in (
            "not an object",
            [],
            {"base_score": "50"},
            {"base_score": True},
            {"base_score": -1},
            {"base_score": 101},
            {"recommended_threshold": -1},
            {"recommended_threshold": 101},
            {"recommended_threshold": None},
            {"unknown_setting": 1},
            {"weights": []},
            {"weights": {"unknown_weight": 1}},
            {"weights": {"remote": -1}},
            {"weights": {"remote": "5"}},
            {"weights": {"remote": False}},
            {"weights": {"confirmed_skill": 5}},
            {"weights": {"confirmed_skill": {"mandatory": -1}}},
            {"weights": {"confirmed_skill": {"unknown_kind": 1}}},
        ):
            with self.subTest(evaluation=evaluation):
                with self.assertRaises(ValidationError):
                    self.load(evaluation)

    def test_the_shipped_example_documents_the_defaults(self):
        config = load_config(CONFIG_EXAMPLE)
        self.assertEqual(evaluation_settings(config), DEFAULT_EVALUATION_SETTINGS)


if __name__ == "__main__":
    unittest.main()
