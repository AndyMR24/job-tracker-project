"""Conservative normalization. Missing source values remain unknown."""
from __future__ import annotations

import re

from .models import Job, Requirement

SENIORITY = ("intern", "trainee", "graduate", "entry", "junior", "associate", "mid", "senior", "lead", "principal", "staff")


def _nomado_tag_text(raw: dict) -> str:
    """Return text from a strictly structured Nomado24 tag list, or an empty string."""
    if raw.get("source") != "nomado24":
        return ""
    metadata = raw.get("metadata")
    tags = metadata.get("tags") if isinstance(metadata, dict) else None
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        return ""
    return " ".join(tag.strip() for tag in tags if tag.strip())


def normalize(raw: dict) -> Job:
    if not raw.get("title"):
        raise ValueError("A job requires a title.")
    text = " ".join(str(raw.get(key, "")) for key in ("description", "requirements", "qualifications"))
    tag_text = _nomado_tag_text(raw)
    title = raw["title"].strip()
    arrangement = str(raw.get("arrangement", "unknown")).lower()
    if arrangement not in {"remote", "hybrid", "onsite", "unknown"}:
        arrangement = "unknown"
    seniority = next((s for s in SENIORITY if re.search(rf"\b{s}\b", title.lower())), "unknown")
    requirements: list[Requirement] = []
    seen: set[str] = set()
    for entry in raw.get("requirements", []) if isinstance(raw.get("requirements"), list) else []:
        requirement = Requirement(**entry) if isinstance(entry, dict) else Requirement(str(entry))
        key = requirement.text.strip().casefold()
        if key and key not in seen:
            requirements.append(requirement)
            seen.add(key)
    has_explicit_requirements = bool(requirements)
    known_terms = raw.get("known_requirement_terms", [])
    for skill in known_terms if isinstance(known_terms, list) else []:
        if not isinstance(skill, str):
            continue
        key = skill.strip().casefold()
        if not key or key in seen:
            continue
        pattern = rf"\b{re.escape(skill)}\b"
        in_text = re.search(pattern, text, re.I) is not None
        in_tags = bool(tag_text and re.search(pattern, tag_text, re.I))
        if not in_text and not in_tags:
            continue
        if has_explicit_requirements and not in_tags:
            continue
        kind = "unknown"
        if in_text and re.search(rf"(required|must have|essential).{{0,80}}{re.escape(skill)}", text, re.I):
            kind = "mandatory"
        requirements.append(Requirement(skill, kind))
        seen.add(key)
    return Job(title=title, company=raw.get("company"), location=raw.get("location"), arrangement=arrangement,
               description=raw.get("description"), requirements=requirements, responsibilities=raw.get("responsibilities"),
               qualifications=raw.get("qualifications"), salary=raw.get("salary"), employment_type=raw.get("employment_type"),
               seniority=raw.get("seniority", seniority).lower(), source=raw.get("source", "unknown"),
               source_url=raw.get("source_url"), external_job_id=raw.get("external_job_id"), metadata=raw.get("metadata", {}))
