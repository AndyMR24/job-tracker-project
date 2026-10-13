"""Public job-discovery orchestration shared by the CLI and the dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .adzuna import AdzunaSource
from .ba import BASource
from .evaluator import evaluate
from .himalayas import HimalayasSource
from .nomado24 import Nomado24Source
from .normalizer import normalize
from .profile import Profile

SOURCE_NAMES = ("adzuna", "nomado24", "himalayas", "ba")


def default_sources(root: str | Path) -> dict[str, tuple[object, bool]]:
    """Build the public source adapters in the order used for configured searches."""
    root = Path(root)
    return {"adzuna": (AdzunaSource(root / ".env"), True), "nomado24": (Nomado24Source(), True), "himalayas": (HimalayasSource(), False), "ba": (BASource(), True)}


@dataclass
class SearchOutcome:
    jobs: list[dict] = field(default_factory=list)
    queries_run: int = 0
    source_results: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def collect(sources, *, queries=None, query=None, source=None, location=None, tolerate_errors=False, progress=None) -> SearchOutcome:
    """Run one manual query or every configured query through the selected public adapters."""
    outcome = SearchOutcome()
    if query is not None:
        name = source or "adzuna"
        adapter, accepts_location = sources[name]
        plans = [(query, [(name, adapter, accepts_location)])]
    else:
        chosen = [(name, adapter, accepts_location) for name, (adapter, accepts_location) in sources.items() if source is None or name == source]
        plans = [(text, chosen) for text in queries or []]
    total = sum(len(adapters) for _, adapters in plans)
    seen: set[tuple] = set()
    for text, adapters in plans:
        for name, adapter, accepts_location in adapters:
            outcome.queries_run += 1
            try:
                results = adapter.search(text, location) if accepts_location else adapter.search(text)
            except Exception as exc:
                if not tolerate_errors:
                    raise
                outcome.errors.append(f"{name}: {exc}")
                if progress:
                    progress(outcome.queries_run, total, f"{name} - {text}: failed")
                continue
            outcome.source_results[name] = outcome.source_results.get(name, 0) + len(results)
            for raw in results:
                identity = (raw.get("source"), raw.get("external_job_id"))
                if identity[0] and identity[1] and identity in seen:
                    continue
                if identity[0] and identity[1]:
                    seen.add(identity)
                outcome.jobs.append(raw)
            if progress:
                progress(outcome.queries_run, total, f"{name} - {text}: {len(results)} results")
    return outcome


def store_jobs(store, profile: Profile, config: dict, raw_jobs: list[dict], on_job=None) -> list[dict]:
    """Normalize, evaluate and persist listings, returning one record per listing."""
    skills = [item["name"] for item in profile.data["skills"]]
    records = []
    for index, raw in enumerate(raw_jobs, start=1):
        raw.setdefault("known_requirement_terms", skills)
        job = normalize(raw)
        result = evaluate(job, profile, config)
        job_id, created = store.save_job(job, result.to_dict())
        record = {"job_id": job_id, "created": created, "excluded": result.excluded, "score": result.score, "assessment": result.assessment, "title": job.title, "label": "Excluded" if result.excluded else ("New" if created else "Known")}
        records.append(record)
        if on_job:
            on_job(index, len(raw_jobs), record)
    return records
