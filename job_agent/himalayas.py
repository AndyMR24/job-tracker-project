"""Public Himalayas job-search adapter."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


class HimalayasError(RuntimeError):
    pass


class HimalayasSource:
    endpoint = "https://himalayas.app/jobs/api/search"

    def search(self, query: str, page: int = 1) -> list[dict]:
        params = {"q": query, "page": page}
        request = urllib.request.Request(self.endpoint + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/json", "User-Agent": "job-searching-agent/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            raise HimalayasError("Himalayas request could not be completed.") from exc
        items = payload.get("jobs", payload.get("data", [])) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise HimalayasError("Himalayas returned an unexpected response shape.")
        jobs = []

        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            remote = item.get("remote") is True or item.get("isRemote") is True
            restrictions = item.get("locationRestrictions") or []

            seniority = item.get("seniority", "unknown")
            if isinstance(seniority, list):
                seniority = ", ".join(str(value) for value in seniority)

            jobs.append({"title": item["title"], "company": _company(item), "location": _location(item), "arrangement": "remote" if remote else "unknown", "description": item.get("description"), "salary": _salary(item), "employment_type": item.get("employmentType"), "seniority": seniority, "source": "himalayas", "source_url": item.get("applicationLink") or item.get("url"), "external_job_id": str(item.get("guid") or item.get("id") or item.get("url")) if (item.get("guid") or item.get("id") or item.get("url")) else None, "metadata": {"location_restrictions": restrictions, "timezone_restrictions": item.get("timezoneRestrictions"), "categories": item.get("categories"), "published_at": item.get("publishedAt"), "expires_at": item.get("expiresAt"), "worldwide": not restrictions}})

        return jobs


def _company(item: dict) -> str | None:
    company = item.get("company")
    return company.get("name") if isinstance(company, dict) else company or item.get("companyName")


def _location(item: dict) -> str | None:
    value = item.get("location")
    return ", ".join(value) if isinstance(value, list) else value


def _salary(item: dict) -> str | None:
    low, high = item.get("salaryMin"), item.get("salaryMax")
    if low is None and high is None:
        return None
    return f"{low if low is not None else '?'}-{high if high is not None else '?'} {item.get('currency') or ''}".strip()
