"""Maintenance helpers for stored jobs."""
from __future__ import annotations

import json

from .ba import BASource, _map
from .evaluator import evaluate
from .models import Job
from .profile import Profile

LOCATION_METADATA_KEYS = ("postal_code", "street", "region", "country", "latitude", "longitude")


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


def refresh_ba_locations(store, profile: Profile, config: dict, *, apply: bool = False, source=None) -> dict:
    """Refresh only missing BA locations from stored BA references.

    Dry-run by default. Successful refreshes replace only the source-derived location and location
    metadata, then re-evaluate the job; decisions, applications, CV versions and audit history are
    left intact. Individual detail failures are reported and do not stop the remaining records.
    """
    source = source or BASource()
    summary = {
        "examined": 0,
        "already_located": 0,
        "would_update": 0,
        "updated": 0,
        "locations_recovered": 0,
        "score_changed": 0,
        "newly_excluded": 0,
        "failed": [],
        "unresolved": [],
    }
    for row in store.list_jobs(include_rejected=True):
        payload = json.loads(row["payload"])
        if payload.get("source") != "ba":
            continue
        if str(payload.get("location") or "").strip():
            summary["already_located"] += 1
            continue
        summary["examined"] += 1
        reference = payload.get("external_job_id")
        if not reference:
            summary["failed"].append({"job_id": row["id"], "reference": None, "error": "missing BA reference"})
            continue
        try:
            detail = source.detail(str(reference))
            mapped = _map({}, detail)
        except Exception as exc:
            summary["failed"].append({"job_id": row["id"], "reference": str(reference), "error": str(exc)})
            continue
        location = str(mapped.get("location") or "").strip()
        if not location:
            summary["unresolved"].append({"job_id": row["id"], "reference": str(reference)})
            continue
        summary["locations_recovered"] += 1
        corrected = Job.from_dict(payload)
        corrected.location = location
        corrected.metadata = {
            **corrected.metadata,
            **{key: mapped.get("metadata", {}).get(key) for key in LOCATION_METADATA_KEYS},
        }
        fresh = evaluate(corrected, profile, config).to_dict()
        stored_evaluation = json.loads(row["evaluation"]) if row["evaluation"] else {}
        if stored_evaluation.get("score") != fresh.get("score") or stored_evaluation.get("assessment") != fresh.get("assessment"):
            summary["score_changed"] += 1
        if fresh.get("excluded") and not stored_evaluation.get("excluded"):
            summary["newly_excluded"] += 1
        if not apply:
            summary["would_update"] += 1
            continue
        try:
            store.save_job(corrected, fresh)
            store.audit(
                "ba_location_refreshed",
                row["id"],
                "BA reference %s -> %s" % (reference, location),
            )
        except Exception as exc:
            summary["failed"].append({"job_id": row["id"], "reference": str(reference), "error": str(exc)})
            continue
        summary["updated"] += 1
    return summary
