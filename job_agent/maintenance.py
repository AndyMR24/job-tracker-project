"""Maintenance helpers that work on already-stored data without contacting any source."""
from __future__ import annotations

import json

from .evaluator import evaluate
from .models import Job
from .profile import Profile


def refresh_evaluations(store, profile: Profile, config: dict) -> dict:
    """Re-run the current evaluator over stored jobs.

    Listing facts, user decisions, application records and discovery history are left untouched;
    only the stored evaluation of a job is replaced, and only when the fresh evaluation differs
    from the stored one. No job is fetched from any source.
    """
    summary = {"examined": 0, "changed": 0, "unchanged": 0, "newly_excluded": 0, "score_changed": 0, "sources": {}}
    for row in store.list_jobs(include_rejected=True):
        payload = json.loads(row["payload"])
        stored = json.loads(row["evaluation"]) if row["evaluation"] else None
        source = payload.get("source") or "unknown"
        counters = summary["sources"].setdefault(source, {"examined": 0, "changed": 0, "newly_excluded": 0, "score_changed": 0})
        fresh = evaluate(Job.from_dict(payload), profile, config).to_dict()
        summary["examined"] += 1
        counters["examined"] += 1
        if stored == fresh:
            summary["unchanged"] += 1
            continue
        newly_excluded = bool(fresh["excluded"]) and not bool((stored or {}).get("excluded"))
        score_changed = stored is None or stored.get("score") != fresh["score"] or stored.get("assessment") != fresh["assessment"]
        if store.replace_evaluation(row["id"], fresh):
            summary["changed"] += 1
            counters["changed"] += 1
        if newly_excluded:
            summary["newly_excluded"] += 1
            counters["newly_excluded"] += 1
        if score_changed:
            summary["score_changed"] += 1
            counters["score_changed"] += 1
    return summary
