"""Local HTTP dashboard for the job searching agent.

The dashboard is a second interface to the same application logic: it reads and writes the same
SQLite database through `Store`, reuses normalization/evaluation through `discovery.store_jobs`,
reuses `cv.generate` for drafts, and exposes exactly the decisions the CLI offers. It never submits
applications, never contacts employers and never transmits candidate data anywhere.
"""
from __future__ import annotations

import argparse
import json
import threading
import traceback
import urllib.parse
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import dashboard, discovery, webui
from .cv import generate, versioned_output_path
from .profile import load_config, load_profile
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "data" / "profile.json"
DEFAULT_CONFIG = ROOT / "data" / "search_config.json"
DEFAULT_DB = ROOT / "data" / "job_agent.sqlite3"
DEFAULT_OUTPUT = ROOT / "output"
PAGE_SIZE = 25
PAGE_SIZES = webui.PAGE_SIZES


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SearchManager:
    """Runs at most one public search at a time in a background thread and reports progress."""

    def __init__(self, *, profile_path, config_path, database_path, sources_factory=discovery.default_sources):
        self.profile_path = Path(profile_path)
        self.config_path = Path(config_path)
        self.database_path = Path(database_path)
        self.sources_factory = sources_factory
        self._lock = threading.Lock()
        self._state = {"running": False, "mode": None, "query": None, "source": None, "location": None, "started_at": None, "finished_at": None, "queries_done": 0, "queries_total": 0, "found": 0, "stored": 0, "new": 0, "known": 0, "excluded": 0, "errors": [], "log": [], "message": "No search has been started from the dashboard yet."}

    def snapshot(self) -> dict:
        with self._lock:
            state = dict(self._state)
            state["log"] = list(self._state["log"])
            state["errors"] = list(self._state["errors"])
        return state

    def _log(self, message: str) -> None:
        with self._lock:
            self._state["log"].append(message)
            del self._state["log"][:-200]

    def start(self, *, mode: str = "query", query=None, source=None, location=None) -> tuple[bool, str]:
        with self._lock:
            if self._state["running"]:
                return False, "A search is already running."
            self._state.update({"running": True, "mode": mode, "query": query, "source": source, "location": location, "started_at": timestamp(), "finished_at": None, "queries_done": 0, "queries_total": 0, "found": 0, "stored": 0, "new": 0, "known": 0, "excluded": 0, "errors": [], "log": [], "message": "Search started."})
        threading.Thread(target=self._run, args=(mode, query, source, location), name="dashboard-search", daemon=True).start()
        return True, "Search started."

    def _progress(self, done: int, total: int, message: str) -> None:
        with self._lock:
            self._state["queries_done"] = done
            self._state["queries_total"] = total
            self._state["log"].append(message)
            del self._state["log"][:-200]

    def _stored(self, index: int, total: int, record: dict) -> None:
        with self._lock:
            self._state["stored"] = index
            self._state["new" if record["created"] else "known"] += 1
            if record["excluded"]:
                self._state["excluded"] += 1
            self._state["log"].append("%s job %s: %s (%s/100)" % (record["label"], record["job_id"], record["title"][:70], record["score"]))

    def _run(self, mode, query, source, location) -> None:
        store = None
        try:
            profile = load_profile(self.profile_path)
            config = load_config(self.config_path)
            store = Store(self.database_path)
            store.audit("search_started", details="dashboard")
            queries = None if mode == "query" else config["search_queries"]["primary"] + config["search_queries"]["secondary"]
            outcome = discovery.collect(self.sources_factory(ROOT), queries=queries, query=query, source=source, location=location, tolerate_errors=True, progress=self._progress)
            for note in outcome.skipped:
                self._log(note)
            if not outcome.jobs:
                self._log("No public listings were returned.")
            records = discovery.store_jobs(store, profile, config, outcome.jobs, on_job=self._stored)
            store.audit("search_completed", details="%s public results (dashboard)" % len(outcome.jobs))
            with self._lock:
                summary = "Search finished: %s public result(s), %s stored (%s new, %s known, %s excluded)" % (len(outcome.jobs), len(records), self._state["new"], self._state["known"], self._state["excluded"])
                if outcome.errors:
                    summary += " - %s source error(s)" % len(outcome.errors)
                if outcome.skipped:
                    summary += " - %s" % "; ".join(outcome.skipped)
                self._state.update({"running": False, "finished_at": timestamp(), "found": len(outcome.jobs), "stored": len(records), "errors": list(outcome.errors), "message": summary})
        except Exception as exc:
            self._log("Search failed: %s" % exc)
            with self._lock:
                self._state.update({"running": False, "finished_at": timestamp(), "message": "Search failed: %s" % exc, "errors": list(self._state["errors"]) + [str(exc)]})
        finally:
            if store is not None:
                store.close()


class Dashboard:
    """Maps HTTP routes onto the existing application functionality."""

    def __init__(self, *, profile_path, config_path, database_path, output_dir, sources_factory=discovery.default_sources):
        self.profile_path = Path(profile_path)
        self.config_path = Path(config_path)
        self.database_path = Path(database_path)
        self.output_dir = Path(output_dir)
        self.search = SearchManager(profile_path=self.profile_path, config_path=self.config_path, database_path=self.database_path, sources_factory=sources_factory)

    @contextmanager
    def _store(self):
        store = Store(self.database_path)
        try:
            yield store
        finally:
            store.close()

    def _records(self, store) -> list[dict]:
        return [dashboard.job_record(row) for row in store.list_jobs(include_rejected=True)]

    def _html(self, status: int, body: str):
        return status, {"Content-Type": "text/html; charset=utf-8"}, body.encode("utf-8")

    def _page(self, title: str, active: str, content: str, params: dict | None = None, *, notice=None, error=None):
        params = params or {}
        return self._html(200, webui.page(title, active, content, notice=notice or params.get("notice"), error=error or params.get("error"), database=str(self.database_path)))

    def _redirect(self, location: str, *, notice=None, error=None):
        values = {}
        if notice:
            values["notice"] = notice
        if error:
            values["error"] = error
        if values:
            location += ("&" if "?" in location else "?") + urllib.parse.urlencode(values)
        return 303, {"Location": location}, b""

    def _safe_next(self, value, default: str) -> str:
        candidate = (value or "").strip()
        return candidate if candidate.startswith("/") and not candidate.startswith("//") else default

    def handle(self, method: str, path: str, params: dict, form: dict):
        try:
            return self._get(path, params) if method == "GET" else self._post(path, form)
        except KeyError as exc:
            return self._html(404, webui.error_page(404, str(exc), str(self.database_path)))
        except ValueError as exc:
            return self._html(400, webui.error_page(400, str(exc), str(self.database_path)))

    def _get(self, path: str, params: dict):
        if path in ("/", "/index.html"):
            return self._overview(params)
        if path == "/jobs":
            return self._jobs(params)
        if path == "/saved":
            return self._saved(params)
        if path == "/applications":
            return self._applications(params)
        if path == "/history":
            return self._history(params)
        if path == "/sources":
            return self._sources(params)
        if path == "/search":
            return self._search(params)
        if path == "/search/status.json":
            return 200, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}, json.dumps(self.search.snapshot()).encode("utf-8")
        if path == "/favicon.ico":
            return 204, {}, b""
        if path.startswith("/jobs/"):
            parts = path.strip("/").split("/")
            job_id = as_int(parts[1], -1)
            if len(parts) == 2:
                return self._job_detail(job_id, params)
            if len(parts) == 3 and parts[2] == "cv":
                return self._job_cv(job_id)
        return self._html(404, webui.error_page(404, "Unknown page: %s" % path, str(self.database_path)))

    def _post(self, path: str, form: dict):
        if path == "/applications":
            return self._application_form(form)
        if path == "/search":
            return self._start_search(form)
        if path.startswith("/jobs/"):
            parts = path.strip("/").split("/")
            job_id = as_int(parts[1], -1)
            if len(parts) == 3 and parts[2] == "decision":
                return self._decide(job_id, form)
            if len(parts) == 3 and parts[2] == "application":
                return self._application(job_id, form, redirect_to="/jobs/%s" % job_id)
            if len(parts) == 3 and parts[2] == "cv":
                return self._tailor(job_id)
        return self._html(404, webui.error_page(404, "Unknown action: %s" % path, str(self.database_path)))

    def _overview(self, params: dict):
        with self._store() as store:
            records = self._records(store)
            applications = store.applications()
            history = store.history()
        search_events = dashboard.audit_rows(history, events=("search_started", "search_completed"))
        summary = dashboard.summary(records, applications, search_events)
        bands = summary["by_band"]
        cards = [("Jobs discovered", summary["total"]), ("Recommended", bands.get("recommended", 0)), ("Borderline", bands.get("borderline", 0)), ("Excluded", bands.get("excluded", 0)), ("Saved", summary["by_status"].get("saved", 0)), ("Applications", summary["applications"]), ("Average fit score", summary["average_score"] if summary["average_score"] is not None else "-"), ("Searches logged", summary["search_count"])]
        recent = dashboard.filter_jobs(records, sort="newest")[:10]
        shortlist = dashboard.sort_jobs([record for record in records if record["status"] == "saved"], "score_desc")[:8]
        tracked = dashboard.application_rows(applications)[:6]
        content = webui.overview_page(cards, recent, shortlist, tracked, dashboard.source_statistics(records)[:5])
        return self._page("Overview", "/", content, params)

    def _jobs(self, params: dict):
        page_size = as_int(params.get("page_size"), PAGE_SIZE)
        if page_size not in PAGE_SIZES:
            page_size = PAGE_SIZE
        values = {"q": params.get("q", ""), "source": [], "source_filter": params.get("source_filter", "0"), "status": params.get("status", ""), "assessment": params.get("assessment", ""), "arrangement": params.get("arrangement", ""), "min_score": params.get("min_score", ""), "sort": params.get("sort", "score_desc"), "page_size": str(page_size), "include_excluded": params.get("include_excluded", "0"), "include_rejected": params.get("include_rejected", "0"), "include_applied": params.get("include_applied", "0")}
        raw_sources = params.get("source", [])
        if isinstance(raw_sources, str):
            raw_sources = [raw_sources] if raw_sources else []
        selected_sources = [source for source in raw_sources if source]
        with self._store() as store:
            records = self._records(store)
            application_statuses = {row["job_id"]: row["status"] for row in store.applications()}
        available_sources = list(discovery.SOURCE_NAMES)
        for name in dashboard.source_names(records) + selected_sources:
            if name not in available_sources:
                available_sources.append(name)
        if not selected_sources and values["source_filter"] != "1":
            selected_sources = list(available_sources)
        values["source"] = selected_sources
        for record in records:
            record["has_application"] = record["id"] in application_statuses
            record["application_status"] = application_statuses.get(record["id"])
        filtered = dashboard.filter_jobs(records, text=values["q"], source=selected_sources, status=values["status"], assessment=values["assessment"], arrangement=values["arrangement"], min_score=as_int(values["min_score"], 0), include_excluded=values["include_excluded"] == "1", include_rejected=values["include_rejected"] == "1", include_applied=values["include_applied"] == "1", sort=values["sort"])
        page_count = max(1, -(-len(filtered) // page_size))
        page_number = min(max(1, as_int(params.get("page"), 1)), page_count)
        window = filtered[(page_number - 1) * page_size: page_number * page_size]
        content = webui.jobs_page(window, values, available_sources, dashboard.STATUS_ORDER, page_number, page_count, len(filtered))
        return self._page("Jobs", "/jobs", content, params)

    def _job_detail(self, job_id: int, params: dict):
        if job_id < 0:
            raise ValueError("Invalid job id.")
        with self._store() as store:
            job, evaluation, row = store.get_job(job_id)
            record = dashboard.job_record(row)
            trail = dashboard.audit_rows(store.history(), job_id=job_id, limit=25)
            versions = store.cv_versions(job_id)
        return self._page(record["title"], "/jobs", webui.job_detail_page(record, trail, versions), params)

    def _job_cv(self, job_id: int):
        if job_id < 0:
            raise ValueError("Invalid job id.")
        with self._store() as store:
            versions = store.cv_versions(job_id)
        if not versions:
            return self._html(404, webui.error_page(404, "No CV draft has been generated for job %s yet." % job_id, str(self.database_path)))
        path = Path(versions[0]["path"])
        if not path.exists():
            return self._html(404, webui.error_page(404, "The recorded CV draft is missing on disk: %s" % path, str(self.database_path)))
        return 200, {"Content-Type": "application/pdf", "Content-Disposition": 'inline; filename="%s"' % path.name, "Content-Length": str(path.stat().st_size)}, path.read_bytes()

    def _saved(self, params: dict):
        with self._store() as store:
            records = self._records(store)
        saved = dashboard.sort_jobs([record for record in records if record["status"] == "saved"], "score_desc")
        return self._page("Saved jobs", "/saved", webui.saved_page(saved), params)

    def _applications(self, params: dict):
        with self._store() as store:
            records = self._records(store)
            applications = dashboard.application_rows(store.applications())
        tracked = {row["job_id"] for row in applications}
        candidates = dashboard.sort_jobs([record for record in records if record["status"] == "saved" or record["id"] in tracked], "score_desc")[:200]
        return self._page("Applications", "/applications", webui.applications_page(applications, candidates, dashboard.APPLICATION_STATUSES), params)

    def _history(self, params: dict):
        with self._store() as store:
            rows = store.history()
        return self._page("History", "/history", webui.history_page(dashboard.audit_rows(rows, limit=200), dashboard.audit_rows(rows, events=("search_started", "search_completed"), limit=40)), params)

    def _sources(self, params: dict):
        with self._store() as store:
            records = self._records(store)
            applications = store.applications()
        summary = dashboard.summary(records, applications)
        content = webui.sources_page(dashboard.source_statistics(records), summary, load_config(self.config_path))
        return self._page("Sources", "/sources", content, params)

    def _search(self, params: dict):
        with self._store() as store:
            events = dashboard.audit_rows(store.history(), events=("search_started", "search_completed"), limit=30)
        queries = load_config(self.config_path)["search_queries"]
        configured_queries = len(queries["primary"]) + len(queries["secondary"])
        return self._page("Search", "/search", webui.search_page(self.search.snapshot(), events, discovery.SOURCE_NAMES, configured_queries), params)

    def _start_search(self, form: dict):
        mode = (form.get("mode") or "query").strip()
        query = (form.get("query") or "").strip() or None
        location = (form.get("location") or "").strip() or None
        raw_sources = form.get("source", [])
        if isinstance(raw_sources, str):
            raw_sources = [raw_sources] if raw_sources else []
        selected_sources = [source.strip() for source in raw_sources if isinstance(source, str) and source.strip()]
        if not selected_sources:
            if (form.get("source_filter") or "").strip() == "1":
                raise ValueError("Select at least one source.")
            selected_sources = ["adzuna"] if mode == "query" else list(discovery.SOURCE_NAMES)
        unknown = sorted(set(selected_sources) - set(discovery.SOURCE_NAMES))
        if unknown:
            raise ValueError("Unknown source(s): %s" % ", ".join(unknown))
        if mode == "configured":
            query = None
        elif not query:
            raise ValueError("Enter a query to search for.")
        started, message = self.search.start(mode=mode, query=query, source=selected_sources, location=location)
        return self._redirect("/search", notice=message) if started else self._redirect("/search", error=message)

    def _decide(self, job_id: int, form: dict):
        action = (form.get("action") or "").strip()
        if action not in {"save", "reject", "unsave"}:
            raise ValueError("Unknown decision: %s" % action)
        reason = (form.get("reason") or "").strip() or None
        with self._store() as store:
            if action == "unsave":
                store.remove_from_shortlist(job_id)
            else:
                store.set_decision(job_id, action, reason)
        outcome = {"save": "saved", "reject": "rejected", "unsave": "removed from shortlist"}[action]
        return self._redirect(self._safe_next(form.get("next"), "/jobs/%s" % job_id), notice="Job %s %s." % (job_id, outcome))

    def _application(self, job_id: int, form: dict, *, redirect_to: str):
        status = (form.get("status") or "").strip()
        date = (form.get("date") or "").strip() or None
        notes = (form.get("notes") or "").strip() or None
        with self._store() as store:
            store.update_application(job_id, status, date, notes)
        return self._redirect(redirect_to, notice="Application for job %s recorded as %s. Nothing was submitted." % (job_id, status))

    def _application_form(self, form: dict):
        job_id = as_int(form.get("job_id"), 0)
        if job_id <= 0:
            raise ValueError("Select a job to track.")
        return self._application(job_id, form, redirect_to="/applications")

    def _tailor(self, job_id: int):
        profile = load_profile(self.profile_path)
        with self._store() as store:
            job, evaluation, row = store.get_job(job_id)
            output = versioned_output_path(self.output_dir, job_id)
            try:
                path, facts = generate(job, profile, output)
            except (RuntimeError, OSError) as exc:
                return self._redirect("/jobs/%s" % job_id, error="CV generation failed: %s" % exc)
            store.save_cv(job_id, str(path), facts)
        return self._redirect("/jobs/%s" % job_id, notice="Local truthful CV draft created: %s" % path)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "job-agent-dashboard"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str):
        parsed = urllib.parse.urlsplit(self.path)
        parsed_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params = {key: values[-1] for key, values in parsed_params.items()}
        if "source" in parsed_params:
            params["source"] = parsed_params["source"]
        form: dict[str, str] = {}
        if method == "POST":
            length = as_int(self.headers.get("Content-Length"), 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length > 0 else ""
            parsed_form = urllib.parse.parse_qs(body, keep_blank_values=True)
            form = {key: values[-1] for key, values in parsed_form.items()}
            if "source" in parsed_form:
                form["source"] = parsed_form["source"]
            if not self._same_origin():
                payload = webui.error_page(403, "Cross-origin form submissions are rejected.", str(self.server.dashboard.database_path)).encode("utf-8")
                self._send(403, {"Content-Type": "text/html; charset=utf-8"}, payload)
                return
        try:
            status, headers, payload = self.server.dashboard.handle(method, parsed.path, params, form)
        except Exception as exc:
            traceback.print_exc()
            status, headers, payload = 500, {"Content-Type": "text/html; charset=utf-8"}, webui.error_page(500, "Dashboard error: %s" % exc, str(self.server.dashboard.database_path)).encode("utf-8")
        self._send(status, headers, payload)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urllib.parse.urlsplit(origin).netloc == self.headers.get("Host")

    def _send(self, status: int, headers: dict, payload: bytes):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def log_message(self, format, *args):
        if not getattr(self.server, "quiet", False):
            print("[dashboard] %s %s" % (self.address_string(), format % args))


def build_server(*, host: str = "127.0.0.1", port: int = 8770, profile=DEFAULT_PROFILE, config=DEFAULT_CONFIG, database=DEFAULT_DB, output=DEFAULT_OUTPUT, quiet: bool = False, sources_factory=discovery.default_sources) -> ThreadingHTTPServer:
    """Create the HTTP server without serving, so tests can drive it directly."""
    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.daemon_threads = True
    server.dashboard = Dashboard(profile_path=profile, config_path=config, database_path=database, output_dir=output, sources_factory=sources_factory)
    server.quiet = quiet
    return server


def address_of(server: ThreadingHTTPServer, host: str = "127.0.0.1") -> str:
    return "http://%s:%s" % (host, server.server_address[1])


def serve(*, host: str = "127.0.0.1", port: int = 8770, profile=DEFAULT_PROFILE, config=DEFAULT_CONFIG, database=DEFAULT_DB, output=DEFAULT_OUTPUT, quiet: bool = False) -> None:
    """Serve the dashboard until interrupted."""
    server = build_server(host=host, port=port, profile=profile, config=config, database=database, output=output, quiet=quiet)
    print("Job dashboard running at %s/" % address_of(server, host))
    print("Database: %s" % database)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local web dashboard for the job searching agent. It never submits applications.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind; the default keeps the dashboard local")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--database", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true", help="Do not log every request")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, profile=args.profile, config=args.config, database=args.database, output=args.output, quiet=args.quiet)


if __name__ == "__main__":
    main()
