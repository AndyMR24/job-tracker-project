"""Synthetic fixtures for the test suite.

The tests must never depend on a real candidate profile, search configuration, source CV or
database, so every module builds its data from these helpers instead.
"""
from __future__ import annotations

import json
from pathlib import Path

SAMPLE_EMAIL = "sample.candidate@example.invalid"
SAMPLE_PHONE = "+49 000 0000000"
SAMPLE_GITHUB = "https://github.com/example-user/"
SAMPLE_LINKEDIN = "https://www.linkedin.com/in/example-user/"
SAMPLE_THESIS = "Portable and Sample Query Functions"
SAMPLE_PROJECT = "Sample Churn Prediction Project"
SAMPLE_SECOND_PROJECT = "Sample Analytics Dashboard"

_THESIS_BULLETS = ["Implemented the query functions in Python.", "Tested portability across two database systems."]
_THESIS_GENERAL = ["Wrote the thesis describing the approach.", "Benchmarked the query functions.", "Documented the API surface."]


def sample_profile() -> dict:
    """A fictional candidate that satisfies every field the application reads."""
    return {
        "identity": {"name": "Sample Candidate", "city": "Sample City, Germany"},
        "contact": {"phone": SAMPLE_PHONE, "email": SAMPLE_EMAIL, "github": SAMPLE_GITHUB, "linkedin": SAMPLE_LINKEDIN},
        "education": [
            {"level": "bachelor", "degree": "Bachelor of Science in Sample Subject", "institution": "Example University", "period": "October 2019 - November 2025", "detail": "Minor in Sample Studies."},
            {"level": "additional education", "degree": "Introductory course in Sample Programming", "institution": "Example Institute", "period": "February 2018 - June 2018", "detail": "Additional education; not a degree."},
        ],
        "professional_experience": False,
        "skills": [
            {"name": "Python", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "SQL", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "Git", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "pandas", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "scikit-learn", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "pytest", "evidence": "Synthetic evidence used by the test suite."},
            {"name": "Java", "evidence": "Synthetic evidence used by the test suite."},
        ],
        "thesis": {"name": SAMPLE_THESIS, "technologies": ["Python", "SQL"], "description": "Synthetic thesis description.", "candidate_bullets": list(_THESIS_BULLETS), "general_bullets": list(_THESIS_GENERAL)},
        "projects": [
            {"name": SAMPLE_THESIS, "technologies": ["Python", "SQL"], "candidate_bullets": list(_THESIS_BULLETS), "general_bullets": list(_THESIS_GENERAL)},
            {"name": SAMPLE_PROJECT, "technologies": ["Python", "pandas", "scikit-learn"], "candidate_bullets": ["Ran the modelling experiment in Python.", "Compared two classification approaches.", "Tuned the model with cross validation.", "Evaluated precision, recall and ROC AUC.", "Documented the pipeline and the results.", "Presented the findings to a study group."], "general_bullets": ["Cleaned and prepared the dataset with pandas.", "Trained and compared classification models with scikit-learn.", "Reported model quality with standard classification metrics."]},
            {"name": SAMPLE_SECOND_PROJECT, "technologies": ["SQL", "Python"], "candidate_bullets": ["Built the reporting views in SQL.", "Exported the results with a Python script."], "general_bullets": ["Designed the reporting tables.", "Automated the weekly export.", "Documented the queries."]},
        ],
        "technical_practice": {"Python": "Synthetic practice note.", "SQL": "Synthetic practice note.", "Web Development": "Synthetic practice note."},
        "languages": {"English": "Fluent", "German": "Intermediate"},
        "certifications": ["Sample Certificate"],
        "employment_eligibility": {"country_of_residence": "Germany", "residence_permit_wording": "Synthetic wording used by the test suite.", "note": "Posting-specific authorization or sponsorship requirements require verification; this is not legal advice."},
        "availability": "As soon as possible",
    }


def sample_config() -> dict:
    """A synthetic search configuration with the same semantics the tests rely on."""
    return {
        "target_roles": ["Data Scientist", "Data Analyst", "Data Engineer", "Machine Learning Engineer", "Python Developer", "Software Developer", "AI/ML"],
        "locations": ["Aachen", "Cologne"],
        "work_arrangements": ["remote", "hybrid", "onsite"],
        "maximum_commute_note": "Synthetic configuration used by the test suite.",
        "location_preferences": {"origin": "Aachen", "max_distance_km": 225, "remote_only_beyond_distance": True},
        "preferred_languages": ["Python"],
        "search_queries": {"primary": ["Data Analyst", "Junior Data Analyst", "Python Developer"], "secondary": ["IT Consultant", "Data Consultant"]},
    }


def write_json(path, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_profile(directory, data=None) -> Path:
    return write_json(Path(directory) / "profile.json", sample_profile() if data is None else data)


def write_config(directory, data=None) -> Path:
    return write_json(Path(directory) / "search_config.json", sample_config() if data is None else data)


def evaluation_cases() -> list[dict]:
    """Representative listings used to pin evaluation output.

    Each entry is a label plus the raw listing passed through `normalize`, so the same set can be
    evaluated before and after a refactor. `tests/evaluation_baseline.json` records the output of
    the pre-configurable-weights implementation for exactly these cases.
    """
    return [
        {"case": "junior hybrid within radius", "job": {"title": "Data Analyst", "location": "Aachen", "arrangement": "hybrid", "requirements": [{"text": "Python", "kind": "mandatory"}]}},
        {"case": "senior title excluded", "job": {"title": "Senior Data Engineer", "requirements": [{"text": "Python", "kind": "mandatory"}]}},
        {"case": "lead title excluded", "job": {"title": "Lead Data Analyst"}},
        {"case": "mandatory master excluded", "job": {"title": "Data Analyst", "requirements": [{"text": "Master's degree", "kind": "mandatory"}]}},
        {"case": "preferred master penalised", "job": {"title": "Data Analyst", "requirements": [{"text": "Master's degree", "kind": "preferred"}]}},
        {"case": "mastery wording hits the degree branch", "job": {"title": "Data Analyst", "requirements": [{"text": "Mastery of Excel", "kind": "mandatory"}]}},
        {"case": "missing mandatory requirement", "job": {"title": "Data Analyst", "requirements": [{"text": "Python", "kind": "mandatory"}, {"text": "Kubernetes", "kind": "mandatory"}]}},
        {"case": "missing preferred requirement", "job": {"title": "Data Analyst", "requirements": [{"text": "Kubernetes", "kind": "preferred"}]}},
        {"case": "unknown requirement kind", "job": {"title": "Data Analyst", "requirements": [{"text": "Tableau"}]}},
        {"case": "experience in years mandatory", "job": {"title": "Data Analyst", "requirements": [{"text": "5 years of experience", "kind": "mandatory"}]}},
        {"case": "experience in years preferred", "job": {"title": "Data Analyst", "requirements": [{"text": "3 years of experience", "kind": "preferred"}]}},
        {"case": "remote job", "job": {"title": "Data Analyst", "arrangement": "remote"}},
        {"case": "remote beyond radius with a US restriction", "job": {"title": "Data Analyst", "arrangement": "remote", "metadata": {"location_restrictions": ["United States"]}}},
        {"case": "remote with a Germany restriction", "job": {"title": "Data Analyst", "arrangement": "remote", "metadata": {"location_restrictions": ["Germany"]}}},
        {"case": "onsite outside the radius", "job": {"title": "Data Analyst", "location": "Munich", "arrangement": "onsite"}},
        {"case": "vague location stays unknown", "job": {"title": "Data Analyst", "location": "Germany", "arrangement": "onsite"}},
        {"case": "description snippet", "job": {"title": "Data Analyst", "metadata": {"description_is_snippet": True}}},
        {"case": "no requirements", "job": {"title": "Data Analyst"}},
        {"case": "sponsorship wording", "job": {"title": "Data Analyst", "description": "We cannot offer visa sponsorship."}},
        {"case": "secondary query title", "job": {"title": "IT Consultant", "location": "Aachen", "arrangement": "hybrid"}},
        {"case": "unrelated title", "job": {"title": "Office Manager", "location": "Aachen", "arrangement": "onsite"}},
        {"case": "mid seniority", "job": {"title": "Data Analyst", "seniority": "mid"}},
        {"case": "mixed senior and junior title", "job": {"title": "Senior Junior Data Analyst"}},
        {"case": "python in qualifications", "job": {"title": "Data Analyst", "qualifications": "Python and SQL"}},
        {"case": "python in the description", "job": {"title": "Data Analyst", "description": "We write Python daily."}},
        {"case": "python in responsibilities", "job": {"title": "Data Analyst", "responsibilities": "Build Python pipelines."}},
        {"case": "hybrid without a location", "job": {"title": "Data Analyst", "arrangement": "hybrid"}},
        {"case": "unknown arrangement", "job": {"title": "Data Analyst", "location": "Aachen"}},
    ]
