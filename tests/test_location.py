import tempfile
import unittest

from job_agent.evaluator import evaluate
from job_agent.location import EligibilityStatus, LocationStatus, extract_city, resolve_eligibility, resolve_location
from job_agent.models import Job
from job_agent.profile import load_config, load_profile


try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile  # noqa: F401
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile  # noqa: F401


class LocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.profile = load_profile(write_profile(cls.directory.name))
        cls.config = load_config(write_config(cls.directory.name))

    def test_common_city_formats_resolve_conservatively(self):
        self.assertEqual(extract_city("München, München (Kreis)"), "München")
        self.assertEqual(extract_city("Köln, Köln"), "Köln")
        self.assertIsNone(extract_city("Germany"))
        self.assertIsNone(extract_city("München, Berlin"))

    def test_within_and_outside_radius(self):
        self.assertEqual(resolve_location("Aachen", self.config["location_preferences"]).status, LocationStatus.WITHIN_RADIUS)
        self.assertEqual(resolve_location("München, München (Kreis)", self.config["location_preferences"]).status, LocationStatus.OUTSIDE_RADIUS)

    def test_outside_radius_requires_explicit_remote_exception(self):
        config = self.config
        self.assertTrue(evaluate(Job("Data Analyst", location="München, München (Kreis)", arrangement="remote"), self.profile, config).excluded is False)
        for arrangement in ("hybrid", "onsite", "unknown"):
            with self.subTest(arrangement=arrangement):
                result = evaluate(Job("Data Analyst", location="München, München (Kreis)", arrangement=arrangement), self.profile, config)
                self.assertTrue(result.excluded)

    def test_eligibility_interprets_published_country_restrictions(self):
        self.assertEqual(resolve_eligibility({"location_restrictions": []}, "Germany").status, EligibilityStatus.ALLOWED)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["Germany", "Austria"]}, "Germany").status, EligibilityStatus.ALLOWED)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["Europe"]}, "Germany").status, EligibilityStatus.ALLOWED)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["United States", "Canada"]}, "Germany").status, EligibilityStatus.RESTRICTED)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["United States", "Canada"]}, "Germany").detail, "United States, Canada")
        self.assertEqual(resolve_eligibility({}, "Germany").status, EligibilityStatus.UNKNOWN)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["United States"]}, None).status, EligibilityStatus.UNKNOWN)
        self.assertEqual(resolve_eligibility({"location_restrictions": ["United States"]}, "").status, EligibilityStatus.UNKNOWN)

    def test_missing_or_unresolved_location_is_unknown(self):
        preferences = self.config["location_preferences"]
        self.assertEqual(resolve_location(None, preferences).status, LocationStatus.UNKNOWN)
        self.assertEqual(resolve_location("Europe", preferences).status, LocationStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
