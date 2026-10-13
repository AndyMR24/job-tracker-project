"""Small normalized job model used across import, search, analysis, and storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

RequirementKind = Literal["mandatory", "preferred", "useful", "unknown"]


@dataclass
class Requirement:
    text: str
    kind: RequirementKind = "unknown"
    category: str = "skill"


@dataclass
class Job:
    title: str
    company: str | None = None
    location: str | None = None
    arrangement: str = "unknown"
    description: str | None = None
    requirements: list[Requirement] = field(default_factory=list)
    responsibilities: str | None = None
    qualifications: str | None = None
    salary: str | None = None
    employment_type: str | None = None
    seniority: str = "unknown"
    source: str = "unknown"
    source_url: str | None = None
    external_job_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = asdict(self)
        return result

    @classmethod
    def from_dict(cls, value: dict) -> "Job":
        requirements = [Requirement(**item) for item in value.get("requirements", [])]
        return cls(**{**value, "requirements": requirements})

