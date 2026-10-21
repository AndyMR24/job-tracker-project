"""Explainable, deliberately conservative job-fit evaluation."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import Job
from .location import EligibilityStatus, LocationStatus, coordinates_from_metadata, resolve_eligibility, resolve_location
from .profile import DEGREE_LABELS, Profile, degree_meets


# Secondary ranking preference. This is deliberately small, additive and never an eligibility rule:
# a job is never excluded for missing it, and it cannot outweigh role relevance, seniority, location,
# employment eligibility or the core requirement checks.
SECONDARY_PREFERRED_LANGUAGES = ("python",)
_SECONDARY_LANGUAGE_TIERS = {"requirement": "listed requirements", "qualification": "qualification text", "description": "job description"}

# Shipped numeric evaluation rules. An optional `evaluation` block in the search configuration
# overrides individual settings (see `evaluation_settings`; it is validated in profile.load_config).
# Bonuses and penalties are stored as non-negative magnitudes and applied by addition or subtraction,
# so `"senior_penalty": 45` subtracts 45. The numbers are independent of the exclusion triggers:
# lowering a penalty - even to 0 - never disables an exclusion.
DEFAULT_EVALUATION_SETTINGS = {
    "base_score": 50,
    "recommended_threshold": 60,
    "weights": {
        "target_role": 15,
        "secondary_query": 8,
        "senior_penalty": 45,
        "confirmed_skill": {"mandatory": 8, "other": 4},
        "missing_requirement": {"mandatory": 18, "preferred": 4, "useful": 4},
        "degree_required_penalty": 50,
        "degree_mentioned": 10,
        "experience_requirement": {"mandatory": 25, "preferred": 8},
        "source_snippet": 5,
        "no_requirements": 5,
        "remote": 6,
        "onsite_or_hybrid_within_radius": 4,
        "preferred_language": {"requirement": 3, "qualification": 2, "description": 1},
    },
}


def _merged_settings(defaults: dict, override: dict) -> dict:
    """Overlay configured values on the defaults key by key, without mutating either mapping."""
    resolved = {}
    for key, default in defaults.items():
        value = override.get(key)
        if isinstance(default, dict):
            resolved[key] = _merged_settings(default, value if isinstance(value, dict) else {})
        else:
            resolved[key] = default if value is None else value
    return resolved


def evaluation_settings(config: dict) -> dict:
    """Resolve the optional `evaluation` configuration block over the shipped defaults."""
    override = config.get("evaluation")
    return _merged_settings(DEFAULT_EVALUATION_SETTINGS, override if isinstance(override, dict) else {})


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
    settings = evaluation_settings(config)
    weights = settings["weights"]
    score = settings["base_score"]
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
        score += weights["target_role"]; matches.append("Title is related to a configured target role.")
    elif secondary_match:
        score += weights["secondary_query"]; matches.append("Title is related to a configured secondary role.")
    else:
        gaps.append("Title is not clearly among the configured target roles.")
    experience = profile.has_professional_experience
    seniority = job.seniority
    if seniority == "unknown":
        seniority = next((level for level in ("intern", "trainee", "graduate", "entry", "junior", "associate", "senior", "lead", "principal", "staff", "head", "director") if re.search(rf"\b{re.escape(level)}\b", title)), "unknown")
    if seniority in {"senior", "lead", "principal", "staff", "head", "director"}:
        if experience is False:
            score -= weights["senior_penalty"]; excluded = True; concerns.append("The posting is explicitly senior-level while the profile has no professional employment experience.")
        elif experience:
            matches.append("The posting is explicitly senior-level and the profile records professional experience.")
        else:
            unknown.append("The posting is explicitly senior-level and the profile does not record whether the candidate has professional experience; the requirement needs review.")
    elif seniority in {"junior", "graduate", "entry", "trainee", "intern", "associate"}:
        if experience is False:
            matches.append("Seniority appears compatible with an early-career search.")
        elif experience:
            matches.append("Seniority wording is compatible with the profile's recorded professional experience.")
        else:
            unknown.append("Seniority wording is not contradicted by the profile, which does not record whether the candidate has professional experience.")
    elif seniority == "unknown":
        unknown.append("Seniority is not stated clearly.")
    for requirement in job.requirements:
        term = requirement.text.lower()
        if term in profile.skills:
            score += weights["confirmed_skill"]["mandatory" if requirement.kind == "mandatory" else "other"]
            matches.append(f"Confirmed skill: {requirement.text}.")
        elif "master" in term:
            candidate = profile.degree_level
            meets = degree_meets(candidate, "master")
            if meets:
                matches.append(f"A Master's degree is required and the profile records a {DEGREE_LABELS[candidate]} degree.")
            elif meets is False:
                label = DEGREE_LABELS[candidate]
                if requirement.kind == "mandatory":
                    score -= weights["degree_required_penalty"]; excluded = True; concerns.append(f"A Master's degree is explicitly required; the profile records a {label} degree.")
                else:
                    score -= weights["degree_mentioned"]; gaps.append(f"A Master's degree is mentioned but the profile records a {label} degree.")
            elif requirement.kind == "mandatory":
                unknown.append("A Master's degree is required, but the profile's highest completed degree is not recognized; the requirement needs review.")
            else:
                unknown.append("A Master's degree is mentioned; the profile's highest completed degree is not recognized.")
        elif "year" in term and "experience" in term:
            if experience is False:
                score -= weights["experience_requirement"]["mandatory" if requirement.kind == "mandatory" else "preferred"]
                concerns.append("Professional-experience requirement is not satisfied by projects or thesis work.")
            elif experience:
                unknown.append(f"Professional-experience requirement needs review: the profile records professional experience but not the years stated by {requirement.text}.")
            else:
                unknown.append(f"Professional-experience requirement needs review: the profile does not record whether the candidate meets the years stated by {requirement.text}.")
        # The profile is not an exhaustive list of what the candidate knows, so a requirement it does
        # not list is unknown rather than a confirmed gap: record it for review and score nothing. The
        # `missing_requirement` weights stay defined for requirements a future rule can prove unmet.
        elif requirement.kind in {"mandatory", "preferred", "useful"}:
            label = {"mandatory": "Mandatory", "preferred": "Preferred", "useful": "Useful"}[requirement.kind]
            unknown.append(f"{label} requirement could not be verified from the profile: {requirement.text}.")
        else:
            unknown.append(f"Requirement needs review: {requirement.text}.")
    preferred_languages = tuple(str(language).lower() for language in config.get("preferred_languages") or SECONDARY_PREFERRED_LANGUAGES)
    language_tier = _secondary_language_signal(job, preferred_languages)
    if language_tier:
        score += weights["preferred_language"][language_tier]
        matches.append(f"{', '.join(language.title() for language in preferred_languages)} is a secondary preference and appears in the {_SECONDARY_LANGUAGE_TIERS[language_tier]}.")
    if job.metadata.get("description_is_snippet"):
        score -= weights["source_snippet"]
        unknown.append("The source provides only a description snippet; additional requirements may be unavailable.")
    elif not job.requirements:
        score -= weights["no_requirements"]
        unknown.append("The listing does not expose explicit requirements; technical qualifications could not be fully verified.")
    geographic = resolve_location(job.location, config["location_preferences"], coordinates_from_metadata(job.metadata))
    if geographic.status == LocationStatus.OUTSIDE_RADIUS:
        if not (job.arrangement == "remote" and config["location_preferences"]["remote_only_beyond_distance"]):
            excluded = True
            location_label = geographic.city or job.location or "source coordinates"
            concerns.append(f"Resolved city {location_label} is outside the configured geographic radius.")
        else:
            matches.append("Explicitly remote job is allowed beyond the configured geographic radius.")
    elif geographic.status == LocationStatus.UNKNOWN:
        if not geographic.origin_resolved:
            unknown.append(f"The configured location origin {config['location_preferences']['origin']!r} could not be resolved, so the geographic radius was not applied; check location_preferences.origin.")
        if not geographic.job_location_resolved:
            unknown.append("Job city could not be resolved for geographic-radius evaluation.")
    if job.arrangement == "remote":
        score += weights["remote"]; matches.append("Germany-wide remote work is enabled in the configuration.")
    elif job.arrangement in {"hybrid", "onsite"}:
        if geographic.status == LocationStatus.WITHIN_RADIUS:
            score += weights["onsite_or_hybrid_within_radius"]; matches.append("Location is within the configured geographic radius.")
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
    elif eligibility.status is EligibilityStatus.UNKNOWN and job.arrangement == "remote":
        unknown.append("Remote country eligibility is not stated or could not be interpreted; verify where you may work from.")
    body = " ".join(filter(None, [job.description, job.qualifications])).lower()
    sponsorship_terms = ("must be authorized to work", "no sponsorship", "visa sponsorship", "requires sponsorship", "sponsorship is unavailable", "sponsorship unavailable")
    if any(term in body for term in sponsorship_terms):
        unknown.append("Work-authorization or sponsorship wording requires verification; no legal conclusion is made.")
    score = max(0, min(100, score))
    assessment = "rejected" if excluded else "recommended" if score >= settings["recommended_threshold"] else "borderline"
    return Evaluation(score, assessment, excluded, matches, gaps, concerns, unknown)
