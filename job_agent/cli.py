from __future__ import annotations

import argparse
import errno
import json
import os
import sys
from pathlib import Path

from .adzuna import AdzunaError, AdzunaSource
from .ba import BAError, BASource
from .cv import generate
from .discovery import collect, store_jobs
from .maintenance import refresh_evaluations
from .permissions import require_external_approval
from .profile import ValidationError, load_config, load_profile
from .storage import Store
from .himalayas import HimalayasError, HimalayasSource
from .nomado24 import Nomado24Error, Nomado24Source

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "data" / "profile.json"
DEFAULT_CONFIG = ROOT / "data" / "search_config.json"
DEFAULT_DB = ROOT / "data" / "job_agent.sqlite3"


def configure_output():
    """Keep non-ASCII job titles printable when output is piped or redirected."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _closed_pipe(exc: OSError) -> bool:
    """Detect a reader that closed the pipe early; Windows reports EINVAL where POSIX reports EPIPE."""
    if exc.errno not in (errno.EPIPE, errno.EINVAL):
        return False
    try:
        sys.stdout.flush()
    except OSError:
        return True
    return isinstance(exc, BrokenPipeError)


def paths(args): return load_profile(args.profile), load_config(args.config), Store(args.database)
def print_evaluation(e):
    print(f"Fit: {e['score']}/100 - {e['assessment']} (a profile/preference match, not hiring probability)")
    for label, key in (("Strong matches", "strong_matches"), ("Potential gaps", "potential_gaps"), ("Important concerns", "concerns"), ("Uncertainties", "uncertainties")):
        print(f"\n{label}:"); print("\n".join(f"- {x}" for x in e[key]) or "- None")


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Local-first Job Searching Agent. It never submits applications.")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE)); parser.add_argument("--config", default=str(DEFAULT_CONFIG)); parser.add_argument("--database", default=str(DEFAULT_DB))
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("validate")
    ingest = subs.add_parser("ingest"); ingest.add_argument("file", help="JSON list of public job records")
    search = subs.add_parser("search"); search.add_argument("query", nargs="?", help="Public search query; no personal data is transmitted"); search.add_argument("--query", dest="query_option", help="Specific public search query"); search.add_argument("--location", help="Optional source location filter"); search.add_argument("--source", choices=("adzuna", "nomado24", "himalayas", "ba"), help="Search only this source")
    listing = subs.add_parser("list"); listing.add_argument("--include-rejected", action="store_true")
    view = subs.add_parser("view"); view.add_argument("job_id", type=int)
    for name in ("save", "reject"):
        item = subs.add_parser(name); item.add_argument("job_id", type=int); item.add_argument("--reason")
    app = subs.add_parser("application"); app.add_argument("job_id", type=int); app.add_argument("status"); app.add_argument("--date"); app.add_argument("--notes")
    subs.add_parser("applications"); subs.add_parser("history")
    permission = subs.add_parser("permission-check", help="Record a one-time approval check; it does not transmit anything.")
    permission.add_argument("action"); permission.add_argument("destination"); permission.add_argument("data_summary"); permission.add_argument("--approve", action="store_true")
    tailor = subs.add_parser("tailor"); tailor.add_argument("job_id", type=int); tailor.add_argument("--output")
    subs.add_parser("re-evaluate", help="Re-run the current evaluator over stored jobs; no search is performed")
    dash = subs.add_parser("dashboard", help="Serve the localhost web dashboard for the same local data"); dash.add_argument("--host", default="127.0.0.1"); dash.add_argument("--port", type=int, default=8770)
    args = parser.parse_args(argv)
    store = None
    try:
        if args.command == "dashboard":
            from .webapp import serve
            serve(host=args.host, port=args.port, profile=args.profile, config=args.config, database=args.database)
            return
        profile, config, store = paths(args)
        if args.command == "validate":
            master_cv = config.get("master_cv_path")
            if master_cv and not Path(master_cv).exists(): print(f"Profile and configuration are valid. Master CV path needs attention: {master_cv}")
            else: print("Profile and configuration are valid.")
            return
        if args.command in {"ingest", "search"}:
            search_count = new_count = known_count = excluded_count = 0
            if args.command == "ingest": raw_jobs = json.loads(Path(args.file).read_text(encoding="utf-8"))
            else:
                manual_query = args.query_option or args.query
                source = AdzunaSource(ROOT / ".env"); store.audit("search_started")
                source_specs = {"adzuna": (source, True), "nomado24": (Nomado24Source(), True), "himalayas": (HimalayasSource(), False), "ba": (BASource(), True)}
                queries = None if manual_query else config["search_queries"]["primary"] + config["search_queries"]["secondary"]
                outcome = collect(source_specs, queries=queries, query=manual_query, source=args.source, location=args.location)
                raw_jobs = outcome.jobs; search_count = outcome.queries_run
                store.audit("search_completed", details=f"{len(raw_jobs)} public results")
            if args.command == "search" and not raw_jobs:
                print("No jobs found.")
            for record in store_jobs(store, profile, config, raw_jobs):
                print(f"{record['label']} job {record['job_id']}: {record['title']} ({record['score']}/100)")
                if args.command == "search":
                    if record["created"]: new_count += 1
                    else: known_count += 1
                    if record["excluded"]: excluded_count += 1
            if args.command == "search":
                print(f"Search complete.\nQueries searched: {search_count}\nUnique jobs found: {len(raw_jobs)}\nNew: {new_count}\nKnown: {known_count}\nExcluded: {excluded_count}")
        elif args.command == "re-evaluate":
            summary = refresh_evaluations(store, profile, config)
            if summary["changed"]:
                store.audit("evaluations_refreshed", details=f"{summary['examined']} examined, {summary['changed']} updated, {summary['newly_excluded']} newly excluded")
            print(f"Re-evaluated {summary['examined']} stored job(s): {summary['changed']} updated, {summary['unchanged']} unchanged.")
            print(f"Newly excluded: {summary['newly_excluded']} | Score or category changed: {summary['score_changed']}")
            for source, item in sorted(summary["sources"].items(), key=lambda pair: (-pair[1]["examined"], pair[0])):
                print(f"  {source}: {item['examined']} examined, {item['changed']} updated, {item['newly_excluded']} newly excluded")
        elif args.command == "list":
            for row in store.list_jobs(args.include_rejected): print(f"{row['id']:>3}  {json.loads(row['evaluation'])['score']:>3}/100  {row['status']:<18} {json.loads(row['payload'])['title']}")
        elif args.command == "view":
            job, ev, row = store.get_job(args.job_id); print(f"{job.title}\nCompany: {job.company or 'unknown'}\nLocation: {job.location or 'unknown'}\nURL: {job.source_url or 'unknown'}\n"); print_evaluation(ev)
        elif args.command in {"save", "reject"}: store.set_decision(args.job_id, args.command, args.reason); print(f"Job {args.job_id} updated.")
        elif args.command == "application": store.update_application(args.job_id, args.status, args.date, args.notes); print("Application status recorded. No application was submitted.")
        elif args.command == "applications":
            for row in store.applications(): print(f"{row['job_id']}  {row['status']}  {json.loads(row['payload'])['title']}")
        elif args.command == "history":
            for row in store.history(): print(f"{row['created_at']}  {row['event']}  job={row['job_id'] or '-'}")
        elif args.command == "permission-check":
            approval = require_external_approval(action=args.action, destination=args.destination, data_summary=args.data_summary, approved=args.approve)
            store.audit("external_action_approved", details=json.dumps(approval)); print("Specific approval recorded locally. No data was transmitted.")
        elif args.command == "tailor":
            job, _, _ = store.get_job(args.job_id); output = args.output or str(ROOT / "output" / f"cv_job_{args.job_id}.pdf"); path, facts = generate(job, profile, output); store.save_cv(args.job_id, str(path), facts); print(f"Local truthful CV draft created: {path}")
    except (AdzunaError, Nomado24Error, HimalayasError, BAError) as exc:
        parser.error(str(exc))
    except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    except OSError as exc:
        if _closed_pipe(exc):
            raise
        parser.error(str(exc))
    finally:
        if store is not None: store.close()

if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
    except OSError as exc:
        if not _closed_pipe(exc):
            raise
        try:
            sys.stdout.flush()
        except OSError:
            pass
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(1)

