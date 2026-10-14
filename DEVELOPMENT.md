# Development notes

This file describes the implemented system: how the modules fit together, what is persisted, the
search and evaluation policies, the security invariants, and how the project is tested and
documented. It is written for whoever maintains the code; behaviour that users see is documented in
`USER_MANUAL.md`.

Run the suite with `python -m unittest discover -s tests`; the CV tests read generated PDFs with
`pypdf`, so install the test extra first with `python -m pip install -e .[test]`. Three
CV-compilation tests skip when no `pdflatex` executable is on `PATH`; when a LaTeX installation
exists but cannot compile - a MiKTeX installation whose setup never completed, for example - they
fail instead of skipping. Runtime code uses the standard library plus `geonamescache` for offline
city coordinates; there are no other runtime dependencies.

## Module map

```
job_agent/
  cli.py          command line entry point (job-agent ...)
  discovery.py    public-search orchestration and the normalize/evaluate/store pipeline
  profile.py      profile and search-configuration loading and validation
  normalizer.py   conservative mapping of raw listings into the internal Job model
  models.py       the internal Job and Requirement dataclasses
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
  search.py       legacy, inactive DuckDuckGo helper (not wired into discovery)
```

The CLI is the reference interface; the dashboard reuses the same modules rather than duplicating
logic.

## Architecture and responsibilities

`profile.py` validates the editable factual data. `load_profile` requires `identity`, `education`,
`skills`, `languages` and an explicit `professional_experience`, at least one education entry and a
name on every skill. `load_config` requires the list fields `target_roles`, `locations` and
`work_arrangements`, a `search_queries` object with non-empty `primary` and `secondary` lists, and a
`location_preferences` object with a non-empty `origin`, a positive `max_distance_km` and a boolean
`remote_only_beyond_distance`.

`normalizer.py` gives incomplete listings a consistent shape without inventing fields: a title is
mandatory, an unrecognised arrangement becomes `unknown`, seniority falls back to a keyword scan of
the title, and requirement entries may be strings or objects. Missing source values stay unknown.

`models.py` is the internal job representation: `title`, `company`, `location`, `arrangement`,
`description`, `requirements`, `responsibilities`, `qualifications`, `salary`, `employment_type`,
`seniority`, `source`, `source_url`, `external_job_id` and `metadata`. A `Requirement` carries
`text`, a `kind` of `mandatory`, `preferred`, `useful` or `unknown` (default `unknown`) and a
`category` (default `skill`).

`evaluator.py` makes conservative, transparent rule-based assessments (see the policy section
below). `storage.py` owns local SQLite state and audit logging. `cv.py` produces local
LaTeX-generated PDF drafts from profile facts. The public sources live in `adzuna.py`,
`nomado24.py`, `himalayas.py` and `ba.py`; each maps public listings into the existing raw-job
shape. `cli.py` coordinates the workflow and stops the whole run with a clear message if any single
source fails. It also reconfigures standard output and error to UTF-8 with replacement characters,
so emoji, en dashes and non-Latin titles survive being piped or redirected; closes its SQLite
connection when a command finishes; and exits quietly when a reader closes the pipe early.

The dashboard stays thin: `discovery.py` holds the public-search orchestration (query ordering,
per-source de-duplication, optional error tolerance) and the normalize/evaluate/store pipeline, and
both `cli.py` and the dashboard call it, so search behavior is defined once. `dashboard.py` contains
read-only projections (filtering, sorting, aggregates, audit and search history) over rows returned
by `Store`; evaluator-excluded jobs and user-rejected jobs are hidden unless a filter asks for them.
`webui.py` renders server-side HTML and escapes every dynamic value. `webapp.py` serves it with the
standard library HTTP server: routes map onto `Store`, `discovery`, `cv.generate` and `dashboard`,
generated PDFs are served from the recorded path, and dashboard-initiated searches run in one
background thread at a time (guarded by a lock) with a JSON status endpoint that the page polls.

Start it with `job-agent dashboard --port 8771` or `python -m job_agent.webapp --port 8771`. It
binds to 127.0.0.1 by default and adds no dependency beyond the standard library.
`tests/test_dashboard.py` covers the read models plus real HTTP requests against a temporary
database and a stub source adapter, so dashboard tests never touch the network or the local
database.

`maintenance.py` re-runs the current evaluator over already-stored jobs and backs
`job-agent re-evaluate`: it rebuilds each `Job` from the stored payload, compares the fresh
evaluation with the stored one, and asks `Store.replace_evaluation` to rewrite only differing rows,
so listing facts, decisions, applications and audit history stay untouched.

## Persistence and the audit trail

`Store` creates five tables on first use: `jobs`, `evaluations`, `applications`, `cv_versions` and
`audit_events`. `jobs` keeps the normalized payload plus `discovered_at`, `last_seen_at`, a `viewed`
flag, a `status` and an optional `rejection_reason`; `source_url` and `external_job_id` are unique,
which is the entire duplicate-prevention mechanism. A listing seen again updates its payload and
`last_seen_at` and keeps its decision, and no fuzzy title or company matching is attempted.
`cv_versions` records the generated path and the source-fact categories it was built from.

Job statuses are `discovered`, `saved`, `rejected_by_user`, `applied`, `interview`, `offer`,
`rejected_by_company` and `withdrawn`; `update_application` accepts only the last five, so a
discovery state can never be written as an application state. Audit events cover the search
lifecycle, discovery and viewing, decisions, application status changes, CV generation,
re-evaluation and recorded approvals; `storage.py` and `cli.py` hold the exact names. Nothing in the
schema stores credentials. Audit events should record only what traceability needs - the event, the
job reference and short details - and avoid unnecessary personal information.

## Evaluation policy

`evaluate` returns one `Evaluation` carrying `score`, `assessment`, `excluded`, `strong_matches`,
`potential_gaps`, `concerns` and `uncertainties`. The assessment is `rejected` when the job is
excluded, `recommended` for a strong match and `borderline` in between; `evaluator.py` defines the
starting score and the exact boundaries.

Only four findings exclude a job outright:

- a senior-level title (senior, lead, principal, staff, head, director) while the profile has no
  professional employment;
- an explicitly mandatory Master's degree when the profile records a Bachelor's;
- a resolved city outside the configured radius, unless the job is explicitly `remote` and
  `remote_only_beyond_distance` is enabled;
- a published country restriction that excludes the profile's country of residence.

The remaining adjustments are all relative and additive, covering role relevance, confirmed and
missing requirements, seniority, location, work arrangement, employment eligibility and the bounded
preferred-language signal. `evaluator.py` holds the exact weights, and `test_regressions.py` pins the
behaviour that matters, such as a missing mandatory requirement costing far more than an optional
one. An unmatched title is recorded as a potential gap.

Confirmed design choices:

- Exclusions are deliberately narrow: only the four mismatches above remove a job, and a missing
  skill lowers the score instead of excluding one.
- Early-career wording (junior, entry, graduate, trainee, intern, associate) is recorded as a match
  but adds no score, so a junior or remote title cannot carry an otherwise irrelevant listing.
- Ambiguity is never resolved in the job's favour: the evaluator and normalizer are written to stay
  conservative, leaving unknown seniority, unresolvable cities, unstated arrangements and
  unprotected requirements as uncertainties, and flagging sponsorship or work-authorization wording
  for review instead of interpreting it.
- `preferred_languages` is a secondary ranking signal only, as the comment in `evaluator.py` states:
  it never excludes a job and cannot outweigh role, seniority, location or eligibility.

## Public sources and search orchestration

`discovery.SOURCE_NAMES` fixes the adapter order used by configured searches: `adzuna`, `nomado24`,
`himalayas`, `ba`. `default_sources` builds them, handing Adzuna the local `.env` and marking
Himalayas as the one adapter that does not accept a location filter. `collect` runs either one
manual query against a single adapter (Adzuna unless `--source` says otherwise) or every configured
query, all `primary` queries before all `secondary` ones, across the selected adapters, and
de-duplicates results by `(source, external_job_id)` within the run.

When Adzuna's credentials are absent, `default_sources` substitutes an `UnavailableSource`
placeholder instead of failing, and `collect` records the skip in `SearchOutcome.skipped`, counts no
query for it and continues with the remaining adapters. A configured search therefore still runs,
and a search restricted to the skipped source finishes with no queries and an explanation rather
than an error. Credentials that are present but rejected are not treated as missing: Adzuna raises
at request time and keeps the existing policy, fatal for a CLI run and one failed source for the
dashboard.

`tolerate_errors` is the one behavioural difference between the two interfaces: the dashboard passes
`True`, so a failing source is reported next to the others in the search status, while the CLI leaves
it `False`, so the first failed source ends the run with a clear message. The CLI behaviour is one of
the limitations listed below.

Source field behaviour, observed against live responses on 2026-09-23 and relied on by the adapters:

- A Himalayas search item publishes `locationRestrictions` (country names, empty for worldwide
  roles) and `timezoneRestrictions`. Those country names are the only structured geographic
  eligibility signal the source offers, and `location.resolve_eligibility` interprets them against
  `employment_eligibility.country_of_residence` from the profile, so an explicitly restricted remote
  job is excluded while worldwide, Europe and Germany listings keep the existing remote handling.
  The payload has no `remote`/`isRemote` field, so the adapter leaves the arrangement unknown, and it
  publishes `minSalary`/`maxSalary`/`companyName`, which the adapter only partly reads.
- A Bundesagentur fuer Arbeit Jobsuche search item exposes the employer application link as
  `externeURL` (capital URL) and the detail payload does not repeat it. Because the API publishes no
  canonical arbeitsagentur.de posting URL, the adapter preserves `externeURL` when present and
  leaves `source_url` unknown otherwise instead of constructing a link.
- Adzuna typically returns description snippets; listings flagged with
  `metadata.description_is_snippet` lose points and carry an explicit uncertainty.

Investigation counts from the same 2026-09-23 pass, kept as historical evidence and not re-verified
since:

- 144 of 152 sampled Himalayas listings published `locationRestrictions`, and 141 of those excluded
  Germany.
- BA exposed `externeURL` on 3 of 10 listings in one query and 27 of 50 in a wider sample.

`search.py` is the earlier general web-search helper (DuckDuckGo HTML scraping with challenge
detection). It is isolated and not wired into `discovery`, and nothing in the search path sends
profile, CV or contact data.

## CV generation

`cv.generate` renders `templates/resume.tex` from profile facts and compiles it with `pdflatex`,
which must be on `PATH`; the tests that exercise the real compiler are skipped when it is absent. It
writes `output/cv_job_ID.tex` and `output/cv_job_ID.pdf` and records the source-fact categories used
in `cv_versions`.

Tailoring is limited to reordering, re-emphasising, shortening and re-wording existing facts, and
the thesis is always included. Skills and projects are selected by matching the job's requirements
against the profile, with up to three bullets per project and job-relevant bullets first. The
generator cannot invent experience, skills, dates or qualifications, and `tests/test_agent.py`
checks that it does not.

## Security and privacy invariants

- Candidate data stays local: the SQLite database, generated CVs and archives live in the checkout
  and are git-ignored. Outbound requests carry the public query text, the location filter on the
  adapters that accept one, the two Adzuna credentials, and static headers (`User-Agent`, `Accept`
  and the public Bundesagentur key `X-API-Key: jobboerse-jobsuche`). Configured searches reach only
  `api.adzuna.com`, `api.nomado24.de`, `himalayas.app` and `rest.arbeitsagentur.de`; `search.py`
  holds a dormant DuckDuckGo helper that the application flow never calls. No profile, CV, contact
  detail or local record is ever transmitted.
- Personal files (`data/profile.json`, `data/search_config.json`, `MASTER_PROFILE.md`,
  `SOURCE_CV.pdf`, `.env`, `*.sqlite3`, `output/`, `archive/`) are untracked by design, and no
  candidate or credential file has ever been committed to this repository.
- `permissions.require_external_approval` refuses `submit_application` before it looks at the
  approval flag, and otherwise requires an explicit per-action approval. `job-agent permission-check`
  records an approval as a local audit event only - nothing reads it back and nothing is transmitted
  - and no code path can submit an application or contact an employer.
- The dashboard has no authentication. It binds to localhost by default, and `webapp.py` rejects
  POST requests whose `Origin` header is present and does not match the `Host`; a request without an
  `Origin` header is unaffected. That is CSRF-style hardening for browser form posts, not access
  control, so binding it to another interface would require adding authentication first.
- No credentials are stored in the database; the Adzuna adapter reads its keys from the environment
  or the local `.env` file.

## Testing strategy

`python -m unittest discover -s tests` runs the suite, and `pip install -e .[test]` adds `pypdf` for
the CV tests. GitHub Actions runs the same command on Python 3.11 and 3.12.

The suite uses synthetic fixtures (`tests/support.py`) and temporary directories only: no test reads
a real profile, search configuration, source CV or database, and no test needs credentials or
network access. Source adapters are exercised through stub responses, and `tests/test_examples.py`
keeps the shipped `data/*.example.json` files loadable, which is what guards the placeholders users
copy.

Read the test modules for the exact cases. By concern, they cover evaluation and location rules
(`test_regressions.py`, `test_location.py`, `test_debugging.py`), persistence, CV truthfulness and
maintenance (`test_agent.py`, `test_maintenance.py`), the CLI including UTF-8 output and closed-pipe
handling (`test_cli_search.py`, `test_cli_output.py`), the dashboard read models and HTTP routes
(`test_dashboard.py`), the source adapters (`test_sources.py`, `test_adzuna.py`) and the shipped
examples (`test_examples.py`).

Two environment caveats matter when reading results. The three CV-compilation tests skip when no
`pdflatex` executable is on `PATH`, but a LaTeX installation that is present and cannot compile makes
them fail rather than skip. `test_reader_closing_the_pipe_early_exits_quietly` in `test_cli_output.py`
expects empty standard error when the reading end of a pipe closes early; on Windows that write
surfaces as `[Errno 22] Invalid argument`, the CLI prints argparse usage to standard error, and the
test fails, so a suite run on that platform is not fully green. Neither caveat appears on the Linux
CI runner.

Live checks against the real sources are manual and limited to one query per adapter; no automated
test contacts a source.

## Known limitations and next steps

- A failed source ends a CLI search run; only the dashboard tolerates per-source errors. A source
  with no credentials is skipped instead of failing.
- Requirement extraction is narrow: requirements come from listing data, or from the profile's own
  skill names found in the listing text when a source provides none, marked mandatory only when
  wording such as "required" or "must have" appears just before the term. Richer extraction from
  full descriptions is not implemented.
- Language requirements are not scored; profile languages are used in CV drafts only.
- Salary is stored when a source publishes it but is not scored, and there is no salary filter.
  `locations` and `work_arrangements` are validated but unused for scoring, while the example
  configuration documents `maximum_commute_note` as informational only.
- `profile.degree_level` is not used anywhere: the Master's check reads the requirement text.
- Himalayas salary fields are published but unread, and the BA API offers no canonical posting URL,
  so some listings keep an unknown `source_url`; the BA adapter fetches five listings per query.
- The built-in fallback coordinate dictionary covers only a few cities; for other cities
  `geonamescache` is reloaded per job, which slows searches and `job-agent re-evaluate`.
- The dashboard history page shows the 200 newest audit events, and search progress uses polling.
- There are no CLI helpers for creating or editing the JSON profile and configuration by hand.
- Test gaps include malformed responses for the Nomado24, Himalayas and BA adapters; the `ingest`
  command; and CLI-level coverage of `reject` and the blocked `permission-check`.

## Documentation conventions

Three documents describe the project, each with one job: `README.md` is the landing page,
`USER_MANUAL.md` documents behaviour users can see, and this file documents the implementation.
Behavioural detail belongs in the manual, implementation detail here, and the README stays short and
links to both.
