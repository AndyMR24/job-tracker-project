"""Public Bundesagentur für Arbeit Jobsuche adapter."""
from __future__ import annotations

import base64
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class BAError(RuntimeError):
    pass


_APPLICATION_LINK = re.compile(r"Bewerbungsformular\s*:\s*\[[^\]]+\]\(\s*(https?://[^)\s]+)\s*\)", re.IGNORECASE)


class BASource:
    search_endpoint = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
    detail_endpoint = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{}"

    def search(self, query: str, location: str | None = None, page: int = 1, size: int = 5) -> list[dict]:
        self.partial_errors: list[str] = []
        params = {"was": query, "page": page, "size": min(size, 10), "angebotsart": 1}
        if location:
            params["wo"] = location
        payload = self._get(self.search_endpoint + "?" + urllib.parse.urlencode(params))
        items = payload.get("ergebnisliste", []) if isinstance(payload, dict) else []
        if isinstance(items, dict):
            items = items.get("stellenangebote", [])
        if not isinstance(items, list):
            raise BAError("BA Jobsuche returned an unexpected search-results shape.")
        jobs = []
        for index, item in enumerate(items, start=1):
            title = item.get("stellenangebotsTitel") if isinstance(item, dict) else None
            if not isinstance(title, str) or not title.strip():
                self.partial_errors.append(f"search result {index} skipped: missing job title")
                continue
            ref = item.get("referenznummer") or item.get("refnr")
            ref = str(ref).strip() if ref is not None and str(ref).strip() else None
            if ref:
                try:
                    detail = self.detail(ref)
                except BAError as exc:
                    self.partial_errors.append(
                        f"detail for reference {ref} failed ({exc}); retained available search-result data"
                    )
                    detail = {}
            else:
                detail = {}
                self.partial_errors.append(
                    f"search result {index} has no reference; retained available search-result data"
                )
            jobs.append(_map(item, detail))
        return jobs

    def detail(self, reference: str) -> dict:
        encoded = base64.b64encode(reference.encode("utf-8")).decode("ascii")
        return self._get(self.detail_endpoint.format(urllib.parse.quote(encoded, safe="")))

    def _get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "X-API-Key": "jobboerse-jobsuche", "User-Agent": "job-searching-agent/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise BAError("BA Jobsuche request could not be completed.") from exc
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BAError("BA Jobsuche returned non-JSON data.") from exc
        if not isinstance(payload, dict):
            raise BAError("BA Jobsuche returned an unexpected response shape.")
        return payload


def _map(item: dict, detail: dict) -> dict:
    locations = detail.get("stellenlokationen") or detail.get("arbeitsorte") or item.get("stellenlokationen") or []
    location = _location(locations)
    location_metadata = _location_metadata(locations)
    detail_title = detail.get("stellenangebotsTitel")
    title = detail_title.strip() if isinstance(detail_title, str) and detail_title.strip() else item.get("stellenangebotsTitel")
    description = detail.get("stellenangebotsBeschreibung") or detail.get("stellenbeschreibung")
    ref = item.get("referenznummer") or item.get("refnr") or detail.get("referenznummer")
    # The Jobsuche search and detail responses may expose the employer application link as
    # `externeURL` (capital URL). When neither response provides one, a clearly labelled
    # `Bewerbungsformular` Markdown link is the only conservative fallback. `allianzpartnerUrl` is
    # a partner/employer domain, not a vacancy URL, so it is deliberately not used.
    external_url = item.get("externeURL") or detail.get("externeURL") or item.get("externeUrl") or detail.get("externeUrl")
    if not external_url:
        match = _APPLICATION_LINK.search(description or "")
        if match:
            candidate = match.group(1)
            parsed = urllib.parse.urlsplit(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                external_url = candidate
    return {"title": title, "company": item.get("firma") or detail.get("arbeitgeber"), "location": location, "description": description, "employment_type": detail.get("angebotsart") or item.get("angebotsart"), "arrangement": "unknown", "source": "ba", "source_url": external_url, "external_job_id": str(ref) if ref else None, "metadata": {"homeoffice_possible": item.get("homeofficemoeglich"), "homeoffice_type": item.get("homeofficetyp"), "homeoffice_percent": item.get("homeofficeprozent"), "published_at": item.get("datumErsteVeroeffentlichung"), "modified_at": item.get("aenderungsdatum"), "distance": item.get("entfernung"), "beruf": item.get("hauptberuf"), "alternative_jobs": [item.get("alternativBeruf1"), item.get("alternativBeruf2")], "all_jobs": item.get("alleBerufe"), **location_metadata}}


def _location(locations: object) -> str | None:
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list) or not locations:
        return None
    first = locations[0]
    if not isinstance(first, dict):
        return str(first).strip() or None
    address = first.get("adresse")
    address = address if isinstance(address, dict) else first
    city = address.get("ort") or first.get("ort")
    return str(city).strip() if city else None


def _location_metadata(locations: object) -> dict:
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list) or not locations or not isinstance(locations[0], dict):
        return {"postal_code": None, "street": None, "region": None, "country": None, "latitude": None, "longitude": None}
    first = locations[0]
    address = first.get("adresse")
    address = address if isinstance(address, dict) else first
    return {
        "postal_code": address.get("plz") or first.get("plz"),
        "street": address.get("strasse") or first.get("strasse"),
        "region": address.get("region") or first.get("region"),
        "country": address.get("land") or first.get("land"),
        "latitude": first.get("breite") or first.get("latitude"),
        "longitude": first.get("laenge") or first.get("longitude"),
    }
    return ", ".join(str(first[key]) for key in ("ort", "region", "land") if first.get(key)) or None
