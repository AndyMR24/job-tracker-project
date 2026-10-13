"""Public Nomado24 job-search adapter."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


class Nomado24Error(RuntimeError):
    pass


class Nomado24Source:
    endpoint = "https://api.nomado24.de/api/public/v1/jobs"

    def search(
        self,
        query: str,
        location: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        params = {
            "q": query,
            "page": page,
            "per_page": min(per_page, 100),
        }
        if location:
            params["location"] = location

        request = urllib.request.Request(
            self.endpoint + "?" + urllib.parse.urlencode(params),
            headers={
                "Accept": "application/json",
                "User-Agent": "job-searching-agent/0.1",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(
                    response.read().decode("utf-8", "replace")
                )
        except Exception as exc:
            raise Nomado24Error(
                "Nomado24 request could not be completed."
            ) from exc

        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            items = payload["data"]
        elif isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
            items = payload["jobs"]
        elif isinstance(payload, list):
            items = payload
        else:
            raise Nomado24Error(
                "Nomado24 returned an unexpected response shape."
            )

        jobs = []
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue

            remote = item.get("remote") is True
            arrangement = str(
                item.get("workArrangement") or ""
            ).lower()

            if arrangement not in {"remote", "hybrid", "onsite"}:
                arrangement = "remote" if remote else "unknown"

            external_id = (
                item.get("id")
                or item.get("jobId")
                or item.get("url")
            )

            seniority = item.get("seniority")
            if isinstance(seniority, list):
                seniority = seniority[0] if seniority else None
            elif seniority is not None:
                seniority = str(seniority)

            jobs.append(
                {
                    "title": item["title"],
                    "company": item.get("companyName"),
                    "location": item.get("location"),
                    "arrangement": arrangement,
                    "description": item.get("description"),
                    "salary": _salary(item),
                    "employment_type": item.get("employmentType"),
                    "source": "nomado24",
                    "source_url": item.get("url"),
                    "external_job_id": (
                        str(external_id) if external_id else None
                    ),
                    "metadata": {
                        "language": item.get("language"),
                        "tags": item.get("tags"),
                        "published_at": item.get("publishedAt"),
                        "currency": item.get("currency"),
                    },
                }
            )

        return jobs


def _salary(item: dict) -> str | None:
    low, high = item.get("salaryMin"), item.get("salaryMax")

    if low is None and high is None:
        return None

    return (
        f"{low if low is not None else '?'}-"
        f"{high if high is not None else '?'} "
        f"{item.get('currency') or ''}"
    ).strip()
