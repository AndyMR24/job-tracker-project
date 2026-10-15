"""Dashboard tests: read models plus real HTTP requests against a temporary database."""
import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

from job_agent import dashboard, webui
from job_agent import discovery
from job_agent.adzuna import AdzunaError
from job_agent.cli import main as cli_main
from job_agent.evaluator import evaluate
from job_agent.normalizer import normalize
from job_agent.profile import load_config, load_profile
from job_agent.storage import Store
from job_agent.webapp import SearchManager, build_server

try:  # works for "python -m unittest discover -s tests" and for pytest
    from support import write_config, write_profile
except ImportError:  # pragma: no cover - when the tests directory is imported as a package
    from tests.support import write_config, write_profile

FIXTURES = [
    {"title": "Junior Data Analyst", "company": "Acme GmbH", "location": "Aachen", "arrangement": "hybrid", "source": "adzuna", "source_url": "https://example.test/1", "external_job_id": "1", "description": "SQL and Python reporting for the analytics team.", "requirements": [{"text": "Python", "kind": "mandatory"}, {"text": "Excel", "kind": "preferred"}]},
    {"title": "Senior Data Platform Engineer", "company": "Big Corp", "location": "Berlin", "arrangement": "onsite", "source": "ba", "source_url": "https://example.test/2", "external_job_id": "2", "description": "Lead the data platform team."},
    {"title": "Python Developer", "company": "RemoteWorks", "location": None, "arrangement": "remote", "source": "himalayas", "source_url": "https://example.test/3", "external_job_id": "3", "description": "Build services with Python, SQL and Git."},
    {"title": "Werkstudent Data Science", "company": "Uni Lab", "location": "Cologne", "arrangement": "remote", "source": "nomado24", "source_url": "https://example.test/4", "external_job_id": "4", "description": "Support data science projects with pandas."},
    {"title": "Office Manager", "company": "Local Office", "location": "Aachen", "arrangement": "onsite", "source": "adzuna", "source_url": "https://example.test/5", "external_job_id": "5", "description": "Organise the office."},
]


class StubAdapter:
    def __init__(self, jobs, name):
        self.jobs = jobs
        self.name = name
        self.calls = []

    def search(self, query, location=None):
        self.calls.append((query, location))
        return [dict(job, source=self.name, external_job_id="%s-%s" % (self.name, query), source_url="https://example.test/%s/%s" % (self.name, query)) for job in self.jobs]


class DashboardFixture(unittest.TestCase):
    """Builds a temporary database from the real profile/config and evaluates fixtures with the real evaluator."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.profile_path = write_profile(root); self.config_path = write_config(root)
        self.profile = load_profile(self.profile_path)
        self.config = load_config(self.config_path)
        self.database = root / "jobs.sqlite"
        self.output = root / "output"
        store = Store(self.database)
        self.ids = {}
        for fixture in FIXTURES:
            job = normalize(dict(fixture))
            evaluation = evaluate(job, self.profile, self.config)
            job_id, _ = store.save_job(job, evaluation.to_dict())
            self.ids[fixture["title"]] = job_id
        store.close()
        self.stores = []
        self.adapters = {
            "adzuna": StubAdapter([{"title": "Junior BI Analyst", "company": "NewCo", "location": "Aachen", "external_job_id": "n1", "source_url": "https://example.test/n1"}], "adzuna"),
            "nomado24": StubAdapter([], "nomado24"),
            "himalayas": StubAdapter([], "himalayas"),
            "ba": StubAdapter([], "ba"),
        }
        self.server = build_server(host="127.0.0.1", port=0, profile=self.profile_path, config=self.config_path, database=self.database, output=self.output, quiet=True, sources_factory=self.sources_factory)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%s" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for store in self.stores:
            store.close()
        self.directory.cleanup()

    def sources_factory(self, root):
        return {name: (adapter, name != "himalayas") for name, adapter in self.adapters.items()}

    def store(self):
        store = Store(self.database)
        self.stores.append(store)
        return store

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as response:
            return response.status, response.read().decode("utf-8")

    def get_error(self, path):
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.base + path, timeout=20)
        error = context.exception
        try:
            return error.code, error.read().decode("utf-8")
        finally:
            error.close()

    def post(self, path, data, headers=None):
        request = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode("utf-8"), method="POST", headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.geturl(), response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.geturl(), exc.read().decode("utf-8")
            finally:
                exc.close()


class ReadModelTests(DashboardFixture):
    def records(self):
        store = Store(self.database)
        try:
            return [dashboard.job_record(row) for row in store.list_jobs()]
        finally:
            store.close()

    def test_summary_reports_bands_sources_and_statuses(self):
        records = self.records()
        summary = dashboard.summary(records, [], [])
        self.assertEqual(summary["total"], len(FIXTURES))
        self.assertGreaterEqual(summary["by_band"].get("recommended", 0), 1)
        self.assertEqual(summary["by_band"].get("excluded", 0), 1)
        self.assertIn("adzuna", summary["by_source"])
        self.assertIsNotNone(summary["average_score"])

    def test_filter_jobs_applies_every_criterion(self):
        records = self.records()
        self.assertEqual([record["title"] for record in dashboard.filter_jobs(records, text="data analyst")], ["Junior Data Analyst"])
        self.assertEqual([record["title"] for record in dashboard.filter_jobs(records, source="himalayas")], ["Python Developer"])
        self.assertNotIn("Senior Data Platform Engineer", [record["title"] for record in dashboard.filter_jobs(records)])
        self.assertIn("Senior Data Platform Engineer", [record["title"] for record in dashboard.filter_jobs(records, include_excluded=True)])
        self.assertEqual([record["title"] for record in dashboard.filter_jobs(records, min_score=70)], ["Junior Data Analyst"])
        self.assertEqual([record["title"] for record in dashboard.filter_jobs(records, arrangement="remote")], ["Python Developer", "Werkstudent Data Science"])
        self.assertEqual([record["title"] for record in dashboard.filter_jobs(records, assessment="excluded")], ["Senior Data Platform Engineer"])

    def test_sorting_orders_by_score_and_discovery_date(self):
        records = self.records()
        scores = [record["score"] for record in dashboard.filter_jobs(records, sort="score_desc") if record["score"] is not None]
        self.assertEqual(scores, sorted(scores, reverse=True))
        ascending = [record["score"] for record in dashboard.filter_jobs(records, sort="score_asc") if record["score"] is not None]
        self.assertEqual(ascending, sorted(ascending))
        newest = dashboard.filter_jobs(records, sort="newest")
        self.assertEqual(newest[0]["title"], FIXTURES[-1]["title"])

    def test_source_statistics_describe_each_source(self):
        statistics = {item["source"]: item for item in dashboard.source_statistics(self.records())}
        self.assertEqual(statistics["adzuna"]["jobs"], 2)
        self.assertEqual(statistics["himalayas"]["remote"], 1)
        self.assertEqual(statistics["ba"]["excluded"], 1)
        self.assertIn("Junior Data Analyst", statistics["adzuna"]["samples"])


class HttpTests(DashboardFixture):
    def test_all_pages_load(self):
        for path, marker in (("/", "Overview"), ("/jobs", "Jobs"), ("/saved", "Saved jobs"), ("/applications", "Applications"), ("/history", "Search history"), ("/sources", "Sources and statistics"), ("/search", "Search public job sources")):
            with self.subTest(path=path):
                status, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn(marker, body)
                self.assertIn("Job Agent", body)

    def test_jobs_page_shows_existing_data_and_filters(self):
        status, body = self.get("/jobs")
        self.assertEqual(status, 200)
        for fixture in FIXTURES:
            if fixture["title"] == "Senior Data Platform Engineer":
                continue
            self.assertIn(fixture["title"], body)
        self.assertNotIn("Senior Data Platform Engineer", body)
        _, shown = self.get("/jobs?include_excluded=1")
        self.assertIn("Senior Data Platform Engineer", shown)
        _, filtered = self.get("/jobs?q=Python&source=himalayas")
        self.assertIn("Python Developer", filtered)
        self.assertNotIn("Office Manager", filtered)
        _, high_scores = self.get("/jobs?min_score=70")
        self.assertNotIn("Office Manager", high_scores)
        self.assertIn("Junior Data Analyst", high_scores)

    def test_job_detail_shows_evaluation_source_link_and_requirements(self):
        job_id = self.ids["Junior Data Analyst"]
        status, body = self.get("/jobs/%s" % job_id)
        self.assertEqual(status, 200)
        self.assertIn("Fit evaluation", body)
        self.assertIn("Confirmed skill: Python", body)
        self.assertIn("Preferred requirement could not be verified from the profile: Excel", body)
        self.assertIn("https://example.test/1", body)
        self.assertIn("Original posting", body)
        self.assertIn("<th>Requirement</th>", body)
        self.assertIn("Python", body)
        self.assertIn("Generate tailored CV", body)

    def test_job_detail_shows_the_internal_database_id(self):
        job_id = self.ids["Python Developer"]
        status, body = self.get("/jobs/%s" % job_id)
        self.assertEqual(status, 200)
        self.assertIn('<span class="id-chip"', body)
        self.assertIn("#%s" % job_id, body)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "list"])
        row = next(line for line in output.getvalue().splitlines() if "Python Developer" in line)
        self.assertEqual(row.split()[0], str(job_id))
        stored = self.store().connection.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(stored["id"], job_id)

    def test_save_and_reject_update_the_shared_status(self):
        job_id = self.ids["Junior Data Analyst"]
        status, url, body = self.post("/jobs/%s/decision" % job_id, {"action": "save", "next": "/jobs/%s" % job_id})
        self.assertEqual(status, 200)
        self.assertIn("Job %s saved." % job_id, url + body)
        saved = self.store().connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"]
        self.assertEqual(saved, "saved")
        _, saved_page = self.get("/saved")
        self.assertIn("Junior Data Analyst", saved_page)
        self.post("/jobs/%s/decision" % job_id, {"action": "reject", "reason": "too far", "next": "/saved"})
        row = self.store().connection.execute("SELECT status,rejection_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "rejected_by_user")
        self.assertEqual(row["rejection_reason"], "too far")
        _, hidden = self.get("/jobs")
        self.assertNotIn("Junior Data Analyst", hidden)
        _, shown = self.get("/jobs?include_rejected=1")
        self.assertIn("Junior Data Analyst", shown)
        _, rejected_filter = self.get("/jobs?status=rejected_by_user")
        self.assertIn("Junior Data Analyst", rejected_filter)

    def test_application_tracking_from_detail_and_overview_form(self):
        job_id = self.ids["Python Developer"]
        status, url, body = self.post("/jobs/%s/application" % job_id, {"status": "applied", "date": "2026-09-20", "notes": "sent by email"})
        self.assertEqual(status, 200)
        self.assertIn("recorded as applied", url + body)
        row = self.store().applications()[0]
        self.assertEqual((row["job_id"], row["status"], row["application_date"], row["notes"]), (job_id, "applied", "2026-09-20", "sent by email"))
        _, applications = self.get("/applications")
        self.assertIn("Python Developer", applications)
        self.assertIn("Applied", applications)
        other = self.ids["Werkstudent Data Science"]
        self.post("/applications", {"job_id": other, "status": "interview", "notes": "call booked"})
        rows = {row["job_id"]: row["status"] for row in self.store().applications()}
        self.assertEqual(rows[other], "interview")

    def test_invalid_application_status_is_reported(self):
        code, _, body = self.post("/jobs/%s/application" % self.ids["Python Developer"], {"status": "hired"})
        self.assertEqual(code, 400)
        self.assertIn("Invalid application status", body)

    def test_cv_generation_and_download(self):
        job_id = self.ids["Junior Data Analyst"]

        def fake_generate(job, profile, output):
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"%PDF-1.4 fake dashboard cv")
            return Path(output), ["projects", "skills"]

        with patch("job_agent.webapp.generate", side_effect=fake_generate):
            status, url, body = self.post("/jobs/%s/cv" % job_id, {})
        self.assertEqual(status, 200)
        self.assertIn("CV draft created", url + body)
        versions = self.store().cv_versions(job_id)
        self.assertEqual(len(versions), 1)
        self.assertTrue(Path(versions[0]["path"]).exists())
        _, pdf = self.get("/jobs/%s/cv" % job_id)
        self.assertIn("fake dashboard cv", pdf)

    def test_cv_failure_is_reported_without_crashing(self):
        def exploding_generate(job, profile, output):
            raise RuntimeError("pdflatex was not found on PATH.")

        with patch("job_agent.webapp.generate", side_effect=exploding_generate):
            status, url, body = self.post("/jobs/%s/cv" % self.ids["Python Developer"], {})
        self.assertEqual(status, 200)
        self.assertIn("CV generation failed", body)
        self.assertEqual(self.store().cv_versions(self.ids["Python Developer"]), [])

    def test_missing_job_and_unknown_routes_are_404(self):
        code, body = self.get_error("/jobs/999999")
        self.assertEqual(code, 404)
        self.assertIn("was not found", body)
        self.assertEqual(self.get_error("/nope")[0], 404)
        self.assertEqual(self.post("/jobs/999999/decision", {"action": "save"})[0], 404)

    def test_cross_origin_post_is_rejected(self):
        code, _, body = self.post("/jobs/%s/decision" % self.ids["Junior Data Analyst"], {"action": "save"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        self.assertIn("Cross-origin", body)
        status = self.store().connection.execute("SELECT status FROM jobs WHERE id=?", (self.ids["Junior Data Analyst"],)).fetchone()["status"]
        self.assertEqual(status, "discovered")

    def test_search_runs_in_background_and_stores_new_jobs(self):
        before = len(self.store().list_jobs())
        status, url, body = self.post("/search", {"mode": "query", "query": "Junior BI Analyst", "source": "adzuna", "location": "Aachen"})
        self.assertEqual(status, 200)
        self.assertIn("Search started", url + body)
        deadline = time.time() + 30
        state = {}
        while time.time() < deadline:
            _, payload = self.get("/search/status.json")
            state = json.loads(payload)
            if not state["running"]:
                break
            time.sleep(0.2)
        self.assertFalse(state["running"], "search did not finish")
        self.assertIn("Search finished", state["message"])
        self.assertEqual(state["found"], 1)
        self.assertEqual(len(self.store().list_jobs()), before + 1)
        self.assertEqual(self.adapters["adzuna"].calls, [("Junior BI Analyst", "Aachen")])
        events = [row["event"] for row in self.store().history()]
        self.assertIn("search_completed", events)

    def test_default_view_hides_rejected_and_excluded_jobs(self):
        excluded_id = self.ids["Senior Data Platform Engineer"]
        rejected_id = self.ids["Office Manager"]
        self.post("/jobs/%s/decision" % rejected_id, {"action": "reject", "reason": "role mismatch"})
        status, default_body = self.get("/jobs")
        self.assertEqual(status, 200)
        self.assertNotIn("Senior Data Platform Engineer", default_body)
        self.assertNotIn("Office Manager", default_body)
        _, excluded_only = self.get("/jobs?assessment=excluded")
        self.assertIn("Senior Data Platform Engineer", excluded_only)
        self.assertNotIn("Office Manager", excluded_only)
        _, rejected_only = self.get("/jobs?status=rejected_by_user")
        self.assertIn("Office Manager", rejected_only)
        self.assertNotIn("Senior Data Platform Engineer", rejected_only)
        self.assertEqual(self.store().connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], len(FIXTURES))
        self.assertEqual(self.store().connection.execute("SELECT status FROM jobs WHERE id=?", (rejected_id,)).fetchone()["status"], "rejected_by_user")
        self.assertEqual(self.store().connection.execute("SELECT status FROM jobs WHERE id=?", (excluded_id,)).fetchone()["status"], "discovered")

    def test_configured_search_runs_every_configured_query_across_all_sources(self):
        config = load_config(self.config_path)
        expected = config["search_queries"]["primary"] + config["search_queries"]["secondary"]
        before = len(self.store().list_jobs())
        status, url, body = self.post("/search", {"mode": "configured"})
        self.assertEqual(status, 200)
        self.assertIn("Search started", url + body)
        deadline = time.time() + 60
        state = {}
        while time.time() < deadline:
            state = json.loads(self.get("/search/status.json")[1])
            if not state["running"]:
                break
            time.sleep(0.2)
        self.assertFalse(state["running"], "configured search did not finish")
        self.assertEqual(state["mode"], "configured")
        self.assertEqual(state["queries_total"], len(expected) * len(self.adapters))
        for name, adapter in self.adapters.items():
            with self.subTest(source=name):
                self.assertEqual([call[0] for call in adapter.calls], expected)
                self.assertEqual({call[1] for call in adapter.calls}, {None})
        self.assertEqual(len(self.store().list_jobs()), before + len(expected))
        self.assertIn("Search finished", state["message"])

    def test_search_requires_a_query(self):
        code, _, body = self.post("/search", {"mode": "query", "query": "  "})
        self.assertEqual(code, 400)
        self.assertIn("Enter a query", body)

    def test_dashboard_and_cli_share_the_same_database(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "save", str(self.ids["Python Developer"])])
        self.assertIn("updated", output.getvalue())
        _, saved_page = self.get("/saved")
        self.assertIn("Python Developer", saved_page)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli_main(["--profile", str(self.profile_path), "--config", str(self.config_path), "--database", str(self.database), "list"])
        self.assertIn("Python Developer", output.getvalue())


class SearchSkipTests(DashboardFixture):
    """Dashboard searches keep running without Adzuna credentials and still report rejected ones."""

    def wait_for_search(self, manager):
        deadline = time.time() + 30
        while time.time() < deadline:
            state = manager.snapshot()
            if not state["running"]:
                return state
            time.sleep(0.2)
        self.fail("search did not finish")

    def test_search_without_adzuna_credentials_continues_and_reports_the_skip(self):
        expected = load_config(self.config_path)["search_queries"]["primary"] + load_config(self.config_path)["search_queries"]["secondary"]
        adapters = {name: StubAdapter([], name) for name in ("nomado24", "himalayas", "ba")}
        manager = SearchManager(profile_path=self.profile_path, config_path=self.config_path, database_path=self.database, sources_factory=discovery.default_sources)
        with patch("job_agent.discovery.AdzunaSource", side_effect=AdzunaError("Missing Adzuna credentials: ADZUNA_APP_ID, ADZUNA_APP_KEY")), patch("job_agent.discovery.Nomado24Source", lambda *_: adapters["nomado24"]), patch("job_agent.discovery.HimalayasSource", lambda *_: adapters["himalayas"]), patch("job_agent.discovery.BASource", lambda *_: adapters["ba"]):
            started, message = manager.start(mode="configured")
            self.assertTrue(started, message)
            state = self.wait_for_search(manager)
        self.assertIn("Adzuna skipped: ADZUNA_APP_ID and ADZUNA_APP_KEY are not set; no Adzuna search was performed.", state["message"])
        self.assertTrue(any("Adzuna skipped" in line for line in state["log"]))
        self.assertNotIn("source error(s)", state["message"])
        for name, adapter in adapters.items():
            with self.subTest(source=name):
                self.assertEqual([call[0] for call in adapter.calls], expected)

    def test_rejected_adzuna_credentials_are_reported_as_a_source_error(self):
        class RejectedAdapter:
            def __init__(self): self.calls = []
            def search(self, query, location=None): self.calls.append(query); raise AdzunaError("Adzuna request failed with HTTP status 401.")
        rejected = RejectedAdapter()
        adapters = {name: StubAdapter([], name) for name in ("nomado24", "himalayas", "ba")}
        manager = SearchManager(profile_path=self.profile_path, config_path=self.config_path, database_path=self.database, sources_factory=lambda root: {"adzuna": (rejected, True), "nomado24": (adapters["nomado24"], True), "himalayas": (adapters["himalayas"], False), "ba": (adapters["ba"], True)})
        started, message = manager.start(mode="configured")
        self.assertTrue(started, message)
        state = self.wait_for_search(manager)
        self.assertIn("Adzuna request failed with HTTP status 401.", "; ".join(state["errors"]))
        self.assertIn("source error(s)", state["message"])
        self.assertNotIn("Adzuna skipped", state["message"])
        for name, adapter in adapters.items():
            with self.subTest(source=name):
                self.assertTrue(adapter.calls)


class PresentationTests(DashboardFixture):
    """Search-page usability and timestamp presentation."""

    ISO = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    PRETTY = r"\d{2}-\d{2}-\d{4}, \d{2}:\d{2}"

    def test_timestamp_helper_formats_stored_values(self):
        self.assertEqual(webui.timestamp("2026-10-15T14:02:33.123456+00:00"), "15-10-2026, 14:02")
        self.assertEqual(webui.timestamp("2026-10-15T14:02:33Z"), "15-10-2026, 14:02")
        self.assertEqual(webui.timestamp("2026-09-20"), "20-09-2026")
        self.assertEqual(webui.timestamp("2026-09-20 08:05:00"), "20-09-2026, 08:05")
        self.assertEqual(webui.timestamp(""), "")
        self.assertEqual(webui.timestamp(None), "")
        self.assertEqual(webui.timestamp("not a date"), "not a date")

    def test_job_detail_explains_the_requirement_kind_and_formats_timestamps(self):
        status, body = self.get("/jobs/%s" % self.ids["Junior Data Analyst"])
        self.assertEqual(status, 200)
        self.assertIn("<th>Requirement</th>", body)
        self.assertIn("Stated as", body)
        self.assertIn("It comes from the listing, not from your profile.", body)
        self.assertIn('class="badge kind"', body)
        self.assertIn("Discovered (UTC)", body)
        self.assertIn("Last seen (UTC)", body)
        self.assertRegex(body, self.PRETTY)
        self.assertNotRegex(body, self.ISO)

    def test_job_list_and_history_use_the_readable_timestamp_format(self):
        for path, marker in (("/jobs", "Discovered (UTC)"), ("/history", "When (UTC)")):
            with self.subTest(path=path):
                status, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn(marker, body)
                self.assertRegex(body, self.PRETTY)
                self.assertNotRegex(body, self.ISO)

    def test_application_and_source_pages_use_the_readable_timestamp_format(self):
        job_id = self.ids["Junior Data Analyst"]
        status, _, _ = self.post("/jobs/%s/application" % job_id, {"status": "applied", "date": "2026-09-20", "notes": "sent by email"})
        self.assertEqual(status, 200)
        _, body = self.get("/applications")
        self.assertIn("20-09-2026", body)
        self.assertIn("Updated (UTC)", body)
        self.assertEqual(self.store().connection.execute("SELECT application_date FROM applications WHERE job_id=?", (job_id,)).fetchone()["application_date"], "2026-09-20")
        _, sources = self.get("/sources")
        self.assertIn("Newest (UTC)", sources)
        self.assertRegex(sources, self.PRETTY)

    def test_search_page_scrolls_the_progress_log_and_keeps_the_start_notice(self):
        status, body = self.get("/search?notice=Search+started.")
        self.assertEqual(status, 200)
        self.assertIn("Search started.", body)
        self.assertIn('id="search-notice"', body)
        self.assertIn('class="log small" id="search-log"', body)
        self.assertIn("overflow-y:auto", body)
        self.assertIn("Keeps the newest 200 lines", body)
        self.assertIn("scrollHeight", body)
        self.assertIn("formatTimestamp", body)
        self.assertIn("Search failed", body)
        self.assertIn("6000", body)

    def test_search_status_endpoint_keeps_the_fields_the_page_uses(self):
        status, payload = self.get("/search/status.json")
        self.assertEqual(status, 200)
        state = json.loads(payload)
        for key in ("running", "message", "finished_at", "started_at", "log", "errors"):
            with self.subTest(key=key):
                self.assertIn(key, state)


if __name__ == "__main__":
    unittest.main()
