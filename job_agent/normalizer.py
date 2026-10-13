"""Conservative normalization. Missing source values remain unknown."""
from __future__ import annotations

import re

from .models import Job, Requirement

SENIORITY = ("intern", "trainee", "graduate", "entry", "junior", "associate", "mid", "senior", "lead", "principal", "staff")


def normalize(raw: dict) -> Job:
    if not raw.get("title"):
        raise ValueError("A job requires a title.")
    text = " ".join(str(raw.get(key, "")) for key in ("description", "requirements", "qualifications"))
    title = raw["title"].strip()
    arrangement = str(raw.get("arrangement", "unknown")).lower()
    if arrangement not in {"remote", "hybrid", "onsite", "unknown"}:
        arrangement = "unknown"
    seniority = next((s for s in SENIORITY if re.search(rf"\b{s}\b", title.lower())), "unknown")
    requirements: list[Requirement] = []
    for entry in raw.get("requirements", []) if isinstance(raw.get("requirements"), list) else []:
        requirements.append(Requirement(**entry) if isinstance(entry, dict) else Requirement(str(entry)))
    if not requirements:
        for skill in raw.get("known_requirement_terms", []):
            if re.search(rf"\b{re.escape(skill)}\b", text, re.I):
                kind = "mandatory" if re.search(rf"(required|must have|essential).{{0,80}}{re.escape(skill)}", text, re.I) else "unknown"
                requirements.append(Requirement(skill, kind))
    return Job(title=title, company=raw.get("company"), location=raw.get("location"), arrangement=arrangement,
               description=raw.get("description"), requirements=requirements, responsibilities=raw.get("responsibilities"),
               qualifications=raw.get("qualifications"), salary=raw.get("salary"), employment_type=raw.get("employment_type"),
               seniority=raw.get("seniority", seniority).lower(), source=raw.get("source", "unknown"),
               source_url=raw.get("source_url"), external_job_id=raw.get("external_job_id"), metadata=raw.get("metadata", {}))
