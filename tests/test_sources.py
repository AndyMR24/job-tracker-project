import base64
import json
import unittest
from urllib.parse import quote
from unittest.mock import patch

from job_agent.ba import BASource
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
        self.assertEqual(job["source"], "ba"); self.assertEqual(job["description"], "Full description"); self.assertEqual(job["location"], "Aachen, NRW, Deutschland"); self.assertEqual(job["arrangement"], "unknown")
        self.assertEqual(job["source_url"], "https://employer.example/apply?utm_source=bundesagentur")
        expected = base64.b64encode(reference.encode()).decode()
        self.assertIn(quote(expected, safe=""), mocked.call_args_list[1].args[0].full_url)

    def test_ba_without_an_external_url_stays_unknown(self):
        reference = "10001-1003704716-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "firma": "BA Employer", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "allianzpartnerUrl": "www.ferchau.de"}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertIsNone(job["source_url"])
        self.assertEqual(job["metadata"]["beruf"], None)

    def test_ba_preserves_a_detail_only_external_url(self):
        reference = "10001-1003580281-S"
        search = {"ergebnisliste": [{"stellenangebotsTitel": "Data Analyst", "referenznummer": reference}]}
        detail = {"stellenangebotsTitel": "Data Analyst", "referenznummer": reference, "externeURL": "https://detail.example/apply", "allianzpartnerUrl": "www.xing.com"}
        with patch("job_agent.ba.urllib.request.urlopen", side_effect=[Response(search), Response(detail)]):
            job = BASource().search("Data Analyst", size=1)[0]
        self.assertEqual(job["source_url"], "https://detail.example/apply")

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
        self.assertTrue(jobs[2]["metadata"]["worldwide"])


if __name__ == "__main__": unittest.main()
