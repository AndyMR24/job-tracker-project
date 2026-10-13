"""Read-only projections over stored jobs, decisions, applications and audit events."""
from __future__ import annotations

import json

STATUS_ORDER = ("discovered", "saved", "applied", "interview", "offer", "rejected_by_company", "withdrawn", "rejected_by_user")
STATUS_LABELS = {"discovered": "Discovered", "saved": "Saved", "rejected_by_user": "Rejected by user", "applied": "Applied", "interview": "Interview", "offer": "Offer", "rejected_by_company": "Rejected by company", "withdrawn": "Withdrawn"}
APPLICATION_STATUSES = ("applied", "interview", "offer", "rejected_by_company", "withdrawn")
BANDS = ("recommended", "borderline", "excluded")
BAND_LABELS = {"recommended": "Recommended", "borderline": "Borderline", "excluded": "Excluded"}
ARRANGEMENTS = ("remote", "hybrid", "onsite", "unknown")
SORTS = {"score_desc": "Score, high to low", "score_asc": "Score, low to high", "newest": "Newest discovery", "oldest": "Oldest discovery", "title": "Title", "company": "Company", "source": "Source", "status": "Status"}
REJECTION_REASONS = ("too senior", "too far", "missing skills", "salary", "role mismatch", "company", "work arrangement", "other")


def job_record(row) -> dict:
    payload = json.loads(row["payload"])
    evaluation = json.loads(row["evaluation"]) if row["evaluation"] else {}
    return {"id": row["id"], "title": payload.get("title") or "(untitled)", "company": payload.get("company"), "location": payload.get("location"), "arrangement": (payload.get("arrangement") or "unknown").lower(), "seniority": payload.get("seniority") or "unknown", "employment_type": payload.get("employment_type"), "salary": payload.get("salary"), "source": payload.get("source") or "unknown", "source_url": payload.get("source_url"), "external_job_id": payload.get("external_job_id"), "description": payload.get("description"), "qualifications": payload.get("qualifications"), "responsibilities": payload.get("responsibilities"), "requirements": payload.get("requirements") or [], "metadata": payload.get("metadata") or {}, "status": row["status"], "rejection_reason": row["rejection_reason"], "viewed": bool(row["viewed"]), "discovered_at": row["discovered_at"], "last_seen_at": row["last_seen_at"], "score": evaluation.get("score"), "assessment": evaluation.get("assessment") or "unknown", "excluded": bool(evaluation.get("excluded")), "evaluation": evaluation}


def band(record: dict) -> str:
    return "excluded" if record["excluded"] else record["assessment"]


def sort_jobs(records: list[dict], sort: str) -> list[dict]:
    if sort == "score_asc":
        return sorted(records, key=lambda r: ((r["score"] if r["score"] is not None else -1), r["last_seen_at"] or ""))
    if sort == "newest":
        return sorted(records, key=lambda r: r["discovered_at"] or "", reverse=True)
    if sort == "oldest":
        return sorted(records, key=lambda r: r["discovered_at"] or "")
    if sort == "title":
        return sorted(records, key=lambda r: r["title"].lower())
    if sort == "company":
        return sorted(records, key=lambda r: (r["company"] or "").lower())
    if sort == "source":
        return sorted(records, key=lambda r: (r["source"], -(r["score"] if r["score"] is not None else -1)))
    if sort == "status":
        return sorted(records, key=lambda r: (STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else len(STATUS_ORDER), -(r["score"] if r["score"] is not None else -1)))
    return sorted(records, key=lambda r: ((r["score"] if r["score"] is not None else -1), r["last_seen_at"] or ""), reverse=True)


def filter_jobs(records: list[dict], *, text: str = "", source: str = "", status: str = "", assessment: str = "", arrangement: str = "", min_score: int = 0, include_excluded: bool = False, include_rejected: bool = False, sort: str = "score_desc") -> list[dict]:
    """Filter and order job records; every criterion is optional and purely presentational.

    Evaluator-excluded jobs and jobs the user rejected are hidden unless the caller asks for them,
    either through the include flags or by selecting that fit band or status explicitly.
    """
    if status == "rejected_by_user":
        include_rejected = True
    if assessment == "excluded":
        include_excluded = True
    needle = (text or "").strip().lower()
    selected = []
    for record in records:
        if record["excluded"] and not include_excluded:
            continue
        if record["status"] == "rejected_by_user" and not include_rejected:
            continue
        if needle and not any(needle in (record[field] or "").lower() for field in ("title", "company", "location")):
            continue
        if source and record["source"] != source:
            continue
        if status and record["status"] != status:
            continue
        if assessment and band(record) != assessment:
            continue
        if arrangement and record["arrangement"] != arrangement:
            continue
        if min_score and (record["score"] if record["score"] is not None else 0) < min_score:
            continue
        selected.append(record)
    return sort_jobs(selected, sort)


def summary(records: list[dict], applications=(), search_events=()) -> dict:
    """Aggregate counts used by the overview and the source page."""
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_band: dict[str, int] = {}
    by_arrangement: dict[str, int] = {}
    scores = []
    for record in records:
        by_status[record["status"]] = by_status.get(record["status"], 0) + 1
        by_source[record["source"]] = by_source.get(record["source"], 0) + 1
        by_band[band(record)] = by_band.get(band(record), 0) + 1
        by_arrangement[record["arrangement"]] = by_arrangement.get(record["arrangement"], 0) + 1
        if record["score"] is not None and not record["excluded"]:
            scores.append(record["score"])
    applications = list(applications)
    application_status: dict[str, int] = {}
    for row in applications:
        application_status[row["status"]] = application_status.get(row["status"], 0) + 1
    return {"total": len(records), "by_status": by_status, "by_source": by_source, "by_band": by_band, "by_arrangement": by_arrangement, "average_score": round(sum(scores) / len(scores)) if scores else None, "applications": len(applications), "application_status": application_status, "search_count": len(list(search_events))}


def source_statistics(records: list[dict]) -> list[dict]:
    """Per-source counts, score distribution and the freshest listing."""
    statistics = []
    for name in sorted({record["source"] for record in records}):
        matching = [record for record in records if record["source"] == name]
        scores = [record["score"] for record in matching if record["score"] is not None and not record["excluded"]]
        newest = max((record["discovered_at"] for record in matching), default=None)
        statistics.append({"source": name, "jobs": len(matching), "average_score": round(sum(scores) / len(scores)) if scores else None, "recommended": sum(1 for record in matching if band(record) == "recommended"), "borderline": sum(1 for record in matching if band(record) == "borderline"), "excluded": sum(1 for record in matching if band(record) == "excluded"), "saved": sum(1 for record in matching if record["status"] == "saved"), "applied": sum(1 for record in matching if record["status"] in APPLICATION_STATUSES), "remote": sum(1 for record in matching if record["arrangement"] == "remote"), "newest": newest, "samples": [record["title"] for record in sort_jobs(matching, "score_desc")[:3]]})
    return sorted(statistics, key=lambda item: item["jobs"], reverse=True)


def application_rows(rows) -> list[dict]:
    applications = []
    for row in rows:
        payload = json.loads(row["payload"])
        applications.append({"job_id": row["job_id"], "title": payload.get("title") or "(untitled)", "company": payload.get("company"), "status": row["status"], "application_date": row["application_date"], "notes": row["notes"], "updated_at": row["updated_at"], "source": payload.get("source") or "unknown", "source_url": payload.get("source_url")})
    return applications


def audit_rows(rows, *, job_id: int | None = None, events: tuple[str, ...] | None = None, limit: int | None = None) -> list[dict]:
    selected = []
    for row in rows:
        if job_id is not None and row["job_id"] != job_id:
            continue
        if events is not None and row["event"] not in events:
            continue
        selected.append({"id": row["id"], "event": row["event"], "job_id": row["job_id"], "details": row["details"], "created_at": row["created_at"]})
    return selected[:limit] if limit else selected


def source_names(records: list[dict]) -> list[str]:
    return sorted({record["source"] for record in records})
