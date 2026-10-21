"""Loading and validation of editable factual profile and search settings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ValidationError(ValueError):
    pass


# Optional `evaluation` block of the search configuration. The block is new, so unknown keys inside
# it are rejected instead of ignored: a mistyped weight would otherwise silently change nothing.
# Weights are non-negative magnitudes; `job_agent.evaluator.DEFAULT_EVALUATION_SETTINGS` holds the
# shipped values and the tests keep this schema and those defaults in sync.
EVALUATION_TOP_LEVEL_KEYS = ("base_score", "recommended_threshold", "weights")
EVALUATION_WEIGHT_SCHEMA = {
    "target_role": "number",
    "secondary_query": "number",
    "senior_penalty": "number",
    "confirmed_skill": {"mandatory": "number", "other": "number"},
    "missing_requirement": {"mandatory": "number", "preferred": "number", "useful": "number"},
    "degree_required_penalty": "number",
    "degree_mentioned": "number",
    "experience_requirement": {"mandatory": "number", "preferred": "number"},
    "source_snippet": "number",
    "no_requirements": "number",
    "remote": "number",
    "onsite_or_hybrid_within_radius": "number",
    "preferred_language": {"requirement": "number", "qualification": "number", "description": "number"},
}


# Recognized completed degrees, mapped to their rank. The profile is the only source of candidate
# education: a level that is not listed here (for example "additional education") is unknown, and
# unknown never means that the candidate lacks the degree.
DEGREE_RANKS = {"bachelor": 1, "master": 2, "phd": 3, "doctorate": 3}
DEGREE_LABELS = {"bachelor": "Bachelor's", "master": "Master's", "phd": "doctoral", "doctorate": "doctoral"}


def _education_level(entry) -> str | None:
    """The normalized level of one education entry, or None when it is missing or not a string."""
    level = entry.get("level") if isinstance(entry, dict) else None
    return level.strip().lower() if isinstance(level, str) and level.strip() else None


def degree_meets(candidate_level: str | None, required_level: str) -> bool | None:
    """Whether a recorded degree satisfies a requirement: None when the candidate level is unknown."""
    candidate = DEGREE_RANKS.get(candidate_level or "")
    required = DEGREE_RANKS.get(required_level)
    if candidate is None or required is None:
        return None
    return candidate >= required


@dataclass(frozen=True)
class Profile:
    data: dict

    @property
    def skills(self) -> set[str]:
        return {item["name"].lower() for item in self.data["skills"]}

    @property
    def degree_level(self) -> str | None:
        """The highest completed degree level recorded in `education`, or None when none is recognized."""
        levels = [level for level in map(_education_level, self.data["education"]) if level in DEGREE_RANKS]
        return max(levels, key=lambda level: DEGREE_RANKS[level]) if levels else None

    @property
    def languages(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.data["languages"].items()}

    @property
    def country_of_residence(self) -> str | None:
        return self.data.get("employment_eligibility", {}).get("country_of_residence")

    @property
    def has_professional_experience(self) -> bool | None:
        """True/False when the profile records the status, None when it does not record it."""
        value = self.data.get("professional_experience")
        return value if isinstance(value, bool) else None


def load_json(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must contain a JSON object.")
    return data


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_list(value, path: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValidationError(f"{path} must be a{' non-empty' if not allow_empty else ''} list.")
    for index, item in enumerate(value):
        if not _non_empty_string(item):
            raise ValidationError(f"{path}[{index}] must be a non-empty string.")


def _validate_optional_string_fields(entry: dict, path: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            raise ValidationError(f"{path}.{field} must be a string or null.")


def _validate_project(entry, path: str) -> None:
    if not isinstance(entry, dict) or not _non_empty_string(entry.get("name")):
        raise ValidationError(f"{path} must be an object with a non-empty string name.")
    _validate_optional_string_fields(entry, path, ("description",))
    for field in ("technologies", "candidate_bullets", "general_bullets"):
        if field in entry:
            _validate_string_list(entry[field], f"{path}.{field}")


def _validate_profile_fields(data: dict) -> None:
    identity = data.get("identity")
    if not isinstance(identity, dict) or not _non_empty_string(identity.get("name")) or not _non_empty_string(identity.get("city")):
        raise ValidationError("Profile identity must be an object with non-empty name and city strings.")

    contact = data.get("contact")
    if contact is not None:
        if not isinstance(contact, dict):
            raise ValidationError("Profile contact must be an object when present.")
        _validate_optional_string_fields(contact, "contact", ("phone", "email", "github", "linkedin"))

    education = data.get("education")
    if not isinstance(education, list) or not education:
        raise ValidationError("Profile needs at least one education entry.")
    for index, entry in enumerate(education):
        path = f"education[{index}]"
        if not isinstance(entry, dict):
            raise ValidationError(f"Profile {path} must be an object.")
        for field in ("degree", "institution", "period"):
            if not _non_empty_string(entry.get(field)):
                raise ValidationError(f"Profile {path}.{field} must be a non-empty string.")
        if "level" in entry and not isinstance(entry["level"], str):
            raise ValidationError(f"Profile {path}.level must be a string.")
        _validate_optional_string_fields(entry, path, ("detail",))

    skills = data.get("skills")
    if not isinstance(skills, list):
        raise ValidationError("Profile skills must be a list.")
    for index, entry in enumerate(skills):
        path = f"skills[{index}]"
        if not isinstance(entry, dict) or not _non_empty_string(entry.get("name")):
            raise ValidationError(f"Profile {path} must be an object with a non-empty string name.")
        _validate_optional_string_fields(entry, path, ("evidence",))

    languages = data.get("languages")
    if not isinstance(languages, dict) or any(not isinstance(value, str) for value in languages.values()):
        raise ValidationError("Profile languages must be an object of string values.")

    thesis = data.get("thesis")
    if thesis is not None:
        _validate_project(thesis, "thesis")
    projects = data.get("projects")
    if projects is not None:
        if not isinstance(projects, list):
            raise ValidationError("Profile projects must be a list when present.")
        for index, entry in enumerate(projects):
            _validate_project(entry, f"projects[{index}]")

    certifications = data.get("certifications")
    if certifications is not None:
        _validate_string_list(certifications, "certifications")

    technical_practice = data.get("technical_practice")
    if technical_practice is not None:
        if not isinstance(technical_practice, dict):
            raise ValidationError("Profile technical_practice must be an object when present.")
        for key, value in technical_practice.items():
            if isinstance(value, str):
                continue
            try:
                _validate_string_list(value, f"technical_practice.{key}")
            except ValidationError as exc:
                raise ValidationError(
                    f"Profile technical_practice.{key} must be a string or a list of non-empty strings."
                ) from exc

    availability = data.get("availability")
    if availability is not None and not isinstance(availability, str):
        raise ValidationError("Profile availability must be a string when present.")

    eligibility = data.get("employment_eligibility")
    if eligibility is not None:
        if not isinstance(eligibility, dict):
            raise ValidationError("Profile employment_eligibility must be an object when present.")
        _validate_optional_string_fields(
            eligibility,
            "employment_eligibility",
            ("country_of_residence", "residence_permit_wording", "note"),
        )


def load_profile(path: str | Path) -> Profile:
    data = load_json(path)
    required = ("identity", "education", "skills", "languages")
    missing = [field for field in required if field not in data]
    if missing:
        raise ValidationError(f"Profile is missing required fields: {', '.join(missing)}")
    _validate_profile_fields(data)
    experience = data.get("professional_experience")
    if experience is not None and not isinstance(experience, bool):
        raise ValidationError("Profile professional_experience must be true, false or null; omit the key when the status is unknown.")
    return Profile(data)


def load_config(path: str | Path) -> dict:
    data = load_json(path)
    for field in ("target_roles", "locations", "work_arrangements"):
        if field not in data:
            raise ValidationError(f"Configuration needs a list named '{field}'.")
        _validate_string_list(data[field], field)
    queries = data.get("search_queries")
    if not isinstance(queries, dict):
        raise ValidationError("Configuration needs a dictionary named 'search_queries'.")
    for family in ("primary", "secondary"):
        values = queries.get(family)
        if not isinstance(values, list) or not values or not all(isinstance(query, str) and query.strip() for query in values):
            raise ValidationError(f"Configuration search_queries.{family} must be a non-empty list of non-empty strings.")
    preferences = data.get("location_preferences")
    if not isinstance(preferences, dict) or not isinstance(preferences.get("origin"), str) or not preferences["origin"].strip():
        raise ValidationError("Configuration needs a non-empty location_preferences.origin.")
    if not isinstance(preferences.get("max_distance_km"), (int, float)) or isinstance(preferences["max_distance_km"], bool) or preferences["max_distance_km"] <= 0:
        raise ValidationError("Configuration location_preferences.max_distance_km must be a positive number.")
    if not isinstance(preferences.get("remote_only_beyond_distance"), bool):
        raise ValidationError("Configuration location_preferences.remote_only_beyond_distance must be boolean.")
    if "evaluation" in data:
        _validate_evaluation(data["evaluation"])
    if "preferred_languages" in data:
        _validate_string_list(data["preferred_languages"], "preferred_languages")
    if "maximum_commute_note" in data and not isinstance(data["maximum_commute_note"], str):
        raise ValidationError("Configuration maximum_commute_note must be a string when present.")
    return data


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_evaluation_number(path: str, value, *, maximum: float | None = None) -> None:
    if not _is_number(value):
        raise ValidationError(f"Configuration {path} must be a number.")
    if value < 0:
        raise ValidationError(f"Configuration {path} must not be negative.")
    if maximum is not None and value > maximum:
        raise ValidationError(f"Configuration {path} must be at most {maximum:g}.")


def _validate_weight_group(path: str, values: dict, schema: dict) -> None:
    unknown = sorted(key for key in values if key not in schema)
    if unknown:
        raise ValidationError(f"Configuration {path} has unknown setting(s): {', '.join(unknown)}.")
    for key, expected in schema.items():
        if key not in values:
            continue
        value = values[key]
        if isinstance(expected, dict):
            if not isinstance(value, dict):
                raise ValidationError(f"Configuration {path}.{key} must be an object.")
            _validate_weight_group(f"{path}.{key}", value, expected)
        else:
            _validate_evaluation_number(f"{path}.{key}", value)


def _validate_evaluation(evaluation) -> None:
    if not isinstance(evaluation, dict):
        raise ValidationError("Configuration 'evaluation' must be an object.")
    unknown = sorted(key for key in evaluation if key not in EVALUATION_TOP_LEVEL_KEYS)
    if unknown:
        raise ValidationError(f"Configuration evaluation has unknown setting(s): {', '.join(unknown)}.")
    for key in ("base_score", "recommended_threshold"):
        if key in evaluation:
            _validate_evaluation_number(f"evaluation.{key}", evaluation[key], maximum=100)
    if "weights" in evaluation:
        weights = evaluation["weights"]
        if not isinstance(weights, dict):
            raise ValidationError("Configuration evaluation.weights must be an object.")
        _validate_weight_group("evaluation.weights", weights, EVALUATION_WEIGHT_SCHEMA)
