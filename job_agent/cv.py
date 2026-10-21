"""Local LaTeX CV drafts assembled only from profile facts."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Job
from .profile import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "resume.tex"
FACTS = ["education", "projects", "skills", "languages", "certifications"]
MAX_PROJECT_ENTRIES = 4
_WORD = re.compile(r"[a-z0-9+#]+")
_IGNORED_TERMS = {
    "a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with",
    "project", "projects", "experience", "experienced", "year", "years",
    "degree", "master", "bachelor", "phd", "doctorate", "required", "must",
    "service", "services",
}
_TOKEN_ALIASES = {"learning": "learn"}


def _escape_latex(value: object) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(char, char) for char in str(value))


def _replace_template(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _text_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [text for item in value if (text := _text(item))]


def _tokens(value: object) -> list[str]:
    return [
        _TOKEN_ALIASES.get(token, token)
        for token in _WORD.findall(_text(value).casefold())
        if token not in _IGNORED_TERMS
    ]


def _job_terms(job: Job) -> dict[str, int]:
    terms: dict[str, int] = {}

    def add(value: object, weight: int) -> None:
        for token in _tokens(value):
            terms[token] = max(terms.get(token, 0), weight)

    for requirement in job.requirements:
        weight = 4 if requirement.kind == "mandatory" else 2 if requirement.kind in {"preferred", "useful"} else 1
        add(requirement.text, weight)
    add(job.title, 2)
    add(job.qualifications, 1)
    add(job.responsibilities, 1)
    add(job.description, 1)
    return terms


def _project_text(project: dict) -> str:
    parts = [_text(project.get("description"))]
    for field in ("candidate_bullets", "general_bullets"):
        parts.extend(_text_list(project.get(field)))
    return " ".join(parts)


def _project_evidence(project: dict, job_terms: dict[str, int]) -> tuple[int, int, int]:
    technologies = set(_tokens(" ".join(_text_list(project.get("technologies")))))
    name = set(_tokens(project.get("name")))
    text = set(_tokens(_project_text(project)))
    technology_score = 0
    descriptive_score = 0
    name_score = 0
    for term, weight in job_terms.items():
        if term in technologies:
            technology_score += weight * 3
        elif term in text:
            descriptive_score += weight * 2
        elif term in name:
            name_score += weight
    return technology_score, descriptive_score, name_score


def _rank_projects(projects: list[dict], job_terms: dict[str, int]) -> list[tuple[int, int, int, int, dict]]:
    ranked = []
    for index, project in enumerate(projects):
        if not _text(project.get("name")):
            continue
        technology, descriptive, name = _project_evidence(project, job_terms)
        ranked.append((technology, descriptive, name, index, project))
    if any(item[0] > 0 for item in ranked):
        return sorted(ranked, key=lambda item: (-item[0], item[3]))
    return sorted(ranked, key=lambda item: (-item[1], -item[2], item[3]))


def _select_projects(job: Job, data: dict) -> tuple[list[dict], str]:
    thesis = data.get("thesis")
    thesis = thesis if isinstance(thesis, dict) else None
    thesis_name = _text(thesis.get("name")).casefold() if thesis else ""
    raw_projects = data.get("projects", [])
    normal_projects = [
        project for project in raw_projects
        if isinstance(project, dict)
        and _text(project.get("name"))
        and _text(project.get("name")).casefold() != thesis_name
    ] if isinstance(raw_projects, list) else []
    project_limit = MAX_PROJECT_ENTRIES - (1 if thesis_name else 0)
    ranked = _rank_projects(normal_projects, _job_terms(job))
    selected = ranked[:project_limit]
    heading = "Relevant projects" if any(any(item[:3]) for item in selected) else "Projects"
    return [item[4] for item in selected], heading


def _select_bullets(item: dict, required: set[str]) -> list[str]:
    candidate = _text_list(item.get("candidate_bullets"))
    general = _text_list(item.get("general_bullets"))
    required_tokens = {token for term in required for token in _tokens(term)}
    relevant = [bullet for bullet in candidate + general if required_tokens & set(_tokens(bullet))]
    ordered = relevant + candidate + general
    selected = []
    for bullet in ordered:
        if bullet not in selected:
            selected.append(bullet)
        if len(selected) == 3:
            break
    return selected


def versioned_output_path(output_dir: str | Path, job_id: int) -> Path:
    """Return a new PDF path whose paired .tex file cannot overwrite an earlier artifact."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(output_dir) / f"cv_job_{job_id}_{stamp}_{uuid.uuid4().hex[:8]}.pdf"


def generate(job: Job, profile: Profile, output: str | Path) -> tuple[Path, list[str]]:
    data = profile.data
    required = set(_job_terms(job))
    skill_requirements = {r.text.lower() for r in job.requirements}
    chosen_skills = [s for s in data["skills"] if s["name"].lower() in skill_requirements] or data["skills"]
    thesis = data.get("thesis")
    thesis = thesis if isinstance(thesis, dict) else None
    thesis_name = _text(thesis.get("name")).casefold() if thesis else ""
    projects, project_heading = _select_projects(job, data)
    education_lines = []
    for item in data["education"]:
        education_lines.append(r"\CVEducation{%s}{%s}{%s}{%s}" % (_escape_latex(item["degree"]), _escape_latex(item["institution"]), _escape_latex(item["period"]), _escape_latex(item.get("detail", ""))))
    project_lines = [
        r"\CVProject{%s}{%s}{%s}" % (
            _escape_latex(_text(project.get("name"))),
            _escape_latex(", ".join(_text_list(project.get("technologies")))),
            "".join(r"\CVBullet{%s}" % _escape_latex(bullet) for bullet in _select_bullets(project, required)),
        )
        for project in projects
    ]
    thesis_line = r"\CVProject{%s}{%s}{%s}" % (
        _escape_latex(thesis_name and _text(thesis.get("name"))),
        _escape_latex(", ".join(_text_list(thesis.get("technologies")))),
        "".join(r"\CVBullet{%s}" % _escape_latex(bullet) for bullet in _select_bullets(thesis, required)),
    ) if thesis_name else ""
    language_lines = [r"\CVLanguage{%s}{%s}" % (_escape_latex(language), _escape_latex(level)) for language, level in data["languages"].items()]
    certification_lines = [r"\CVItem{%s}" % _escape_latex(item) for item in data["certifications"]]
    contact = data.get("contact", {})
    phone = contact.get("phone")
    email = contact.get("email")
    github = contact.get("github")
    linkedin = contact.get("linkedin")
    contact_primary = " | ".join(filter(None, [_escape_latex(phone) if phone else "", r"\href{mailto:%s}{%s}" % (_escape_latex(email), _escape_latex(email)) if email else ""]))
    github_label = github.removeprefix("https://").rstrip("/") if github else ""
    linkedin_label = linkedin.removeprefix("https://").rstrip("/") if linkedin else ""
    contact_social = " | ".join(filter(None, [r"\href{%s}{%s}" % (_escape_latex(github), _escape_latex(github_label)) if github else "", r"\href{%s}{%s}" % (_escape_latex(linkedin), _escape_latex(linkedin_label)) if linkedin else ""]))
    values = {"NAME": _escape_latex(data["identity"]["name"]), "CITY": _escape_latex(data["identity"]["city"]), "CONTACT_PRIMARY": contact_primary, "CONTACT_SOCIAL": contact_social, "EDUCATION": "\n".join(education_lines), "PROJECT_HEADING": _escape_latex(project_heading), "THESIS": thesis_line, "PROJECTS": "\n".join(project_lines), "SKILLS": _escape_latex(", ".join(s["name"] for s in chosen_skills)), "LANGUAGES": "\n".join(language_lines), "CERTIFICATIONS": "\n".join(certification_lines)}
    template = _replace_template(TEMPLATE.read_text(encoding="utf-8"), values)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tex_output = path.with_suffix(".tex")
    tex_output.write_text(template, encoding="utf-8")
    executable = shutil.which("pdflatex")
    if not executable:
        raise RuntimeError("pdflatex was not found on PATH. Install a LaTeX distribution and ensure pdflatex is available.")
    with tempfile.TemporaryDirectory(prefix="job-agent-cv-") as directory:
        workdir = Path(directory)
        tex_path = workdir / "resume.tex"
        shutil.copyfile(tex_output, tex_path)
        try:
            result = subprocess.run([executable, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"], cwd=workdir, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise RuntimeError(f"Could not run pdflatex: {exc}") from exc
        if result.returncode != 0:
            details = (result.stdout + "\n" + result.stderr).strip().splitlines()
            detail = next((line.strip() for line in reversed(details) if line.strip()), "unknown LaTeX error")
            raise RuntimeError(f"LaTeX CV compilation failed: {detail}")
        compiled = workdir / "resume.pdf"
        if not compiled.exists():
            raise RuntimeError("LaTeX CV compilation completed without producing a PDF.")
        shutil.copyfile(compiled, path)
    return path, FACTS.copy()
