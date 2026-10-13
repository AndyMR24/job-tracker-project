"""Loading and validation of editable factual profile and search settings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    data: dict

    @property
    def skills(self) -> set[str]:
        return {item["name"].lower() for item in self.data["skills"]}

    @property
    def degree_level(self) -> str:
        return self.data["education"][0]["level"].lower()

    @property
    def languages(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.data["languages"].items()}

    @property
    def country_of_residence(self) -> str | None:
        return self.data.get("employment_eligibility", {}).get("country_of_residence")


def load_json(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read {path}: {exc}") from exc


def load_profile(path: str | Path) -> Profile:
    data = load_json(path)
    required = ("identity", "education", "skills", "languages", "professional_experience")
    missing = [field for field in required if field not in data]
    if missing:
        raise ValidationError(f"Profile is missing required fields: {', '.join(missing)}")
    if not isinstance(data["education"], list) or not data["education"]:
        raise ValidationError("Profile needs at least one education entry.")
    if not all(isinstance(x, dict) and x.get("name") for x in data["skills"]):
        raise ValidationError("Every skill needs a name.")
    if data["professional_experience"] is not False:
        raise ValidationError("MVP profile must explicitly state whether professional experience exists.")
    return Profile(data)


def load_config(path: str | Path) -> dict:
    data = load_json(path)
    for field in ("target_roles", "locations", "work_arrangements"):
        if field not in data or not isinstance(data[field], list):
            raise ValidationError(f"Configuration needs a list named '{field}'.")
    queries = data.get("search_queries")
    if not isinstance(queries, dict):
        raise ValidationError("Configuration needs a dictionary named 'search_queries'.")
    for family in ("primary", "secondary"):
        values = queries.get(family)
        if not isinstance(values, list) or not all(isinstance(query, str) and query.strip() for query in values):
            raise ValidationError(f"Configuration search_queries.{family} must be a list of non-empty strings.")
    preferences = data.get("location_preferences")
    if not isinstance(preferences, dict) or not isinstance(preferences.get("origin"), str) or not preferences["origin"].strip():
        raise ValidationError("Configuration needs a non-empty location_preferences.origin.")
    if not isinstance(preferences.get("max_distance_km"), (int, float)) or isinstance(preferences["max_distance_km"], bool) or preferences["max_distance_km"] <= 0:
        raise ValidationError("Configuration location_preferences.max_distance_km must be a positive number.")
    if not isinstance(preferences.get("remote_only_beyond_distance"), bool):
        raise ValidationError("Configuration location_preferences.remote_only_beyond_distance must be boolean.")
    return data
