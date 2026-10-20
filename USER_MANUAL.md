# Job Searching Agent user manual

This is a local-first Python CLI for discovering public job listings, comparing them against a local
factual profile, tracking choices, and creating local LaTeX-generated PDF CV drafts. The agent helps
organize and evaluate opportunities; it never submits an application, contacts employers, sends a
CV, or stores passwords. Unknown job information remains unknown rather than being silently guessed.

This manual covers installation, first-time configuration, day-to-day use, the evaluation rules, and
how to fix common problems.

Contents:

1. [Getting started](#1-getting-started)
2. [First run](#2-first-run)
3. [Using the application](#3-using-the-application)
4. [Understanding job evaluations](#4-understanding-job-evaluations)
5. [Configuration and data](#5-configuration-and-data)
6. [Troubleshooting](#6-troubleshooting)

## 1. Getting started

### Prerequisites and dependencies

| Software | Required? | Why you need it |
| --- | --- | --- |
| Python 3.11 or newer | Required | Runs the whole application (`requires-python = ">=3.11"`). Check it with `python --version`. |
| pip | Required | Installs the project and its dependencies. It ships with Python; always call it as `python -m pip`. |
| Git | Optional | Only to download the project. You can also download the repository as a ZIP file instead. |
| A LaTeX distribution providing `pdflatex` (MiKTeX on Windows) | Optional | Only for CV drafts. Install it from https://miktex.org/ and let its first-run setup finish. |
| Free Adzuna API credentials | Optional | Only for the Adzuna source. The other three sources need no credentials. |

If `python --version` opens the Microsoft Store or prints nothing, install Python from
https://www.python.org/downloads/windows/ and tick **"Add python.exe to PATH"** during setup, then
close and reopen the terminal. On a machine with several Python versions, `py -3.12 --version` is an
alternative way to check.

### Python Dependencies

The project uses a few additional Python packages. You don't need to install them individually; the installation command in this guide takes care of the required packages.

**Packages needed to run the application**

| Package | What it does |
|---|---|
| `geonamescache` (version 2.0 or newer) | Provides offline city and country data. The application uses this information to interpret job locations and calculate distances without contacting an external location service. |

This is the only additional Python package the application needs to run.

**Packages used for testing and installation**

| Package | When it is needed |
|---|---|
| `pypdf` (version 5.0 or newer) | Used by automated tests to read and check generated PDF files. You only need it if you want to run the tests. |
| `setuptools` (version 68 or newer) | Helps pip install the project. You don't need to use it directly. |

**Which installation command should you use?**

If you only want to use the application, install it with:

```powershell
python -m pip install -e .
```

If you also want to run the automated tests, install the project with its test dependencies instead:

```powershell
python -m pip install -e .[test]
```

The second command includes the packages needed for testing, in addition to the normal application dependencies.

**One more thing:** Generating CV PDFs requires a working LaTeX installation, such as MiKTeX. LaTeX is a separate program, not a Python package, so installing the Python dependencies alone is not enough for PDF generation.

### Windows installation and virtual environment

The commands below are PowerShell commands; the older Command Prompt works too (only the activation
command differs). Everything happens inside one folder - the project folder.

**1. Get the project.**

```powershell
git clone https://github.com/AndyMR24/job-tracker-project.git
```

Without Git, open https://github.com/AndyMR24/job-tracker-project in a browser, choose **Code ->
Download ZIP**, and unzip it somewhere convenient such as `C:\Users\<you>\Documents\`.

**2. Open a terminal in the project folder.**

```powershell
cd C:\Users\<you>\Documents\job-tracker-project
```

`Get-ChildItem pyproject.toml` should list that file. If PowerShell reports that the path does not
exist, adjust the folder path.

**3. Create a virtual environment.** A virtual environment is a private copy of Python for this
project. It keeps the project's packages away from the rest of your computer.

```powershell
python -m venv .venv
```

This takes a few seconds and produces no output.

**4. Activate it.** Your prompt then starts with `(.venv)`.

```powershell
.venv\Scripts\Activate.ps1
```

```text
(.venv) PS C:\Users\<you>\Documents\job-tracker-project>
```

If PowerShell refuses to run the script ("running scripts is disabled on this system"), allow it for
this window only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

In the Command Prompt, activate with `.venv\Scripts\activate.bat`.

**5. Install the project.**

```powershell
python -m pip install -e .
```

The `-e` means "editable": the installed tool always uses the files in this folder. Expected output
ends with something like:

```text
Successfully installed geonamescache-3.0.2 job-searching-agent-0.1.0 ...
```

`geonamescache` is the declared runtime dependency; pip installs it automatically. This step needs an
internet connection the first time and does not install LaTeX or any other external program. To run
the automated tests as well, install the test extra once with `python -m pip install -e .[test]` and
run `python -m unittest discover -s tests`.

### Initial configuration

Two local files describe you and your search. Both are ignored by Git, so a fresh download contains
only the tracked examples:

| File | What it is |
| --- | --- |
| `data/profile.example.json` / `data/profile.json` | Example template / your own factual profile (identity, contact, education, skills, projects, thesis, languages, certifications, employment eligibility). |
| `data/search_config.example.json` / `data/search_config.json` | Example template / your own preferences (target roles, locations and commute radius, search queries, preferred languages, optional evaluation weights). |

Create your personal copies without overwriting anything you already have:

```powershell
if (-not (Test-Path data\profile.json)) { Copy-Item data\profile.example.json data\profile.json } else { Write-Host "data\profile.json already exists - kept as is" }
if (-not (Test-Path data\search_config.json)) { Copy-Item data\search_config.example.json data\search_config.json } else { Write-Host "data\search_config.json already exists - kept as is" }
```

In the Command Prompt, `copy data\profile.example.json data\profile.json` asks before overwriting an
existing file, so you can answer "No" to keep your version.

In `data/profile.json`:

- **identity** and **contact** - your name, city, phone and e-mail as you want them on your CV.
- **education**, **skills**, **projects**, **thesis**, **languages**, **certifications** - only facts
  you can support. Replace every placeholder. Give each education entry a `level` of `bachelor`,
  `master`, `phd` or `doctorate`: the highest of those is compared with a job's degree requirement,
  and any other value (for example `additional education`) counts as no recognized degree.
- **professional_experience** - `true` if you have paid professional experience, `false` if you do
  not; `null`, or leaving the key out, means "not recorded" and the evaluator treats it as unknown
  rather than assuming either answer.
- **employment_eligibility** - keep the wording that is true for you; the tool never interprets
  authorization wording as legal advice.
- Do not put desired roles or preferences in the profile: they belong in the search configuration.

In `data/search_config.json`:

- **target_roles** - your strongest target titles; a matching job title earns the strongest
  relevance signal.
- **search_queries.primary** and **search_queries.secondary** - what is searched and in which order;
  see [Adding and removing search queries](#adding-and-removing-search-queries).
- **location_preferences** - `origin` (your city, spelled so the offline dataset can find it),
  `max_distance_km`, and `remote_only_beyond_distance`.
- **locations** and **work_arrangements** - your preferences, validated but not used in scoring yet.
- **preferred_languages** - a small secondary ranking signal, never a requirement.
- **evaluation** (optional) - overrides the scoring weights; see
  [Scoring weights, worked examples and limitations](#scoring-weights-worked-examples-and-limitations).

The local configuration in this working copy currently uses **Aachen** as the origin and **100 km**
as the maximum geographic distance. The public example remains a generic template, so its example
values are not your active preferences.

CV drafts are generated from `data/profile.json` together with the built-in LaTeX template in
`templates/resume.tex`; no separate master CV file is needed or configured. If you also keep longer
notes or a copy of a CV in your checkout, they are local only: `SOURCE_CV.pdf` and
`MASTER_PROFILE.md` are ignored by Git, so a fresh clone never contains them. The canonical factual
source used by the application is always `data/profile.json`. If one of your local documents and the
structured profile disagree, correct the source deliberately; this MVP does not silently resolve
conflicts.

Validate both files as described in [First run](#2-first-run) before searching.

### API credentials and optional dependencies

Three of the four sources - Nomado24, Himalayas and the German Federal Employment Agency job board
("BA Jobsuche") - work with no credentials at all. Only Adzuna needs a free application ID and key,
which you request from Adzuna's developer portal at https://developer.adzuna.com/ .

Store them in a `.env` file in the project root (next to `pyproject.toml`):

```text
ADZUNA_APP_ID=your-adzuna-app-id
ADZUNA_APP_KEY=your-adzuna-app-key
```

The two variable names must match exactly, and `.env` is ignored by Git, so the file stays on your
computer. Never paste real credentials into example files, documentation or a chat. If the
credentials are missing, a search skips Adzuna and reports the skip while the other sources still
run; credentials that Adzuna rejects are reported as a request failure for that source. See
[Missing API credentials](#missing-api-credentials).

Optional extras are never installed by pip:

- **LaTeX / `pdflatex`** (MiKTeX on Windows) is needed only for CV PDFs; everything else works
  without it.
- **`pypdf`**, installed with `python -m pip install -e .[test]`, is needed only to run the tests.

## 2. First run

### Validate the configuration

```powershell
job-agent validate
```

`Profile and configuration are valid.` means both files are readable and complete; the command does
not check API credentials. If it reports a missing or malformed field instead, fix that field in the
named file and run the command again. You can also run the tool without the console script, for
example `python -m job_agent.cli validate`.

### Start the dashboard

```powershell
job-agent dashboard
```

Expected output:

```text
Job dashboard running at http://127.0.0.1:8770/
Database: C:\Users\<you>\Documents\job-tracker-project\data\job_agent.sqlite3
Press Ctrl+C to stop.
```

Open http://127.0.0.1:8770/ in a browser. You should see the "Job Agent" overview page with empty
counts, and the footer shows which database file is in use. The dashboard is served on your own
computer only; leave the terminal open while you use it. Running the module directly,
`python -m job_agent.webapp`, accepts the same options plus `--profile`, `--config`, `--database`,
`--output` and `--quiet`.

To stop the dashboard, press **Ctrl+C** in that terminal (`Dashboard stopped.`), then leave the
virtual environment with:

```powershell
deactivate
```

The `(.venv)` prefix disappears and you can close the terminal. To use the tool again later, open a
terminal in the project folder, activate the environment again, and start the dashboard or any
`job-agent` command.

### Run the first search

```powershell
job-agent search
```

This runs every configured query from `data/search_config.json` once, through all four public
sources, and stores what it finds. Each configured query is sent to every selected source before the
next query starts, which is why long query lists take noticeably longer; see
[Adding and removing search queries](#adding-and-removing-search-queries) and
[Search workload and source behaviour](#search-workload-and-source-behaviour).

Afterwards the command prints a summary showing how many queries ran, how many unique jobs were
processed, how many were newly stored, how many were already known, and how many the evaluator
excluded. `No jobs found.` is printed when the combined search returns nothing. For a single ad-hoc
query, use `job-agent search --query "Data Analyst" --source ba` (or the positional form
`job-agent search "Data Analyst"`); a manual query skips the configured list. See
[CLI usage and commands](#cli-usage-and-commands) for every command.

### Where your data is stored

Everything lives inside the project folder, and none of it is committed to Git: your profile in
`data\profile.json`, your preferences in `data\search_config.json`, optional credentials in `.env`,
the local database in `data\job_agent.sqlite3`, generated CV drafts in `output\`, and the virtual
environment in `.venv\`. The full table and the privacy implications are in
[Configuration and data](#5-configuration-and-data).

## 3. Using the application

The dashboard is a second interface rather than a second application: it reads and writes the same
SQLite database through the same storage layer, normalizes and evaluates listings with the same
evaluator, and creates CV drafts with the same LaTeX pipeline. Decisions taken there are visible to
the CLI immediately, and the other way round. The CLI remains the reference interface.

### Dashboard overview

- **Overview** - counts by fit band and status, newest discoveries, the saved shortlist, tracked
  applications and a source summary.
- **Jobs** - the local job list with text search, source, status, fit band, arrangement, minimum
  score, sorting, a per-page selector and paging. Jobs with a tracked application are hidden by
  default; set the "Tracked applications" filter to "show" to inspect them.
- **Saved** - the shortlist based on the job's saved decision state, including saved jobs that also
  have an application record, with inline remove-from-shortlist and reject buttons.
- **Applications** - every tracked application regardless of the job's current decision status,
  with application status, application date and notes.
- **Search** - run one ad-hoc query against one or more selected sources, or run the full configured
  search, with live progress. Quick search defaults to Adzuna; configured search defaults to all
  sources. An empty source selection is rejected.
- **History** - logged searches and the local audit trail.
- **Sources** - per-source job counts, average score, fit distribution, saved and applied counts,
  newest listing and top titles, plus the configured queries and location preferences.

### Browsing, filtering, sorting and pagination

The Jobs page offers text search plus filters for source, status, fit band, arrangement and a minimum
score, and can sort by score, discovery date, title, company, source or status. Jobs the evaluator
excluded, jobs you rejected and jobs with a tracked application are hidden by default; set the
matching filter to "show" to inspect them. Filter choices are kept when you change page or sort
order. They stay stored either way, so history and auditing are unaffected. Long lists are paged.

The source filter is a compact **Sources** picker; open it to see the known sources as checkboxes.
All sources are selected initially. Select one or more sources to show jobs from any of them, or use
the "select all" and "clear" links. If you clear every source and apply the filter, no jobs are
shown; an empty selection is not treated as "all sources". The source selection is kept with the
other filters when you change page or sort order.

The **Per page** selector offers 10, 25, 50 and 100 jobs, with 25 as the default. The selected size
is kept when you change page, sort order or other filters.

The Status filter reads two separate records. `discovered`, `saved` and `rejected_by_user` come from
the job record. `applied`, `interview`, `offer`, `rejected_by_company` and `withdrawn` come from the
tracked application record, so an application remains findable even if a later Save or Reject action
changes the job's own status. Selecting any of these recognized statuses is an explicit query: it
overrides the three default hides above, while the other filters still apply. The "Tracked
applications" hide/show control applies to the default Jobs view when no status is selected.

### Job details and evaluation history

The job detail page shows the listing facts (including a link to the original posting), the complete
fit evaluation (score, strong matches, potential gaps, important concerns, uncertainties), the
extracted requirements, description text, the per-job history, and the actions: save to or remove
from the shortlist, reject with an optional reason, generate a tailored CV, and record an application
status. The requirements table shows each requirement, how firmly the listing states it (Stated as:
mandatory, preferred, useful or unknown, taken from the listing rather than from your profile) and
the recorded requirement area.

Dates and times are shown as `DD-MM-YYYY, HH:MM` (for example `15-10-2026, 14:02`). They are the
values stored in the local database, which the application records in UTC, and are displayed without
any timezone conversion.

### Saving and rejecting jobs

Use the buttons on the job detail page or the inline actions on the Saved page, or the CLI equivalents
`job-agent save JOB_ID` and `job-agent reject JOB_ID --reason "too far"`. Rejected jobs remain in the
database and in the audit history. "Save to shortlist" records a shortlist decision only; it does not
mean that you applied. A saved job shows **Remove from shortlist** instead of Save. Removing it never
deletes the job, application records, CV drafts, or audit history: it restores the existing
application status when one is tracked, or returns the job to `discovered`. The valid application
states are described in [Application tracking](#application-tracking). Remove from shortlist is a
dashboard action; the CLI currently exposes `save` and `reject` only.

### Application tracking

The tool records what you did; it never applies for you. Track progress with
`job-agent application JOB_ID applied --date 2026-09-15 --notes "Submitted manually"`, or use the
forms on the Applications page, then review them with `job-agent applications`. Valid tracked states
are `applied`, `interview`, `offer`, `rejected_by_company`, and `withdrawn`; `rejected_by_company`
records the employer's decision and is distinct from your own `reject` decision. Once any of these
states is recorded, the job leaves the default Jobs view but remains available on the Applications
page and under the Jobs page's "Tracked applications" filter. Recording an application also mirrors
that status into the job's current status under the current model, so a job that was on the
shortlist leaves Saved. It remains in Applications regardless of later Save or Reject actions:
Saved is the shortlist decision, while Applications is the tracked application record.

When you record an application with status `applied` and leave the date empty, the local calendar
date is stored. An explicitly supplied date is used as entered, and later status changes without a
date keep the existing application date. Recording an application directly in another status without
a date leaves the date empty.

### Generating job-specific CVs

After ingesting a job, run `job-agent tailor JOB_ID`. This creates `output/cv_job_JOB_ID.pdf` and the
exact source `output/cv_job_JOB_ID.tex` locally, and records its source categories. The thesis is
always included, while other projects and skills are tailored to the job when possible. It selects
and orders only profile facts; it cannot add skills or professional experience. Drafts currently
cover education, projects, skills, languages and certifications: a work-experience section is not
generated yet, even when your profile records professional experience. Review and edit the factual
sources before using a draft.

### CLI usage and commands

The console script is `job-agent`. The global options `--profile`, `--config` and `--database` must
come **before** the subcommand, for example
`job-agent --database data/job_agent.sqlite3 dashboard --port 8771`.

| Command | Purpose |
| --- | --- |
| `job-agent validate` | Check the profile and search configuration. |
| `job-agent search` | Run every configured query against all sources. |
| `job-agent search --query "Data Analyst" --source ba` | Run one query against one source. |
| `job-agent ingest jobs.json` | Import public listings you saved yourself. |
| `job-agent list` | List stored jobs by fit score. |
| `job-agent view JOB_ID` | Show one job with its full evaluation. |
| `job-agent save JOB_ID` / `job-agent reject JOB_ID --reason "too far"` | Record a decision. |
| `job-agent tailor JOB_ID` | Generate a tailored CV draft in `output/`. |
| `job-agent application JOB_ID applied --date 2026-01-01` | Track an application you sent. |
| `job-agent applications` / `job-agent history` | Review applications and the audit trail. |
| `job-agent re-evaluate` | Refresh stored evaluations after changing profile or rules. |
| `job-agent refresh-ba-locations` / `--apply` | Preview or apply location repairs for stored BA jobs using their references. |
| `job-agent permission-check ACTION DESTINATION DATA --approve` | Record a one-time local approval for a future external action; it never transmits data and always refuses the `submit_application` action. |
| `job-agent dashboard` | Serve the local web interface. |

`refresh-ba-locations` is a dry run by default. It fetches only the BA detail records for stored BA
jobs whose locations are missing, reports recovered locations and failures, and writes nothing until
you rerun it with `--apply`. The apply step preserves decisions, viewed state, applications, CV
versions and history, while re-evaluating jobs whose locations changed.

After changing location rules or the radius, first run `job-agent re-evaluate` to apply them to every
stored job. Then run `job-agent refresh-ba-locations` to preview missing BA locations and
`job-agent refresh-ba-locations --apply` if the preview is satisfactory. Each successfully refreshed
BA job is re-evaluated immediately, so a second global `re-evaluate` is not required when the same
profile and configuration remain active. Run `re-evaluate` again only after another rule,
configuration or source-location change.

When `job-agent application ... applied` omits `--date`, today's local date is stored. Explicit and
previously stored application dates are preserved when later updates omit the date.

Use `job-agent history` to see local audit events, and `job-agent list` followed by
`job-agent view JOB_ID` for the CLI equivalent of the dashboard pages. Commands can also be run as
`python -m job_agent.cli <command>`.

## 4. Understanding job evaluations

### Scores and fit categories

Every stored job gets a score between **0 and 100** (values are clamped to that range). It starts at
**50** and then moves up or down according to fixed rules that you can configure. With the default
settings:

| Rule | Effect on the score |
| --- | --- |
| The title matches one of your `target_roles` | +15 |
| The title matches one of your configured secondary queries | +8 |
| A job requirement is a skill your profile lists (mandatory / other) | +8 / +4 |
| Your `preferred_languages` entry appears in the requirements / qualifications / description | +3 / +2 / +1 |
| The job is remote | +6 |
| Hybrid or onsite work resolved inside your radius | +4 |
| A senior-level title while your profile records no professional experience | -45 **and excludes the job** |
| An explicitly required Master's degree while your profile records a lower completed degree | -50 **and excludes the job** |
| A Master's degree mentioned but not required, with a lower completed degree recorded | -10 |
| "N years of experience" wording while your profile records no professional experience | -25 / -8 |
| The source supplied only a description snippet | -5 |
| The listing exposes no explicit requirements | -5 |

The score summarizes how well a listing matches your profile and preferences. It is **not** a
probability of being hired and not a prediction of an interview.

The **fit category** is a label derived from the score and the exclusions: `recommended` from 60
upwards, `borderline` below that, and `rejected` whenever a job is excluded. An **exclusion** is a
separate decision: the job is hidden from the default list but stays stored and can be shown with the
"Excluded jobs" filter. A title that matches neither your target roles nor a configured secondary
query is recorded as a potential gap - it simply earns no role bonus - and the evaluation separates
that from requirements your profile could not verify.

### Primary versus secondary search queries

The two query families control **what is searched and in which order**: `primary` queries run before
`secondary` queries. They never change the score of a result by themselves - a job found through a
secondary query is scored exactly like the same job found through a primary one - so a secondary
query never makes a job less suitable.

What shapes the role-relevance part of the score is the job's **title** compared with the
configuration: a title matching a `target_roles` entry earns the strongest signal (+15 by default),
and a title matching a configured **secondary query** earns a smaller one (+8). Put your strongest
target titles in `search_queries.primary` and broader or less central titles in
`search_queries.secondary`.

### Mandatory, preferred, useful and unknown requirements

A listing can state a requirement with a strength, shown in the "Stated as" column of the
requirements table:

| Stated as | Meaning |
| --- | --- |
| `mandatory` | The posting says it is required. |
| `preferred` | The posting would like it. |
| `useful` | The posting mentions it as a plus. |
| `unknown` | The wording is unclear, or no strength was given. |

The evaluator compares each requirement with your profile:

- **A skill your profile lists** is credited as a confirmed match (+8 mandatory, +4 otherwise).
- **A skill your profile does not list** is treated as **unknown**, not as a gap: the job does not
  lose points, and the requirement appears under "Uncertainties" as "could not be verified from the
  profile". Your profile is not an exhaustive list of everything you know, so an unlisted skill is
  never counted against you.
- **Degree requirements** are compared with the highest completed degree recorded in your education
  entries (`bachelor`, `master`, `phd`/`doctorate`). A satisfied requirement changes nothing; a known
  lower degree follows the rules above; an unrecognized or missing level is an uncertainty.
- **"N years of experience" requirements** are penalised only when your profile records that you have
  no professional experience. If you do record experience, the duration cannot be verified, so the
  requirement is flagged for review instead of being scored as met or unmet.
- **Sponsorship or work-authorization wording** is always flagged for manual verification; the tool
  draws no legal conclusion.

Project and thesis evidence is never reported as professional employment.

### Uncertainty and exclusion rules

Only four findings exclude a job today:

1. a senior-level title while your profile records that you have **no** professional experience;
2. an explicitly required Master's degree while your profile records a **lower** completed degree;
3. a location resolved **outside** your configured radius, unless the job is explicitly remote and
   `remote_only_beyond_distance` is enabled;
4. a published country restriction that excludes your country of residence.

If your profile does not record a fact, that fact is never used against the job. An unrecognized
degree level, an unrecorded professional-experience status, or a job location that cannot be resolved
all produce an uncertainty instead of a penalty or an exclusion. Location suitability uses
`location_preferences`: resolved locations within the radius stay eligible, resolved locations
outside it follow rule 3, and unknown or vague locations remain uncertain rather than being assumed
nearby or remote. Coordinates are resolved locally with the offline `geonamescache` dataset, and the
radius is only an approximate geographic proxy for the commute preference, not a train-time
calculation. If the configured `origin` itself cannot be resolved, the evaluation says so explicitly,
the radius is not applied, and a hybrid or onsite job receives no within-radius bonus - check the
spelling of `location_preferences.origin` and run `job-agent re-evaluate` afterwards. A job location
that cannot be resolved is reported separately, so the two causes are never confused, and in neither
case is a job excluded on distance.

The resolver understands common structured display forms such as `Berlin, Deutschland`,
`Mitte, Berlin`, `Hamburg-Altstadt, Hamburg`, and `Maxvorstadt, München`. It accepts a city only when
offline locality data identifies it unambiguously; conflicting strings such as `München, Berlin`, as
well as country-only or region-only values, stay unknown. Valid BA source coordinates are preferred
for distance calculation, with the city text used as a fallback. Invalid or incomplete coordinates
are ignored. Unknown locations remain visible as uncertainties under the current policy and are not
treated as nearby.

Because unverified requirements do not reduce the score, a job can be `recommended` while still
listing requirements the profile could not confirm. Review those uncertainties manually before you
decide: a high score does not mean every requirement was checked, and an unverified requirement is
not a confirmed gap.

### Scoring weights, worked examples and limitations

The numbers above are the shipped defaults in `job_agent/evaluator.py`. The optional `evaluation`
block in `data/search_config.json` overrides them (`data/search_config.example.json` lists every key
with its default):

```json
"evaluation": {
  "base_score": 50,
  "recommended_threshold": 60,
  "weights": {
    "target_role": 15,
    "secondary_query": 8,
    "senior_penalty": 45,
    "confirmed_skill": {"mandatory": 8, "other": 4},
    "missing_requirement": {"mandatory": 18, "preferred": 4, "useful": 4},
    "degree_required_penalty": 50,
    "degree_mentioned": 10,
    "experience_requirement": {"mandatory": 25, "preferred": 8},
    "source_snippet": 5,
    "no_requirements": 5,
    "remote": 6,
    "onsite_or_hybrid_within_radius": 4,
    "preferred_language": {"requirement": 3, "qualification": 2, "description": 1}
  }
}
```

- Change one value at a time, save the file, and run `job-agent validate`: a negative number, a
  misspelled key, or a `recommended_threshold` outside 0-100 is rejected with a clear message.
- Changing a weight does not rewrite evaluations that are already stored. Run
  `job-agent re-evaluate` to refresh them, then study the new order in the dashboard. The command
  performs no search, leaves listing data and decisions untouched, only rewrites evaluations that
  differ, and is idempotent - running it twice reports zero updates the second time.
- The penalty values are independent of the exclusions: lowering a penalty, even to zero, does not
  make an excluded job eligible again.
- `weights.missing_requirement` is kept only for backward compatibility. An unlisted requirement is
  treated as unknown, so changing those three numbers has no effect on scores today.
- Weights never change your profile: your facts stay exactly as you recorded them.

A worked example, using the shipped example profile and example configuration with the default
weights:

| Job | Why | Score |
| --- | --- | --- |
| *Junior Data Analyst*, Berlin, hybrid, requirement "Python (mandatory)" | Base 50 + 15 (target role) + 8 (Python is listed in the profile) + 3 (Python also appears in the listed requirements) + 4 (hybrid inside the radius) | **80 - recommended** |
| *Office Manager*, Berlin, onsite, no requirements | Base 50 + 0 (title is not a target role, recorded as a potential gap) + 4 (inside the radius) - 5 (no requirements exposed) | **49 - borderline** |

Add a requirement the profile does not list - for example "Kubernetes (mandatory)" - to the first
job and the score stays **80**, because the requirement is unknown rather than missing. What changes
is the job detail page: it now shows "Mandatory requirement could not be verified from the profile:
Kubernetes." under Uncertainties, so you can check it yourself.

Limitations of the scoring system:

- The evaluator is a deterministic, rule-based scoring system, not a machine-learning model. The
  same inputs always produce the same score, and every point traces back to one of the rules above.
- A higher score means "matches the configured rules more closely". It is not a guarantee of
  suitability, an interview or a job offer.
- Job descriptions are often incomplete, inconsistent or copied from other postings, and some
  sources return only snippets.
- Always inspect the posting itself - description, responsibilities, location and the uncertainties
  the tool lists - before deciding whether to apply.
- Judge the ranking against your real experience with it. If the order feels wrong, adjust the
  weights or your search configuration and re-evaluate; passing tests does not prove that the
  ranking is useful for you.

## 5. Configuration and data

### Editing search preferences

Edit `data/search_config.json` in any text editor, save the file, and run `job-agent validate`. The
fields are described in [Initial configuration](#initial-configuration). `target_roles` decides which
titles earn the strongest relevance signal, `location_preferences` decides the commute radius and the
remote exception, and `preferred_languages` adds a small ranking preference without ever excluding a
job.

### Adding and removing search queries

`search_queries.primary` and `search_queries.secondary` in `data/search_config.json` decide what is
searched. Both fields must contain non-empty text queries, and `primary` runs before `secondary`.
Put your strongest target titles in `primary` and broader or less central titles in `secondary`; a
secondary query broadens discovery and does not make a result less suitable (see
[Primary versus secondary search queries](#primary-versus-secondary-search-queries)).

Adding queries increases the search workload. Every configured query is sent to every selected
source, so the work grows roughly with (number of queries) x (number of sources), and each source
search can then perform extra follow-up requests - the Bundesagentur adapter, for example, fetches
details for the listings it returns - so the total number of HTTP requests can be higher than that
product. Keeping both lists short keeps searches fast and reduces the chance of hitting rate limits;
prefer a few well-chosen queries over near-duplicates, and move marginal titles to `secondary`
rather than adding more primary queries.

### Search workload and source behaviour

- Sources: Adzuna, Nomado24, Himalayas and the German Federal Employment Agency job board ("BA
  Jobsuche"). Adzuna needs credentials; the other three need none.
- Ordering: for a configured search, all `primary` queries run before all `secondary` queries, and
  within one query the sources are queried in a fixed order.
- Limiting a run: `--source adzuna`, `--source nomado24`, `--source himalayas` or `--source ba`
  restricts a search to one source. A manual query (`--query`) bypasses the configured list and
  performs exactly one request, against Adzuna by default or the source given with `--source`.
- Dashboard source selection: Quick search defaults to Adzuna and Full configured search defaults to
  all sources. The Search tab accepts any non-empty selection of the four sources; a cleared
  selection is rejected. This selection is for that search run only and does not rewrite
  `search_config.json`. It is separate from the Jobs tab source filter, which only filters jobs
  already stored.
- Duplicates: a listing returned more than once by the same source is processed once when its source
  and external identifier match; there is no fuzzy title or company matching. Normalized jobs keep
  their source for diagnostics.
- Detail levels differ between sources: Adzuna commonly returns snippets, while BA may request a
  small number of details after the search results. Review listings before treating them as complete
  job descriptions.
- BA links: the app uses an explicit `externeURL` from either the search or detail response. If
  neither supplies one, it promotes only a clearly labelled `Bewerbungsformular` Markdown link from
  the description when that link is `http` or `https`. It does not use generic partner/employer
  domains or arbitrary description links, and it does not construct a BA listing URL. If no direct
  vacancy link exists, the job detail page says so. Descriptions containing arbitrary links are
  otherwise shown as plain text.
- Errors: a CLI search stops with an error if a source fails, while a dashboard search continues
  through the remaining sources and reports the failures per source. Missing Adzuna credentials are
  a skip rather than a failure (see [Missing API credentials](#missing-api-credentials)).
- What is sent: the public query text, an optional location filter and (for Adzuna) your API
  credentials; see [Privacy and local data handling](#privacy-and-local-data-handling) for what never
  leaves your machine.

### Importing listings yourself

For reliable, detailed ingestion, create a JSON array and run `job-agent ingest jobs.json`. Each item
needs `title`; it may contain `company`, `location`, `arrangement` (`remote`, `hybrid`, `onsite` or
`unknown`), `description`, `source`, `source_url`, `external_job_id`, and `requirements`.
Requirements are objects such as `{"text":"Python","kind":"mandatory"}`. Missing information stays
unknown. Imported jobs enter the same normalization, evaluation, deduplication and storage workflow
as search results.

### Profile, database and generated-file locations

Everything the application stores lives inside the project folder, and none of it is committed to
Git (the rules are in `.gitignore`):

| What | Where |
| --- | --- |
| Your profile | `data\profile.json` |
| Your search preferences | `data\search_config.json` |
| Adzuna credentials (optional) | `.env` in the project root |
| Jobs, evaluations, decisions, applications and audit history | `data\job_agent.sqlite3` (created the first time the dashboard or a command stores something) |
| Generated CV drafts | `output\` (`.pdf` and `.tex`) |
| The virtual environment | `.venv\` |

Each installation starts with its own empty `data\job_agent.sqlite3`. If you move to a new folder and
want your previous history, copy that file yourself, or point the tool at it with
`job-agent --database <path to the other file> dashboard`. To start over, delete or move the database
file; everything else keeps working.

### Privacy and local data handling

- The dashboard binds to `127.0.0.1` only, has no password, and rejects cross-origin form
  submissions. Keep it that way: do not pass `--host 0.0.0.0` or forward the port, because anyone who
  can reach the port can read and change your local data.
- Searches send only the public query text, an optional location filter and (for Adzuna) your API
  credentials. Your profile, CV and local records are never uploaded, and no code path transmits
  them.
- The database stores no passwords. `job-agent permission-check ACTION DESTINATION DATA --approve`
  records an approval-related audit event locally for a possible future integration; nothing reads
  those records back, no sender exists today, and the command always refuses `submit_application`.
- The application never submits an application and never contacts an employer. Application tracking
  only records what you did.
- The `.venv` folder and the `.env` file are local to your machine: do not copy them to other
  computers, do not commit them, and never paste credentials into documentation or a chat.

## 6. Troubleshooting

### Installation and Python environment issues

**`python` is not recognised, or opens the Microsoft Store.** Install Python from
https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH"; close and reopen the
terminal afterwards. On a machine with several Python versions, try `py -3.12 --version`.

**PowerShell refuses to activate the environment: "running scripts is disabled on this system".**
Allow it for the current window only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Alternatively use the Command Prompt with `.venv\Scripts\activate.bat`.

**`job-agent` is not recognised after installation.** Check that the prompt starts with `(.venv)`:
the command only exists inside the activated environment. If it still fails, reinstall from the
project folder with `python -m pip install -e .`, or call the module directly, for example
`python -m job_agent.cli validate`.

**`validate` reports a problem.** Correct the reported JSON field in the named file and run
`job-agent validate` again. `job-agent validate` never checks API credentials, so a missing `.env`
file is not a validation error.

### Missing API credentials

Adzuna is the only source that needs credentials (`ADZUNA_APP_ID` and `ADZUNA_APP_KEY`, see
[API credentials and optional dependencies](#api-credentials-and-optional-dependencies)). Without
them, a search skips Adzuna and continues with the other configured sources: the CLI prints
`Adzuna skipped: ADZUNA_APP_ID and ADZUNA_APP_KEY are not set; no Adzuna search was performed.` and
the dashboard shows the same message in its search status and progress log. A search that asks for
Adzuna only performs no search at all and reports the skip instead of an empty result. Credentials
that are present but rejected by Adzuna are not treated as missing: a CLI search stops on that error,
while the dashboard records the failed source and continues with the other three. Everything else
works without Adzuna credentials; to keep searching without them, use `ingest` with saved public job
data. The Adzuna adapter does not follow redirect URLs.

### Dashboard and port issues

**The dashboard will not start because the port is already in use** (for example
`WinError 10048`). Something else is using port 8770 - often a dashboard you started earlier. Close
it, or use another port:

```powershell
job-agent dashboard --port 8771
```

Then open http://127.0.0.1:8771/ . `--port` belongs to the `dashboard` subcommand, while `--profile`,
`--config` and `--database` are options of `job-agent` itself and must come first, for example
`job-agent --database data/job_agent.sqlite3 dashboard --port 8771`. Binding a wider interface is
possible with `--host`, but then anyone on that network can reach your local data, so keep the
default.

**Command output looks garbled when piped or redirected.** The CLI switches its output to UTF-8 when
output is not a terminal, so listings containing emoji, en dashes or non-Latin titles stay readable;
if you see replacement characters, your console's code page is the cause.

### LaTeX and CV-generation issues

**`pdflatex was not found on PATH`.** No LaTeX distribution is installed. Install MiKTeX from
https://miktex.org/ and reopen the terminal. Everything except CV drafts works without LaTeX.

**Compilation fails with a message pointing at `https://miktex.org/howto/install-miktex-win`.** The
distribution is installed but its first-run setup has not finished. Open MiKTeX once, let it complete
its setup, and try the CV draft again.

**The CV draft is missing content.** Drafts contain only profile facts - education, projects, skills,
languages and certifications - and never invent experience. A work-experience section is not
generated yet, even when your profile records professional experience; update `data/profile.json`
first if the factual source is wrong.

### Other problems

If a search returns no results, check the progress log and the source errors in the dashboard, and
confirm that the configured queries and the location preferences match what you expect. The History
page shows the local audit trail, including skipped and failed sources.
