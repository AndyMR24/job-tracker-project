"""Offline city resolution and approximate geographic distance checks."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum


class LocationStatus(str, Enum):
    WITHIN_RADIUS = "within_radius"
    OUTSIDE_RADIUS = "outside_radius"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LocationResult:
    """The outcome of the geographic radius check.

    `origin_resolved` and `job_location_resolved` only carry information for `UNKNOWN` results: they
    say which side of the check could not be resolved, so callers can report the configured origin
    instead of blaming a job city that resolved perfectly well.
    """

    status: LocationStatus
    city: str | None = None
    distance_km: float | None = None
    origin_resolved: bool = True
    job_location_resolved: bool = True


# Small deterministic fallback for the German locations used by the application.
# geonamescache remains the complete offline dataset when installed.
_FALLBACK_CITIES = {
    "aachen": (50.7753, 6.0839), "köln": (50.9375, 6.9603), "cologne": (50.9375, 6.9603),
    "düsseldorf": (51.2277, 6.7735), "duesseldorf": (51.2277, 6.7735), "münchen": (48.1351, 11.5820), "munich": (48.1351, 11.5820),
    "berlin": (52.5200, 13.4050),
}
_VAGUE = {"germany", "deutschland", "europe", "north rhine-westphalia", "nordrhein-westfalen"}


def extract_city(location: str | None) -> str | None:
    if not location:
        return None
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if not parts or location.strip().lower() in _VAGUE or len(parts) > 2:
        return None
    first = re.sub(r"\s*\([^)]*\)\s*$", "", parts[0]).strip()
    if not first or first.lower() in _VAGUE:
        return None
    if len(parts) == 2 and parts[1].strip().lower() == first.lower():
        return first
    if len(parts) == 2 and "kreis" in parts[1].lower():
        return first
    return first if len(parts) == 1 else None


def _city_coordinates(city: str) -> tuple[float, float] | None:
    key = city.casefold()
    if key in _FALLBACK_CITIES:
        return _FALLBACK_CITIES[key]
    try:
        import geonamescache
        cities = geonamescache.GeonamesCache().get_cities()
    except ImportError:
        return None
    matches = [value for value in cities.values() if str(value.get("name", "")).casefold() == key]
    if len(matches) != 1:
        return None
    return float(matches[0]["latitude"]), float(matches[0]["longitude"])


class EligibilityStatus(str, Enum):
    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EligibilityResult:
    status: EligibilityStatus
    detail: str | None = None


# Labels that describe a group which contains Germany. They are only ever used to avoid excluding a
# job, never to exclude one, so an unfamiliar grouping stays unknown instead of becoming a rejection.
_INCLUSIVE_GROUPS = ("worldwide", "global", "anywhere", "europe", "european union", "european economic area", "eea", "emea", "eu")
# Minimal fallback so the German market works even without the optional geonamescache dataset.
_HOME_ALIASES = {"germany": ("germany", "deutschland", "de", "federal republic of germany")}


def _matching_group(entry: str) -> bool:
    normalized = entry.casefold()
    return any(normalized == group or re.search(rf"\b{re.escape(group)}\b", normalized) for group in _INCLUSIVE_GROUPS)


def home_country_aliases(country: str | None) -> set[str]:
    """Names and codes that identify the country a job would have to be open to."""
    if not country:
        return set()
    key = str(country).strip().casefold()
    aliases = set(_HOME_ALIASES.get(key, ()))
    aliases.add(key)
    try:
        import geonamescache
        countries = geonamescache.GeonamesCache().get_countries()
    except Exception:
        return aliases
    for code, value in countries.items():
        name = str(value.get("name", "")).casefold()
        if key in {name, code.casefold()}:
            aliases.update({name, code.casefold()})
    return aliases


def _summarize(entries: list[str]) -> str:
    if len(entries) <= 3:
        return ", ".join(entries)
    return "%s and %s more" % (", ".join(entries[:2]), len(entries) - 2)


def resolve_eligibility(metadata: dict, home_country: str | None) -> EligibilityResult:
    """Interpret structured country restrictions published by a source, such as Himalayas tags.

    Only the structured list is used: an empty list means the source marks the role as open
    worldwide, while a missing field means the source says nothing. The result is UNKNOWN whenever
    the home country cannot be established, so a job is never excluded on a guess.
    """
    if "location_restrictions" not in metadata:
        return EligibilityResult(EligibilityStatus.UNKNOWN)
    aliases = home_country_aliases(home_country)
    if not aliases:
        return EligibilityResult(EligibilityStatus.UNKNOWN)
    entries = [str(entry).strip() for entry in metadata.get("location_restrictions") or [] if str(entry).strip()]
    if not entries:
        return EligibilityResult(EligibilityStatus.ALLOWED, "worldwide")
    if any(entry.casefold() in aliases or _matching_group(entry) for entry in entries):
        return EligibilityResult(EligibilityStatus.ALLOWED, _summarize(entries))
    return EligibilityResult(EligibilityStatus.RESTRICTED, _summarize(entries))


def resolve_location(location: str | None, preferences: dict) -> LocationResult:
    city = extract_city(location)
    origin = str(preferences.get("origin", "")).strip()
    origin_coordinates = _city_coordinates(origin) if origin else None
    coordinates = _city_coordinates(city) if city else None
    if not origin_coordinates or not coordinates:
        return LocationResult(LocationStatus.UNKNOWN, city=city, origin_resolved=origin_coordinates is not None, job_location_resolved=coordinates is not None)
    lat1, lon1 = map(math.radians, origin_coordinates)
    lat2, lon2 = map(math.radians, coordinates)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    distance = 6371.0088 * 2 * math.asin(math.sqrt(haversine))
    status = LocationStatus.WITHIN_RADIUS if distance <= float(preferences["max_distance_km"]) else LocationStatus.OUTSIDE_RADIUS
    return LocationResult(status, city=city, distance_km=distance)
