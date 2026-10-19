import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.cv import generate
from job_agent.evaluator import _secondary_language_signal, evaluate
from job_agent.models import Job, Requirement
from job_agent.profile import Profile, load_config, load_profile
from job_agent.search import SearchProviderChallengeError, public_search
from job_agent.storage import Store


try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile  # noqa: F401
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile  # noqa: F401


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.profile = load_profile(write_profile(cls.directory.name))
        cls.config = load_config(write_config(cls.directory.name))

    def test_nonexistent_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "jobs.sqlite")
            with self.assertRaises(KeyError): store.set_decision(999, "save")
            with self.assertRaises(KeyError): store.set_decision(999, "reject")
            with self.assertRaises(KeyError): store.remove_from_shortlist(999)
            with self.assertRaises(KeyError): store.update_application(999, "applied", None, None)
            with self.assertRaises(KeyError): store.save_cv(999, "draft.pdf", [])
            self.assertEqual(store.list_jobs(), [])
            self.assertEqual(store.applications(), [])
            self.assertEqual(store.history(), [])
            store.close()

    def test_target_role_matching_is_narrow_but_keeps_variants(self):
        positive = ["Junior Data Scientist", "Data Science Associate", "Junior Data Analyst", "Data Engineer", "Machine Learning Engineer", "Junior Python Developer", "Python Software Developer", "Software Developer"]
        negative = ["Business Analyst", "Marketing Analyst", "Financial Analyst", "Frontend Developer"]
        for title in positive:
            with self.subTest(title=title):
                self.assertIn("Title is related", " ".join(evaluate(Job(title), self.profile, self.config).strong_matches))
        for title in negative:
            with self.subTest(title=title):
                self.assertNotIn("Title is related", " ".join(evaluate(Job(title), self.profile, self.config).strong_matches))

    def test_secondary_role_is_distinguishable_from_primary_role(self):
        secondary = evaluate(Job("Junior IT Consultant"), self.profile, self.config)
        primary = evaluate(Job("Junior Data Engineer"), self.profile, self.config)
        self.assertIn("secondary role", " ".join(secondary.strong_matches))
        self.assertNotIn("target role", " ".join(secondary.strong_matches))
        self.assertIn("target role", " ".join(primary.strong_matches))
        self.assertGreater(primary.score, secondary.score)

    def test_unrelated_junior_remote_job_is_not_recommended(self):
        result = evaluate(Job("Junior Payroll Assistant", arrangement="remote"), self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertNotEqual(result.assessment, "recommended")

    def test_compatible_seniority_is_not_a_major_score_bonus(self):
        junior = evaluate(Job("Payroll Assistant", seniority="junior"), self.profile, self.config)
        unknown = evaluate(Job("Payroll Assistant", seniority="unknown"), self.profile, self.config)
        self.assertEqual(junior.score, unknown.score)

    def test_sponsorship_variants_are_flagged_without_exclusion(self):
        for wording in ("visa sponsorship required", "this role requires sponsorship", "employer sponsorship is unavailable"):
            with self.subTest(wording=wording):
                result = evaluate(Job("Python Developer", description=wording), self.profile, self.config)
                self.assertTrue(result.uncertainties)
                self.assertFalse(result.excluded)

    def test_country_restricted_remote_job_is_excluded(self):
        restricted = evaluate(Job("Python Developer", arrangement="remote", metadata={"location_restrictions": ["United States"]}), self.profile, self.config)
        self.assertTrue(restricted.excluded)
        self.assertEqual(restricted.assessment, "rejected")
        self.assertTrue(any("United States" in concern for concern in restricted.concerns))

    def test_remote_job_open_to_germany_or_worldwide_stays_allowed(self):
        for metadata in ({"location_restrictions": []}, {"location_restrictions": ["Germany"]}, {"location_restrictions": ["United States", "Germany"]}, {"location_restrictions": ["Europe"]}, {}):
            with self.subTest(metadata=metadata):
                result = evaluate(Job("Python Developer", arrangement="remote", metadata=metadata), self.profile, self.config)
                self.assertFalse(result.excluded)
                self.assertIn("Germany-wide remote work is enabled in the configuration.", result.strong_matches)

    def test_country_restriction_without_a_known_home_country_changes_nothing(self):
        profile = Profile({**self.profile.data, "employment_eligibility": {}})
        result = evaluate(Job("Python Developer", arrangement="remote", metadata={"location_restrictions": ["United States"]}), profile, self.config)
        self.assertFalse(result.excluded)
        self.assertFalse(any("restricted" in item.lower() for item in result.concerns + result.uncertainties))

    def test_country_restriction_does_not_affect_known_german_locations(self):
        result = evaluate(Job("Junior Data Analyst", location="Aachen", arrangement="hybrid", metadata={"location_restrictions": ["United States"]}), self.profile, self.config)
        self.assertTrue(result.excluded)
        self.assertTrue(any("United States" in concern for concern in result.concerns))
        self.assertIn("Location is within the configured geographic radius.", result.strong_matches)

    def test_python_is_a_secondary_positive_signal(self):
        python_job = evaluate(Job("Junior Data Analyst", requirements=[Requirement("Python", "preferred")]), self.profile, self.config)
        other_job = evaluate(Job("Junior Data Analyst", requirements=[Requirement("SQL", "preferred")]), self.profile, self.config)
        self.assertEqual(python_job.score - other_job.score, 3)
        self.assertFalse(python_job.excluded)
        self.assertTrue(any("secondary preference" in item for item in python_job.strong_matches))

    def test_missing_python_is_not_penalised_into_rejection(self):
        result = evaluate(Job("Junior Data Analyst", location="Aachen", arrangement="hybrid", requirements=[Requirement("SQL", "preferred")]), self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertEqual(result.assessment, "recommended")
        self.assertFalse(any("secondary preference" in item for item in result.strong_matches))

    def test_python_preference_never_overrides_core_fit(self):
        senior = evaluate(Job("Senior Data Analyst", requirements=[Requirement("Python", "mandatory")], description="We write Python everywhere."), self.profile, self.config)
        self.assertTrue(senior.excluded)
        outside = evaluate(Job("Junior Data Analyst", location="Munich", arrangement="onsite", requirements=[Requirement("Python", "mandatory")]), self.profile, self.config)
        self.assertTrue(outside.excluded)
        python_only = evaluate(Job("Junior Data Analyst", requirements=[Requirement("Python", "mandatory")]), self.profile, self.config)
        missing_core = evaluate(Job("Junior Data Analyst", requirements=[Requirement("Python", "mandatory"), Requirement("Kubernetes", "mandatory")]), self.profile, self.config)
        # an unlisted requirement is unknown, not a gap: it costs nothing and is left for review
        self.assertEqual(python_only.score, missing_core.score)
        self.assertFalse(missing_core.excluded)
        self.assertTrue(any("Kubernetes" in item for item in missing_core.uncertainties))

    def test_explicit_python_mentions_outweigh_incidental_ones(self):
        explicit = evaluate(Job("Junior Data Analyst", requirements=[Requirement("Python", "preferred")]), self.profile, self.config)
        other_requirement = evaluate(Job("Junior Data Analyst", requirements=[Requirement("SQL", "preferred")]), self.profile, self.config)
        qualifying = evaluate(Job("Junior Data Analyst", qualifications="Python"), self.profile, self.config)
        incidental = evaluate(Job("Junior Data Analyst", description="We use Python daily."), self.profile, self.config)
        absent = evaluate(Job("Junior Data Analyst"), self.profile, self.config)
        self.assertEqual(explicit.score - other_requirement.score, 3)
        self.assertEqual(qualifying.score - absent.score, 2)
        self.assertEqual(incidental.score - absent.score, 1)
        self.assertEqual(_secondary_language_signal(Job("Role", requirements=[Requirement("Python")]), ("python",)), "requirement")
        self.assertEqual(_secondary_language_signal(Job("Role", qualifications="Python and SQL"), ("python",)), "qualification")
        self.assertEqual(_secondary_language_signal(Job("Role", description="Python tooling"), ("python",)), "description")
        self.assertIsNone(_secondary_language_signal(Job("Role", description="Pythonic culture only"), ("python",)))

    def test_search_challenge_is_distinguished_from_zero_results(self):
        challenge = type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *args: None, "read": lambda self: b"captcha unusual traffic"})
        empty = type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *args: None, "read": lambda self: b"<html><body>normal results page</body></html>"})
        with patch("job_agent.search.urlopen", return_value=challenge()):
            with self.assertRaises(SearchProviderChallengeError): public_search("test")
        with patch("job_agent.search.urlopen", return_value=empty()):
            self.assertEqual(public_search("test"), [])

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed in this test environment")
    def test_cv_heading_reflects_requirement_match(self):
        with tempfile.TemporaryDirectory() as directory:
            matched = Path(directory) / "matched.pdf"
            unmatched = Path(directory) / "unmatched.pdf"
            generate(Job("Python Developer", requirements=[Requirement("Python")]), self.profile, matched)
            generate(Job("Business Analyst", requirements=[Requirement("Excel")]), self.profile, unmatched)
            from pypdf import PdfReader
            matched_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(matched)).pages)
            unmatched_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(unmatched)).pages)
            self.assertIn("Relevant projects", matched_text)
            self.assertIn("Projects", unmatched_text)
            self.assertNotIn("Relevant projects", unmatched_text)


if __name__ == "__main__": unittest.main()
