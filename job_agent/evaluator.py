"""Explainable, deliberately conservative job-fit evaluation."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import Job
from .location import EligibilityStatus, LocationStatus, resolve_eligibility, resolve_location
from .profile import Profile


# Secondary ranking preference. This is deliberately small, additive and never an eligibility rule:
# a job is never excluded for missing it, and it cannot outweigh role relevance, seniority, location,
# employment eligibility or the core requirement checks.
SECONDARY_PREFERRED_LANGUAGES = ("python",)
_SECONDARY_LANGUAGE_BONUS = {"requirement": 3, "qualification": 2, "description": 1}
_SECONDARY_LANGUAGE_TIERS = {"requirement": "listed requirements", "qualification": "qualification text", "description": "job description"}


def _secondary_language_signal(job: Job, languages: tuple[str, ...]) -> str | None:
    """Return the strongest tier that mentions a preferred language, or None when it is absent."""
    if not languages:
        return None
    pattern = "|".join(rf"\b{re.escape(language)}\b" for language in languages)
    if any(re.search(pattern, requirement.text, re.I) for requirement in job.requirements):
        return "requirement"
    if job.qualifications and re.search(pattern, job.qualifications, re.I):
        return "qualification"
    if re.search(pattern, " ".join(filter(None, [job.description, job.responsibilities])), re.I):
        return "description"
    return None


def _matches_target_role(title: str, roles: list[str]) -> bool:
    """Recognize small, explicit title variants without matching generic words."""
    normalized = " ".join(title.lower().replace("/", " ").split())
    for role in roles:
        target = " ".join(role.lower().replace("/", " ").split())
        if target in normalized:
            return True
        if target == "data scientist" and "data science" in normalized:
            return True
        if target == "python developer" and "python" in normalized and "developer" in normalized:
            return True
        if target == "software developer" and "software" in normalized and "developer" in normalized:
            return True
    return False


def _matches_configured_query(title: str, queries: list[str]) -> bool:
    """Match a title against an explicitly configured secondary query."""
    normalized = " ".join(title.lower().replace("/", " ").split())
    return any(" ".join(query.lower().replace("/", " ").split()) in normalized for query in queries)


@dataclass
class Evaluation:
    score: int
    assessment: str
    excluded: bool
    strong_matches: list[str]
    potential_gaps: list[str]
    concerns: list[str]
    uncertainties: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(job: Job, profile: Profile, config: dict) -> Evaluation:
    score = 50
    matches: list[str] = []
    gaps: list[str] = []
    concerns: list[str] = []
    unknown: list[str] = []
    excluded = False
    title = job.title.lower()
    roles = [x.lower() for x in config["target_roles"]]
    primary_match = _matches_target_role(title, roles)
    secondary_match = _matches_configured_query(title, config["search_queries"]["secondary"])
    if primary_match:
        score += 15; matches.append("Title is related to a configured target role.")
    elif secondary_match:
        score += 8; matches.append("Title is related to a configured secondary role.")
    else:
        gaps.append("Title is not clearly among the configured target roles.")
    seniority = job.seniority
    if seniority == "unknown":
        seniority = next((level for level in ("intern", "trainee", "graduate", "entry", "junior", "associate", "senior", "lead", "principal", "staff", "head", "director") if re.search(rf"\b{re.escape(level)}\b", title)), "unknown")
    if seniority in {"senior", "lead", "principal", "staff", "head", "director"}:
        score -= 45; excluded = True; concerns.append("The posting is explicitly senior-level while the profile has no professional employment experience.")
    elif seniority in {"junior", "graduate", "entry", "trainee", "intern", "associate"}:
        matches.append("Seniority appears compatible with an early-career search.")
    elif seniority == "unknown":
        unknown.append("Seniority is not stated clearly.")
    for requirement in job.requirements:
        term = requirement.text.lower()
        if term in profile.skills:
            score += 8 if requirement.kind == "mandatory" else 4
            matches.append(f"Confirmed skill: {requirement.text}.")
        elif "master" in term:
            if requirement.kind == "mandatory":
                score -= 50; excluded = True; concerns.append("A Master's degree is explicitly required; the profile records a Bachelor's degree.")
            else:
                score -= 10; gaps.append("A Master's degree is mentioned but the profile records a Bachelor's degree.")
        elif "year" in term and "experience" in term:
            score -= 25 if requirement.kind == "mandatory" else 8
            concerns.append("Professional-experience requirement is not satisfied by projects or thesis work.")
        elif requirement.kind == "mandatory":
            score -= 18; gaps.append(f"Mandatory requirement not confirmed by profile: {requirement.text}.")
        elif requirement.kind in {"preferred", "useful"}:
            score -= 4; gaps.append(f"Preferred/useful requirement not confirmed: {requirement.text}.")
        else:
            unknown.append(f"Requirement needs review: {requirement.text}.")
    preferred_languages = tuple(str(language).lower() for language in config.get("preferred_languages") or SECONDARY_PREFERRED_LANGUAGES)
    language_tier = _secondary_language_signal(job, preferred_languages)
    if language_tier:
        score += _SECONDARY_LANGUAGE_BONUS[language_tier]
        matches.append(f"{', '.join(language.title() for language in preferred_languages)} is a secondary preference and appears in the {_SECONDARY_LANGUAGE_TIERS[language_tier]}.")
    if job.metadata.get("description_is_snippet"):
        score -= 5
        unknown.append("The source provides only a description snippet; additional requirements may be unavailable.")
    elif not job.requirements:
        score -= 5
        unknown.append("The listing does not expose explicit requirements; technical qualifications could not be fully verified.")
    geographic = resolve_location(job.location, config["location_preferences"])
    if geographic.status == LocationStatus.OUTSIDE_RADIUS:
        if not (job.arrangement == "remote" and config["location_preferences"]["remote_only_beyond_distance"]):
            excluded = True
            concerns.append(f"Resolved city {geographic.city} is outside the configured geographic radius.")
        else:
            matches.append("Explicitly remote job is allowed beyond the configured geographic radius.")
    elif geographic.status == LocationStatus.UNKNOWN:
        unknown.append("Job city could not be resolved for geographic-radius evaluation.")
    if job.arrangement == "remote":
        score += 6; matches.append("Germany-wide remote work is enabled in the configuration.")
    elif job.arrangement in {"hybrid", "onsite"}:
        if geographic.status == LocationStatus.WITHIN_RADIUS:
            score += 4; matches.append("Location is within the configured geographic radius.")
        elif not job.location:
            unknown.append("Hybrid/onsite posting has no stated location.")
    else:
        unknown.append("Work arrangement is unknown.")
    eligibility = resolve_eligibility(job.metadata, profile.country_of_residence)
    if eligibility.status is EligibilityStatus.RESTRICTED:
        excluded = True
        concerns.append(f"The posting is restricted to {eligibility.detail}; the profile records residence in {profile.country_of_residence}.")
    elif eligibility.status is EligibilityStatus.ALLOWED and eligibility.detail != "worldwide":
        matches.append(f"The published restriction list explicitly allows {profile.country_of_residence}.")
    body = " ".join(filter(None, [job.description, job.qualifications])).lower()
    sponsorship_terms = ("must be authorized to work", "no sponsorship", "visa sponsorship", "requires sponsorship", "sponsorship is unavailable", "sponsorship unavailable")
    if any(term in body for term in sponsorship_terms):
        unknown.append("Work-authorization or sponsorship wording requires verification; no legal conclusion is made.")
    score = max(0, min(100, score))
    assessment = "rejected" if excluded else "recommended" if score >= 60 else "borderline"
    return Evaluation(score, assessment, excluded, matches, gaps, concerns, unknown)
