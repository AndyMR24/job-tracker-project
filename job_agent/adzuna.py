"""Small Adzuna API source adapter.

The source stops at the fields returned by Adzuna's search API. It never
follows redirect URLs or sends candidate information.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class AdzunaError(RuntimeError):
    """A safe, user-facing Adzuna request or response error."""


def load_local_env(path: str | Path) -> None:
    """Load only the two supported Adzuna variables from a local .env file."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in {"ADZUNA_APP_ID", "ADZUNA_APP_KEY"} or os.environ.get(name):
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


class AdzunaSource:
    def __init__(self, env_path: str | Path | None = None):
        load_local_env(env_path or Path(".env"))
        self.app_id = os.environ.get("ADZUNA_APP_ID")
        self.app_key = os.environ.get("ADZUNA_APP_KEY")
        missing = [name for name, value in (("ADZUNA_APP_ID", self.app_id), ("ADZUNA_APP_KEY", self.app_key)) if not value]
        if missing:
            raise AdzunaError(f"Missing Adzuna credentials: {', '.join(missing)}")

    def search(self, query: str, location: str | None = None, page: int = 1, results_per_page: int = 20) -> list[dict]:
        params = {"app_id": self.app_id, "app_key": self.app_key, "what": query, "results_per_page": str(results_per_page), "content-type": "application/json"}
        if location:
            params["where"] = location
        url = "https://api.adzuna.com/v1/api/jobs/de/search/{}?{}".format(page, urllib.parse.urlencode(params))
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "job-searching-agent/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise AdzunaError(f"Adzuna request failed with HTTP status {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AdzunaError("Adzuna request could not be completed.") from exc
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdzunaError("Adzuna returned a non-JSON response.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise AdzunaError("Adzuna returned an unexpected response shape.")
        jobs = []
        for result in payload["results"]:
            if not isinstance(result, dict) or not result.get("id") or not result.get("title"):
                raise AdzunaError("Adzuna returned a job without a required ID or title.")
            company = result.get("company") or {}
            job_location = result.get("location") or {}
            category = result.get("category") or {}
            salary_min = result.get("salary_min")
            salary_max = result.get("salary_max")
            salary = None
            if salary_min is not None or salary_max is not None:
                salary = f"{salary_min if salary_min is not None else '?'}-{salary_max if salary_max is not None else '?'}"
            jobs.append({"title": result["title"], "company": company.get("display_name"), "location": job_location.get("display_name"), "description": result.get("description"), "salary": salary, "employment_type": result.get("contract_time"), "source": "adzuna", "source_url": result.get("redirect_url"), "external_job_id": str(result["id"]), "metadata": {"category": category, "created": result.get("created"), "salary_is_predicted": result.get("salary_is_predicted"), "adref": result.get("adref"), "description_is_snippet": True}})
        return jobs


