"""Local LaTeX CV drafts assembled only from profile facts."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import Job
from .profile import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "resume.tex"
FACTS = ["education", "projects", "skills", "languages", "certifications"]


def _escape_latex(value: object) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(char, char) for char in str(value))


def _replace_template(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _select_bullets(item: dict, required: set[str]) -> list[str]:
    candidate = item.get("candidate_bullets", [])
    general = item.get("general_bullets", [])
    relevant = [bullet for bullet in candidate if any(term and term in bullet.lower() for term in required)]
    source = relevant if len(relevant) >= 2 else general or candidate
    selected = []
    for bullet in source:
        if bullet not in selected:
            selected.append(bullet)
        if len(selected) == 3:
            break
    return selected


def generate(job: Job, profile: Profile, output: str | Path) -> tuple[Path, list[str]]:
    data = profile.data
    required = {r.text.lower() for r in job.requirements}
    chosen_skills = [s for s in data["skills"] if s["name"].lower() in required] or data["skills"]
    thesis = data.get("thesis")
    thesis_name = thesis.get("name", "").strip().lower() if thesis else ""
    normal_projects = [p for p in data["projects"] if p.get("name", "").strip().lower() != thesis_name]
    projects = [p for p in normal_projects if required & {s.lower() for s in p["technologies"]}]
    project_heading = "Relevant projects" if projects else "Projects"
    projects = projects or normal_projects
    education_lines = []
    for item in data["education"]:
        education_lines.append(r"\CVEducation{%s}{%s}{%s}{%s}" % (_escape_latex(item["degree"]), _escape_latex(item["institution"]), _escape_latex(item["period"]), _escape_latex(item.get("detail", ""))))
    project_lines = [r"\CVProject{%s}{%s}{%s}" % (_escape_latex(project["name"]), _escape_latex(", ".join(project["technologies"])), "".join(r"\CVBullet{%s}" % _escape_latex(bullet) for bullet in _select_bullets(project, required))) for project in projects]
    thesis_line = r"\CVProject{%s}{%s}{%s}" % (_escape_latex(thesis["name"]), _escape_latex(", ".join(thesis["technologies"])), "".join(r"\CVBullet{%s}" % _escape_latex(bullet) for bullet in _select_bullets(thesis, required))) if thesis else ""
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
