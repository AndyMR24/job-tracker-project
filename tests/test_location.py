import tempfile
import unittest

from job_agent.evaluator import DEFAULT_EVALUATION_SETTINGS, evaluate
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
        self.assertEqual(extract_city("Berlin, Deutschland"), "Berlin")
        self.assertEqual(extract_city("Mitte, Berlin"), "Berlin")
        self.assertEqual(extract_city("Hamburg-Altstadt, Hamburg"), "Hamburg")
        self.assertEqual(extract_city("Maxvorstadt, München"), "München")
        self.assertEqual(extract_city("Frankfurt am Main, Hessen"), "Frankfurt am Main")
        self.assertEqual(extract_city("Springe, Deister"), "Springe")
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


UNRESOLVABLE = "Xyzzyville"  # no such city in the fallback dictionary or geonamescache
ORIGIN_MESSAGE = "could not be resolved, so the geographic radius was not applied"
JOB_MESSAGE = "Job city could not be resolved for geographic-radius evaluation."
WITHIN_RADIUS_MESSAGE = "Location is within the configured geographic radius."


class LocationResolutionTests(unittest.TestCase):
    """The result says which side of the check failed instead of collapsing both into one status."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.config = load_config(write_config(cls.directory.name))

    def preferences(self, **overrides):
        return {**self.config["location_preferences"], **overrides}

    def test_resolvable_origin_and_job_location(self):
        result = resolve_location("Aachen", self.preferences())
        self.assertEqual(result.status, LocationStatus.WITHIN_RADIUS)
        self.assertTrue(result.origin_resolved)
        self.assertTrue(result.job_location_resolved)

    def test_unresolvable_origin_is_flagged_as_the_origin(self):
        result = resolve_location("Aachen", self.preferences(origin=UNRESOLVABLE))
        self.assertEqual(result.status, LocationStatus.UNKNOWN)
        self.assertFalse(result.origin_resolved)
        self.assertTrue(result.job_location_resolved)
        self.assertEqual(result.city, "Aachen")

    def test_unresolvable_job_location_is_flagged_as_the_job(self):
        result = resolve_location(UNRESOLVABLE, self.preferences())
        self.assertEqual(result.status, LocationStatus.UNKNOWN)
        self.assertTrue(result.origin_resolved)
        self.assertFalse(result.job_location_resolved)

    def test_missing_job_location_is_flagged_as_the_job(self):
        result = resolve_location(None, self.preferences())
        self.assertEqual(result.status, LocationStatus.UNKNOWN)
        self.assertTrue(result.origin_resolved)
        self.assertFalse(result.job_location_resolved)

    def test_both_sides_are_reported_when_neither_resolves(self):
        result = resolve_location(UNRESOLVABLE, self.preferences(origin=UNRESOLVABLE))
        self.assertEqual(result.status, LocationStatus.UNKNOWN)
        self.assertFalse(result.origin_resolved)
        self.assertFalse(result.job_location_resolved)


class RadiusFilteringTests(unittest.TestCase):
    """`evaluate` reports the right cause and only rewards a distance it could establish."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.profile = load_profile(write_profile(cls.directory.name))
        cls.config = load_config(write_config(cls.directory.name))

    def config_with(self, **preferences):
        return {**self.config, "location_preferences": {**self.config["location_preferences"], **preferences}}

    def test_inside_radius_keeps_the_within_radius_bonus(self):
        result = evaluate(Job("Data Analyst", location="Aachen", arrangement="hybrid"), self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertIn(WITHIN_RADIUS_MESSAGE, result.strong_matches)

    def test_outside_radius_still_excludes_non_remote_jobs(self):
        result = evaluate(Job("Data Analyst", location="München", arrangement="onsite"), self.profile, self.config)
        self.assertTrue(result.excluded)
        self.assertTrue(any("outside the configured geographic radius" in concern for concern in result.concerns))

    def test_remote_job_beyond_the_radius_needs_the_configured_switch(self):
        job = Job("Data Analyst", location="München", arrangement="remote")
        self.assertFalse(evaluate(job, self.profile, self.config).excluded)
        refused = evaluate(job, self.profile, self.config_with(remote_only_beyond_distance=False))
        self.assertTrue(refused.excluded)

    def test_exact_radius_boundary_is_inclusive_and_the_next_meter_is_outside(self):
        distance = resolve_location("Berlin", self.config_with(max_distance_km=1000)["location_preferences"]).distance_km
        at_boundary = resolve_location("Berlin", self.config_with(max_distance_km=distance)["location_preferences"])
        beyond = resolve_location("Berlin", self.config_with(max_distance_km=distance - 0.001)["location_preferences"])
        self.assertEqual(at_boundary.status, LocationStatus.WITHIN_RADIUS)
        self.assertEqual(beyond.status, LocationStatus.OUTSIDE_RADIUS)

    def test_valid_source_coordinates_resolve_an_unresolvable_location_text(self):
        result = resolve_location(UNRESOLVABLE, self.config["location_preferences"], coordinates=(52.52, 13.405))
        self.assertEqual(result.status, LocationStatus.OUTSIDE_RADIUS)
        self.assertTrue(result.job_location_resolved)

    def test_invalid_coordinates_fall_back_to_text_resolution(self):
        preferences = self.config["location_preferences"]
        for coordinates in ((999, 13.405), (52.52, -999), (float("nan"), 13.405), ("bad", 13.405)):
            with self.subTest(coordinates=coordinates):
                self.assertEqual(resolve_location("Aachen", preferences, coordinates=coordinates).status, LocationStatus.WITHIN_RADIUS)
                self.assertEqual(resolve_location(UNRESOLVABLE, preferences, coordinates=coordinates).status, LocationStatus.UNKNOWN)

    def test_valid_coordinates_drive_evaluation_and_unrelated_metadata_is_ignored(self):
        outside = Job("Data Analyst", location="Remote listing", arrangement="hybrid", metadata={"latitude": 52.52, "longitude": 13.405})
        self.assertTrue(evaluate(outside, self.profile, self.config).excluded)
        remote = Job("Data Analyst", location="Remote listing", arrangement="remote", metadata={"latitude": 52.52, "longitude": 13.405})
        self.assertFalse(evaluate(remote, self.profile, self.config).excluded)
        unrelated = Job("Data Analyst", location="Aachen", arrangement="hybrid", metadata={"company_latitude": 52.52, "company_longitude": 13.405})
        result = evaluate(unrelated, self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertIn(WITHIN_RADIUS_MESSAGE, result.strong_matches)

    def test_unresolvable_origin_is_reported_as_the_origin(self):
        result = evaluate(Job("Data Analyst", location="Aachen", arrangement="hybrid"), self.profile, self.config_with(origin=UNRESOLVABLE))
        self.assertFalse(result.excluded)
        self.assertTrue(any(ORIGIN_MESSAGE in item for item in result.uncertainties))
        self.assertNotIn(JOB_MESSAGE, result.uncertainties)
        self.assertNotIn(WITHIN_RADIUS_MESSAGE, result.strong_matches)

    def test_unresolvable_origin_does_not_award_the_within_radius_bonus(self):
        job = Job("Data Analyst", location="Aachen", arrangement="hybrid")
        resolved = evaluate(job, self.profile, self.config)
        unresolved = evaluate(job, self.profile, self.config_with(origin=UNRESOLVABLE))
        self.assertEqual(resolved.score - unresolved.score, DEFAULT_EVALUATION_SETTINGS["weights"]["onsite_or_hybrid_within_radius"])

    def test_unresolvable_job_location_keeps_its_own_message(self):
        result = evaluate(Job("Data Analyst", location=UNRESOLVABLE, arrangement="hybrid"), self.profile, self.config)
        self.assertFalse(result.excluded)
        self.assertIn(JOB_MESSAGE, result.uncertainties)
        self.assertFalse(any(ORIGIN_MESSAGE in item for item in result.uncertainties))
        self.assertNotIn(WITHIN_RADIUS_MESSAGE, result.strong_matches)

    def test_both_unresolvable_reports_both_causes(self):
        result = evaluate(Job("Data Analyst", location=UNRESOLVABLE, arrangement="hybrid"), self.profile, self.config_with(origin=UNRESOLVABLE))
        self.assertFalse(result.excluded)
        self.assertTrue(any(ORIGIN_MESSAGE in item for item in result.uncertainties))
        self.assertIn(JOB_MESSAGE, result.uncertainties)

    def test_remote_job_is_not_rejected_when_the_origin_is_unresolvable(self):
        result = evaluate(Job("Data Analyst", location="Aachen", arrangement="remote"), self.profile, self.config_with(origin=UNRESOLVABLE))
        self.assertFalse(result.excluded)
        self.assertIn("Germany-wide remote work is enabled in the configuration.", result.strong_matches)
        self.assertTrue(any(ORIGIN_MESSAGE in item for item in result.uncertainties))


if __name__ == "__main__":
    unittest.main()
