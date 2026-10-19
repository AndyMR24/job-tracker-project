"""Public Bundesagentur für Arbeit Jobsuche adapter."""
from __future__ import annotations

import base64
import json
import re
import urllib.parse
import urllib.request


class BAError(RuntimeError):
    pass


_APPLICATION_LINK = re.compile(r"Bewerbungsformular\s*:\s*\[[^\]]+\]\(\s*(https?://[^)\s]+)\s*\)", re.IGNORECASE)


class BASource:
    search_endpoint = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
    detail_endpoint = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{}"

    def search(self, query: str, location: str | None = None, page: int = 1, size: int = 5) -> list[dict]:
        params = {"was": query, "page": page, "size": min(size, 10), "angebotsart": 1}
        if location:
            params["wo"] = location
        payload = self._get(self.search_endpoint + "?" + urllib.parse.urlencode(params))
        items = payload.get("ergebnisliste", []) if isinstance(payload, dict) else []
        if isinstance(items, dict):
            items = items.get("stellenangebote", [])
        jobs = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get("stellenangebotsTitel"):
                continue
            ref = item.get("referenznummer") or item.get("refnr")
            detail = self.detail(ref) if ref else {}
            jobs.append(_map(item, detail))
        return jobs

    def detail(self, reference: str) -> dict:
        encoded = base64.b64encode(reference.encode("utf-8")).decode("ascii")
        return self._get(self.detail_endpoint.format(urllib.parse.quote(encoded, safe="")))

    def _get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "X-API-Key": "jobboerse-jobsuche", "User-Agent": "job-searching-agent/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            raise BAError("BA Jobsuche request could not be completed.") from exc
        if not isinstance(payload, dict):
            raise BAError("BA Jobsuche returned an unexpected response shape.")
        return payload


def _map(item: dict, detail: dict) -> dict:
    locations = item.get("stellenlokationen") or detail.get("arbeitsorte") or []
    location = _location(locations)
    title = detail.get("stellenangebotsTitel") or item.get("stellenangebotsTitel")
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
    return {"title": title, "company": item.get("firma") or detail.get("arbeitgeber"), "location": location, "description": description, "employment_type": detail.get("angebotsart") or item.get("angebotsart"), "arrangement": "unknown", "source": "ba", "source_url": external_url, "external_job_id": str(ref) if ref else None, "metadata": {"homeoffice_possible": item.get("homeofficemoeglich"), "homeoffice_type": item.get("homeofficetyp"), "homeoffice_percent": item.get("homeofficeprozent"), "published_at": item.get("datumErsteVeroeffentlichung"), "modified_at": item.get("aenderungsdatum"), "distance": item.get("entfernung"), "beruf": item.get("hauptberuf"), "alternative_jobs": [item.get("alternativBeruf1"), item.get("alternativBeruf2")], "all_jobs": item.get("alleBerufe")}}


def _location(locations: object) -> str | None:
    if isinstance(locations, dict):
        locations = [locations]
    if not isinstance(locations, list) or not locations:
        return None
    first = locations[0]
    if not isinstance(first, dict):
        return str(first)
    return ", ".join(str(first[key]) for key in ("ort", "region", "land") if first.get(key)) or None
