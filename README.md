# Job Searching Agent

A local-first Python application for finding and tracking jobs in Germany. It searches public job
sources, evaluates every listing against your own profile and preferences, explains why a job does or
does not fit, records your decisions and application progress, and drafts truthful job-specific CVs.

It never submits an application, never contacts employers, and never sends your profile or CV to any
service.

## What it does

- **Discovery** - runs your configured queries against four public sources (Adzuna, Nomado24,
  Himalayas and the German Federal Employment Agency job board) and normalizes the results into one
  internal job shape.
- **Explainable fit** - every job gets a score plus strong matches, potential gaps, important
  concerns and uncertainties. Hard exclusions are limited to explicit mismatches such as a senior
  role, a required Master's degree, a location outside your radius, or a country restriction that
  excludes you.
- **Decisions and history** - save jobs, reject them with a reason, and keep a local audit trail of
  what the tool did.
- **Application tracking** - record your own applications and their status; the tool only records
  what you did.
- **CV drafts** - generate a LaTeX/PDF draft tailored to one job, assembled only from facts in your
  profile. It reorders, re-words and shortens; it never invents experience, skills or qualifications.
- **Two interfaces** - a CLI and a local browser dashboard over the same SQLite database, the same
  evaluator and the same rules.

## Architecture summary

```
job_agent/
  cli.py          command line entry point (job-agent ...)
  discovery.py    public-search orchestration and the normalize/evaluate/store pipeline
  profile.py      profile and search-configuration loading and validation
  normalizer.py   conservative mapping of raw listings into the internal Job model
  evaluator.py    transparent rule-based fit evaluation
  location.py     offline city resolution, radius checks, country-restriction interpretation
  storage.py      local SQLite persistence and audit events
  cv.py           LaTeX CV drafts built only from profile facts
  permissions.py  gate for future external actions; application submission is always blocked
  maintenance.py  re-evaluation of already-stored jobs (job-agent re-evaluate)
  dashboard.py    read-only projections for the web interface
  webui.py        server-rendered HTML for the web interface
  webapp.py       local HTTP server for the web interface
  adzuna.py, nomado24.py, himalayas.py, ba.py   public job sources
  search.py       legacy, inactive DuckDuckGo helper
```

The CLI is the reference interface; the dashboard reuses the same modules rather than duplicating
logic.

## Requirements

- Python 3.11 or later.
- `geonamescache` - installed automatically, used for offline city coordinates and country aliases.
- Optional: a LaTeX distribution providing `pdflatex`, needed only to generate CV PDFs.
- Optional: free Adzuna API credentials, needed only to query Adzuna.

## Setup

```bash
git clone <your-fork-url>
cd job-tracking-agent
python -m pip install -e .
```

Then create your two local configuration files by copying the tracked examples:

```bash
cp data/profile.example.json data/profile.json
cp data/search_config.example.json data/search_config.json
```

- `data/profile.json` holds your factual profile (identity, contact, education, skills, projects,
  thesis, languages, certifications, employment eligibility). Replace every placeholder with your
  own facts; never add facts you cannot support.
- `data/search_config.json` holds your preferences (target roles, locations, work arrangements,
  commute radius, search queries, `preferred_languages`) and `master_cv_path`, which points at your
  master CV if you want CV drafts.

Adzuna credentials are read from the environment or from a local `.env` file in the project root:

```
ADZUNA_APP_ID=your-adzuna-app-id
ADZUNA_APP_KEY=your-adzuna-app-key
```

Check everything with `job-agent validate`.

## Usage - CLI

| Command | Purpose |
| --- | --- |
| `job-agent validate` | check the profile, search configuration and master CV path |
| `job-agent search` | run every configured query against all sources |
| `job-agent search --query "Data Analyst" --source ba` | run one query against one source |
| `job-agent ingest jobs.json` | import public listings you saved yourself |
| `job-agent list` | list stored jobs by fit score |
| `job-agent view JOB_ID` | show one job with its full evaluation |
| `job-agent save JOB_ID` / `job-agent reject JOB_ID --reason "too far"` | record a decision |
| `job-agent tailor JOB_ID` | generate a tailored CV draft in `output/` |
| `job-agent application JOB_ID applied --date 2026-01-01` | track an application you sent |
| `job-agent applications` / `job-agent history` | review applications and the audit trail |
| `job-agent re-evaluate` | refresh stored evaluations after changing profile or rules |
| `job-agent permission-check ACTION DESTINATION DATA --approve` | record a one-time local approval for a future external action; it never transmits data and always refuses the `submit_application` action |
| `job-agent dashboard` | serve the local web interface |

## Usage - dashboard

```bash
job-agent dashboard            # or: python -m job_agent.webapp
```

Then open http://127.0.0.1:8770/. The dashboard offers an overview, job browsing with filters and
sorting, job detail with the full evaluation and the original posting link, save/reject actions,
saved jobs, application tracking, search history, source statistics, background searches and CV
generation with PDF download.

It binds to `127.0.0.1` by default and has no authentication, so keep it local. Widen the binding
with `--host` only if you understand that your local data becomes reachable on that network.

## Data, privacy and limitations

- Everything is local: `data/job_agent.sqlite3` for jobs, decisions, applications, CV metadata and
  audit events, and `output/` for generated CV drafts. Both are ignored by Git.
- Only public search text, an optional location filter and (for Adzuna) your API keys leave your
  machine. Your profile, CV and local records are never transmitted.
- No credentials are stored in the database and application submission is always blocked.
- Fit scores describe how well a listing matches your profile and preferences. They are not a
  hiring probability, and nothing here is legal advice.
- Deployment, decisions and applications remain yours: review every draft before sending it.

## Testing

```bash
python -m pip install -e .[test]
python -m unittest discover -s tests
```

The suite uses synthetic fixtures (`tests/support.py`), temporary databases and stub source
adapters, so it needs no personal data, no credentials and no network access. CV tests that shell
out to LaTeX are skipped when `pdflatex` is unavailable.

## Project documents

- `USER_MANUAL.md` - the full walkthrough for using the application.
- `DEVELOPMENT.md` - architecture notes, conventions and development workflow.
- `SPECIFICATION.md` - the original requirements this implementation follows.
- `PROGRESS.md` - verified state, remaining work and known limitations.

## Status

An MVP, deliberately small: one evaluator, four public sources, exact URL/job-ID duplicate
prevention, no browser automation and no automatic applications. A license file is not included yet,
so choosing a license is still an open decision for the owner.
