import base64
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from job_agent.ba import BAError, BASource
from job_agent.location import LocationStatus, resolve_location
from job_agent.normalizer import normalize
from job_agent.storage import Store
from job_agent.himalayas import HimalayasSource
from job_agent.nomado24 import Nomado24Source


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.payload).encode()


class SourceAdapterTests(unittest.TestCase):
    def test_nomado24_maps_fields_and_optional_values(self):
        payload = {"jobs": [{"id": "n1", "title": "Data Analyst", "companyName": "Nomado", "location": "Aachen", "remote": True, "workArrangement": "remote", "url": "https://nomado.test/1", "salaryMin": 50000, "currency": "EUR"}, {"id": "n2", "title": "Minimal"}]}
        with patch("job_agent.nomado24.urllib.request.urlopen", return_value=Response(payload)):
            jobs = Nomado24Source().search("Data Analyst")
        self.assertEqual(jobs[0]["source"], "nomado24"); self.assertEqual(jobs[0]["company"], "Nomado"); self.assertEqual(jobs[0]["arrangement"], "remote")
        self.assertNotIn("location_restrictions", jobs[0]["metadata"])
        self.assertIsNone(jobs[1]["company"]); self.assertIsNone(jobs[1]["location"])

    def test_himalayas_preserves_location_restrictions(self):
        payload = {"jobs": [{"guid": "h1", "title": "Python Developer", "company": {"name": "Himalayas Co"}, "remote": True, "locationRestrictions": ["Germany"], "timezoneRestrictions": ["CET"], "applicationLink": "https://himalayas.test/1"}]}
        with patch("job_agent.himalayas.urllib.request.urlopen", return_value=Response(payload)):
            job = HimalayasSource().search("Python")[0]
        self.assertEqual(job["source"], "himalayas"); self.assertEqual(job["arrangement"], "remote"); self.assertEqual(job["metadata"]["location_restrictions"], ["Germany"]); self.assertIsNone(job["location"])

    def test_ba_maps_search_and_detail_and_encodes_reference(self):
        reference = "10001-1003580280-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "firma": "BA Employer", "referenznummer": reference, "stellenlokationen": [{"ort": "Aachen", "region": "NRW", "land": "Deutschland"}], "homeofficemoeglich": True, "externeURL": "https://employer.example/apply?utm_source=bundesagentur"}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "stellenangebotsBeschreibung": "Full description", "referenznummer": reference, "angebotsart": "ARBEIT"}
        responses = [Response(search), Response(detail)]
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=responses) as mocked:
            job = BASource().search("Data Analyst", "Aachen", size=1)[0]
        self.assertEqual(job["source"], "ba"); self.assertEqual(job["description"], "Full description"); self.assertEqual(job["location"], "Aachen"); self.assertEqual(job["arrangement"], "unknown")
        self.assertEqual(job["source_url"], "https://employer.example/apply?utm_source=bundesagentur")
        self.assertEqual(job["metadata"]["region"], "NRW")
        self.assertEqual(job["metadata"]["country"], "Deutschland")
        self.assertNotIn("location_restrictions", job["metadata"])
        expected = base64.b64encode(reference.encode()).decode()
        self.assertIn(quote(expected, safe=""), mocked.call_args_list[1].args[0].full_url)

    def test_ba_without_an_external_url_stays_unknown(self):
        reference = "10001-1003704716-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "firma": "BA Employer", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "allianzpartnerUrl": "www.ferchau.de"}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertIsNone(job["location"])
        self.assertIsNone(job["source_url"])
        self.assertEqual(job["metadata"]["beruf"], None)

    def test_ba_maps_nested_detail_address_and_coordinates(self):
        reference = "10001-1003580286-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {
            "stellenangebotsTitel": "Data Analyst",
            "referenznummer": reference,
            "stellenlokationen": [{
                "adresse": {"plz": "01307", "ort": "Dresden", "region": "SACHSEN", "land": "DEUTSCHLAND"},
                "breite": 51.0526313,
                "laenge": 13.7705539,
            }],
        }
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["location"], "Dresden")
        self.assertEqual(job["metadata"]["postal_code"], "01307")
        self.assertEqual(job["metadata"]["region"], "SACHSEN")
        self.assertEqual(job["metadata"]["country"], "DEUTSCHLAND")
        self.assertEqual(job["metadata"]["latitude"], 51.0526313)
        self.assertEqual(job["metadata"]["longitude"], 13.7705539)

    def test_ba_location_survives_normalization_storage_and_distance_resolution(self):
        reference = "10001-1003580287-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {
            "stellenangebotsTitel": "Data Analyst",
            "referenznummer": reference,
            "stellenlokationen": [{
                "adresse": {"plz": "52062", "ort": "Aachen", "region": "NRW", "land": "DEUTSCHLAND"},
                "breite": 50.7753,
                "laenge": 6.0839,
            }],
        }
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            raw = BASource().search("Data Analyst", size=1)[0]
        job = normalize(raw)
        self.assertEqual(job.location, "Aachen")
        self.assertEqual(resolve_location(job.location, {"origin": "Aachen", "max_distance_km": 225}).status, LocationStatus.WITHIN_RADIUS)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "jobs.sqlite")
            try:
                job_id, _ = store.save_job(job, {"score": 50})
                stored, _, _ = store.get_job(job_id)
            finally:
                store.close()
        self.assertEqual(stored.location, "Aachen")
        self.assertEqual(stored.metadata["postal_code"], "52062")

    def test_ba_partial_location_keeps_unknown_fields(self):
        reference = "10001-1003580288-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {
            "stellenangebotsTitel": "Data Analyst",
            "referenznummer": reference,
            "stellenlokationen": [{"adresse": {"ort": "Aachen"}}],
        }
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["location"], "Aachen")
        self.assertIsNone(job["metadata"]["postal_code"])
        self.assertIsNone(job["metadata"]["region"])
        self.assertIsNone(job["metadata"]["country"])

    def test_ba_preserves_a_detail_only_external_url(self):
        reference = "10001-1003580281-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "externeURL": "https://detail.example/apply", "allianzpartnerUrl": "www.xing.com"}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["source_url"], "https://detail.example/apply")

    def test_ba_keeps_neighbors_when_one_detail_request_fails(self):
        search = {"ergebnisliste": [
            {"stellenangebotsTitel": "First Role", "firma": "One", "referenznummer": "good", "stellenlokationen": [{"ort": "Aachen"}]},
            {"stellenangebotsTitel": "Second Role", "firma": "Two", "referenznummer": "bad", "stellenlokationen": [{"ort": "Berlin"}]},
        ]}
        detail = {"stellenangebotsTitel": "First Role", "stellenangebotsBeschreibung": "Full description"}
        with patch.object(BASource, "_get", side_effect=[search, detail, BAError("detail unavailable")]):
            source = BASource()
            jobs = source.search("Data Analyst")
        self.assertEqual([job["title"] for job in jobs], ["First Role", "Second Role"])
        self.assertEqual(jobs[1]["location"], "Berlin")
        self.assertEqual(len(source.partial_errors), 1)
        self.assertIn("retained available search-result data", source.partial_errors[0])

    def test_ba_skips_malformed_result_and_reports_it(self):
        search = {"ergebnisliste": [
            {"referenznummer": "missing-title"},
            {"stellenangebotsTitel": 123, "referenznummer": "numeric-title"},
        ]}
        with patch.object(BASource, "_get", return_value=search):
            source = BASource()
            jobs = source.search("Data Analyst")
        self.assertEqual(jobs, [])
        self.assertEqual(
            source.partial_errors,
            ["search result 1 skipped: missing job title", "search result 2 skipped: missing job title"],
        )

    def test_ba_rejects_unexpected_search_result_shape(self):
        with patch.object(BASource, "_get", return_value={"ergebnisliste": "invalid"}):
            with self.assertRaisesRegex(BAError, "unexpected search-results shape"):
                BASource().search("Data Analyst")

    def test_ba_search_request_failure_remains_a_source_failure(self):
        with patch.object(BASource, "_get", side_effect=BAError("search unavailable")):
            with self.assertRaisesRegex(BAError, "search unavailable"):
                BASource().search("Data Analyst")

    def test_ba_extracts_a_labelled_application_form_link_from_the_description(self):
        reference = "10001-1003580282-S"
        description = "Bewerbungsformular: [Zum Bewerbungsformular](https://recruiting.example.test/apply/42)"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "stellenangebotsBeschreibung": description}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["source_url"], "https://recruiting.example.test/apply/42")
        self.assertEqual(job["description"], description)

    def test_ba_does_not_extract_unrelated_description_links(self):
        reference = "10001-1003580283-S"
        description = "Datenschutz: [Hinweise](https://example.test/privacy)\nKarriere: [Overview](https://example.test/career)"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "stellenangebotsBeschreibung": description}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertIsNone(job["source_url"])

    def test_ba_does_not_accept_unsupported_description_schemes(self):
        reference = "10001-1003580284-S"
        description = "Bewerbungsformular: [E-Mail senden](mailto:jobs@example.test)"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "stellenangebotsBeschreibung": description}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertIsNone(job["source_url"])

    def test_ba_prefers_explicit_external_url_over_a_description_link(self):
        reference = "10001-1003580285-S"
        description = "Bewerbungsformular: [Zum Bewerbungsformular](https://description.example/apply)"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "externeURL": "https://search.example/apply"}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "stellenangebotsBeschreibung": description}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["source_url"], "https://search.example/apply")

    def test_himalayas_restriction_semantics_are_preserved(self):
        payload = {"jobs": [
            {"guid": "h1", "title": "US only Analyst", "locationRestrictions": ["United States", "Canada"], "timezoneRestrictions": [-8, -5]},
            {"guid": "h2", "title": "Worldwide Analyst", "locationRestrictions": []},
            {"guid": "h3", "title": "Analyst without restriction field"},
        ]}
        with patch("job_agent.himalayas.urllib.request.urlopen", return_value=Response(payload)):
            jobs = HimalayasSource().search("Analyst")
        self.assertEqual(jobs[0]["metadata"]["location_restrictions"], ["United States", "Canada"])
        self.assertFalse(jobs[0]["metadata"]["worldwide"])
        self.assertEqual(jobs[1]["metadata"]["location_restrictions"], [])
        self.assertTrue(jobs[1]["metadata"]["worldwide"])
        self.assertNotIn("location_restrictions", jobs[2]["metadata"])
        self.assertIsNone(jobs[2]["metadata"]["worldwide"])


if __name__ == "__main__": unittest.main()
