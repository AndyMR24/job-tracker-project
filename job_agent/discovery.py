"""Public job-discovery orchestration shared by the CLI and the dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .adzuna import AdzunaError, AdzunaSource
from .ba import BASource
from .evaluator import evaluate
from .himalayas import HimalayasSource
from .nomado24 import Nomado24Source
from .normalizer import normalize
from .profile import Profile

SOURCE_NAMES = ("adzuna", "nomado24", "himalayas", "ba")


class UnavailableSource:
    """Placeholder for a configured source that cannot be built, such as Adzuna without credentials."""

    def __init__(self, label: str, reason: str):
        self.label = label
        self.reason = reason

    @property
    def note(self) -> str:
        return f"{self.label} skipped: {self.reason}; no {self.label} search was performed."

    def search(self, query: str, location: str | None = None) -> list[dict]:
        raise RuntimeError(self.note)


def default_sources(root: str | Path) -> dict[str, tuple[object, bool]]:
    """Build the public source adapters in the order used for configured searches.

    Adzuna becomes an unavailable placeholder when its credentials are absent, so the remaining
    sources can still be searched; `collect` reports the skip instead of failing the whole run.
    Rejected credentials are not treated as missing - they fail at request time as before.
    """
    root = Path(root)
    sources: dict[str, tuple[object, bool]] = {}
    try:
        sources["adzuna"] = (AdzunaSource(root / ".env"), True)
    except AdzunaError:
        # AdzunaSource raises at construction only when a credential is missing; nothing else is
        # caught here, so unrelated failures keep their existing handling.
        sources["adzuna"] = (UnavailableSource("Adzuna", "ADZUNA_APP_ID and ADZUNA_APP_KEY are not set"), True)
    sources["nomado24"] = (Nomado24Source(), True)
    sources["himalayas"] = (HimalayasSource(), False)
    sources["ba"] = (BASource(), True)
    return sources


@dataclass
class SearchOutcome:
    jobs: list[dict] = field(default_factory=list)
    queries_run: int = 0
    source_results: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


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
    total = sum(1 for _, adapters in plans for _, adapter, _ in adapters if not isinstance(adapter, UnavailableSource))
    seen: set[tuple] = set()
    for text, adapters in plans:
        for name, adapter, accepts_location in adapters:
            if isinstance(adapter, UnavailableSource):
                if adapter.note not in outcome.skipped:
                    outcome.skipped.append(adapter.note)
                continue
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
