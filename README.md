# Job Searching Agent

A local-first Python application for finding and tracking jobs in Germany. It searches public job
sources, evaluates every listing against your own profile and preferences, explains why a job does or
does not fit, records your decisions and application progress, and drafts truthful job-specific CVs.

It never submits an application and never contacts employers. The current application code does not
send your profile or CV content to external services.

**New to the project?** [USER_MANUAL.md](USER_MANUAL.md#1-getting-started) is the complete guide: it
covers installation on Windows, the first configuration, day-to-day use and how the scoring works.

## What it does

- **Discovery** - runs your configured queries against four public sources (Adzuna, Nomado24,
  Himalayas and the German Federal Employment Agency job board) and normalizes the results into one
  internal job shape.
- **Explainable fit** - every job gets a score plus strong matches, potential gaps, important
  concerns and uncertainties. Hard exclusions are limited to explicit mismatches such as a senior
  role when your profile records that you have no professional experience, a required Master's degree
  you do not hold, a location outside your radius, or a country restriction that excludes you.
- **Decisions and history** - save jobs, reject them with a reason, and keep a local audit trail of
  what the tool did.
- **Application tracking** - record your own applications and their status; the tool only records
  what you did.
- **CV drafts** - generate a LaTeX/PDF draft tailored to one job, assembled only from facts in your
  profile. It reorders, re-words and shortens; it never invents experience, skills or qualifications.
- **Two interfaces** - a CLI and a local browser dashboard over the same SQLite database, the same
  evaluator and the same rules.

## Architecture summary

The implementation is a small `job_agent/` package: a CLI, one shared discovery pipeline, an
explainable rule-based evaluator, local SQLite storage, LaTeX CV generation and four public source
adapters. [DEVELOPMENT.md](DEVELOPMENT.md) maps every module and explains the design decisions.

The CLI is the reference interface; the dashboard reuses the same modules rather than duplicating
logic.

## Requirements

- Python 3.11 or later.
- `geonamescache` - installed automatically, used for offline city coordinates and country aliases.
- Optional: a LaTeX distribution providing `pdflatex`, needed only to generate CV PDFs.
- Optional: free Adzuna API credentials, needed only to query Adzuna.

## Quick start

These commands install the project on Windows PowerShell.
[USER_MANUAL.md](USER_MANUAL.md#1-getting-started) walks through the same steps in more detail,
including what you should see and how to fix common problems.

```bash
git clone https://github.com/AndyMR24/job-tracker-project.git
cd job-tracker-project
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Then create your two local configuration files by copying the tracked examples:

```bash
cp data/profile.example.json data/profile.json
cp data/search_config.example.json data/search_config.json
```

`data/profile.json` holds the facts about you that the application may use, and
`data/search_config.json` holds your search preferences. Both files are ignored by Git, so a fresh
clone contains only the tracked examples. Replace every placeholder with facts you can support and
never add facts the profile cannot back; [USER_MANUAL.md](USER_MANUAL.md) explains every field.

Adzuna credentials are read from the environment or from a local `.env` file in the project root:

```
ADZUNA_APP_ID=your-adzuna-app-id
ADZUNA_APP_KEY=your-adzuna-app-key
```

Use exactly those two variable names. Credentials are needed only for Adzuna: without them a search
skips Adzuna - reporting the skip - and continues with the other configured sources, while an
Adzuna-only search explains that nothing was searched. Everything else works without them, and
`job-agent validate` does not check them. Credentials that Adzuna rejects are treated as a request
failure rather than a missing source; [USER_MANUAL.md](USER_MANUAL.md) explains what each interface
shows.

Check everything with `job-agent validate`, then start the dashboard with `job-agent dashboard` and
open http://127.0.0.1:8770/ . Press Ctrl+C in that terminal to stop it.

## How jobs are scored

Every stored job gets a score from 0 to 100. Scoring starts at 50 and applies fixed, configurable
rules: +15 when the title matches one of your `target_roles`, +8 for a configured secondary query,
+8 or +4 when your profile confirms a requirement, +3/+2/+1 for a `preferred_languages` mention, +6
for remote work and +4 for hybrid or onsite work inside your radius. Only four findings exclude a
job: a senior role while your profile records no professional experience, an explicitly required
Master's degree while you record a lower completed degree, a location outside your radius unless the
job is explicitly remote, and a published country restriction that excludes your residence country.

A job is labelled `recommended` from 60 upwards, `borderline` below that, and `rejected` when it is
excluded. Requirements the profile does not verify do not cost points: they are listed as
uncertainties that need a manual review, so a job can still be recommended while containing
requirements the profile could not confirm. The evaluator is a deterministic, rule-based scoring
system rather than a machine-learning model, and a high score is a match against your configured
rules, not a hiring probability.

[Understanding job evaluations](USER_MANUAL.md#4-understanding-job-evaluations) explains every rule,
the configurable `evaluation` weights and the limitations in full.

## Usage - CLI

| Command | Purpose |
| --- | --- |
| `job-agent validate` | check the profile and search configuration |
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

It binds to `127.0.0.1` by default, has no authentication and rejects cross-origin form posts as
CSRF hardening rather than access control, so keep it local. Widen the binding with `--host` only if
you understand that your local data becomes reachable on that network.

## Data, privacy and limitations

- Your local state stays in the checkout: `data/job_agent.sqlite3` for jobs, decisions,
  applications, CV metadata and audit events, and `output/` for generated CV drafts. Both are
  ignored by Git. CV drafts are rendered locally with `pdflatex`; a LaTeX distribution that installs
  missing packages may contact a package repository on its own, and that traffic carries no
  candidate data.
- Searches through the four configured sources send the public query text, an optional location
  filter, your Adzuna credentials and the static public key the Bundesagentur adapter uses. The
  requests also carry a generic `User-Agent`, and the services you query see ordinary network
  metadata such as your IP address. No request contains your profile, CV content or database
  records.
- No credentials are stored in the database and application submission is always blocked.
- Fit scores describe how well a listing matches your profile and preferences. They are not a
  hiring probability, and nothing here is legal advice.
- Deployment, decisions and applications remain yours: review every draft before sending it.

## Testing

```bash
python -m pip install -e .[test]
python -m unittest discover -s tests
```

GitHub Actions runs the same suite on Python 3.11 and 3.12. The tests use synthetic fixtures and
temporary databases, so they need no personal data, credentials or network access.
[DEVELOPMENT.md](DEVELOPMENT.md) describes the test strategy, including which tests need a working
`pdflatex` and why a local Windows run can differ from CI.

## Project documents

- [USER_MANUAL.md](USER_MANUAL.md) - the complete user guide: Windows installation, first-time
  configuration, dashboard and CLI usage, how jobs are scored, and troubleshooting.
- [DEVELOPMENT.md](DEVELOPMENT.md) - architecture, module responsibilities, design decisions and
  development conventions.

## Status

An MVP, deliberately small: one evaluator, four public sources, exact URL/job-ID duplicate
prevention, no browser automation and no automatic applications. It is available under the MIT
license; see `LICENSE`.
