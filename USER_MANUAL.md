# Job Searching Agent user manual

This is a local-first Python CLI for discovering public job listings, comparing them against a local factual profile, tracking choices, and creating local LaTeX-generated PDF CV drafts. The agent helps organize and evaluate opportunities; it never submits an application, contacts employers, sends a CV, or stores passwords. Unknown job information remains unknown rather than being silently guessed.

## Install and setup

Use Python 3.11 or later. From this directory, run `python -m pip install -e .`, then `job-agent validate`; alternatively, run commands directly as `python -m job_agent.cli validate`.

Two local files describe you and your search. Both are ignored by Git, so a fresh clone contains only the tracked examples:

- `data/profile.json` - your factual profile (identity, contact, education, skills, projects, thesis, languages, certifications, employment eligibility). Create it by copying `data/profile.example.json` and replacing the placeholders with your own facts.
- `data/search_config.json` - your preferences (target roles, locations, work arrangements, commute radius, search queries and the secondary `preferred_languages` ranking preference). Create it by copying `data/search_config.example.json`.

Do not put desired roles or preferences in the profile.

CV drafts are generated from `data/profile.json` together with the built-in LaTeX template in `templates/resume.tex`; no separate master CV file is needed or configured. If you also keep longer notes or a copy of a CV in your checkout, they are local only: `SOURCE_CV.pdf` and `MASTER_PROFILE.md` are ignored by Git, so a fresh clone never contains them. The canonical factual source used by the application is always `data/profile.json`. If one of your local documents and the structured profile disagree, correct the source deliberately; this MVP does not silently resolve conflicts.

## Web dashboard

The same local data is also available as a browser dashboard, and the CLI keeps working exactly as before. Start it with `job-agent dashboard` and open http://127.0.0.1:8770/. The `dashboard` subcommand takes only `--host` and `--port`; the global options `--profile`, `--config` and `--database` belong to the `job-agent` command and must be given before the subcommand, for example `job-agent --database data/job_agent.sqlite3 dashboard --port 8771`. The default binding is localhost only. Running the module directly, `python -m job_agent.webapp`, accepts the same options plus `--profile`, `--config`, `--database`, `--output` and `--quiet`.

The dashboard is a second interface rather than a second application: it reads and writes `data/job_agent.sqlite3` through the same storage layer, normalizes and evaluates listings with the same evaluator, and creates CV drafts with the same LaTeX pipeline. Decisions taken there are visible to the CLI immediately, and the other way round. The CLI remains the reference interface.

- Overview: counts by fit band and status, newest discoveries, the saved shortlist, tracked applications and a source summary.
- Jobs: the full local job list with text search, source, status, fit band, arrangement, minimum score, sorting (score, discovery date, title, company, source, status) and paging. Jobs the evaluator excluded and jobs you rejected are hidden by default; set the matching filter to show to inspect them. They stay stored either way, so history and auditing are unaffected.
- Job detail: listing facts including a link to the original posting, the complete fit evaluation (score, strong matches, potential gaps, important concerns, uncertainties), extracted requirements, description text, per-job history and the available actions: save, reject with an optional reason, generate a tailored CV, and record an application status.
- Saved: the shortlist with inline save and reject buttons.
- Applications: every tracked application with status, application date and notes, plus a form to record or change a status.
- Search: run a single public query against a chosen source, or use Run configured search, which runs every configured primary and secondary query across all four sources, exactly like `job-agent search` without a query. Both run in a background thread with live progress and per-source errors. Only the public query text and an optional location filter are transmitted.
- History: logged searches and the local audit trail.
- Sources: per-source job counts, average score, fit distribution, saved and applied counts, newest listing and top titles, plus the configured queries and location preferences.

The dashboard does not submit applications, contact employers or transmit profile, CV and contact data. It refuses cross-origin form submissions, binds to localhost by default, and has no authentication, so treat it like any other local development tool. The `permission-check` command and its block on `submit_application` are unchanged.

## Discovering jobs

For a normal configured search, run `job-agent search`. The command searches every query in `data/search_config.json` once, running the `primary` queries before the `secondary` queries. Each configured query is sent through the public Adzuna, Nomado24, Himalayas, and Bundesagentur für Arbeit (BA Jobsuche) adapters; results are combined and passed through the same normalization, fit evaluation, and local SQLite storage pipeline as imported jobs. To restrict the run to one adapter, add `--source adzuna`, `--source nomado24`, `--source himalayas`, or `--source ba`. A job returned more than once by the same source is processed once when its source and external identifier match; there is no fuzzy title or company matching. Normalized jobs retain their source provenance (`adzuna`, `nomado24`, `himalayas`, or `ba`) for diagnostics and deduplication.

For a specific manual search, use `job-agent search --query "Data Engineer"` or the backward-compatible positional form `job-agent search "Data Engineer"`. A supplied manual query bypasses all configured searches and performs exactly one Adzuna request by default. Add `--source` to run that query against one specific source instead, for example `job-agent search --query "Data Engineer" --source ba`. Add a location filter with `--location Berlin` where supported. Searches send only the public query/location plus locally loaded Adzuna credentials where required; they send no profile, CV, or contact information. Public source adapters may provide different levels of detail: Adzuna commonly returns snippets, while BA may request a small number of details after search results. Review listings before treating them as complete job descriptions.

The configured search families are intentionally separate from suitability scoring. Edit `search_queries.primary` and `search_queries.secondary` in `data/search_config.json` to adjust the normal search scope. Both fields must contain non-empty text queries. The ordering affects request order only; a secondary result is not scored lower than a primary result.

After processing a search, the command prints a summary showing the number of queries actually executed, unique jobs processed, newly stored jobs, previously known jobs, and evaluator-excluded jobs. `No jobs found.` is still printed when the combined search returns no jobs.

Location suitability uses the configurable `location_preferences` object: `origin`, `max_distance_km`, and `remote_only_beyond_distance`. Resolved city locations within the radius remain eligible; resolved locations outside it are excluded unless the job already has the explicit `remote` arrangement and the remote exception is enabled. Unknown or vague locations remain uncertain rather than being assumed nearby or remote. City coordinates are resolved locally with the offline `geonamescache` dataset; the radius is only an approximate geographic proxy for the commute preference, not a train-time calculation.

For reliable, detailed ingestion, create a JSON array and run `job-agent ingest jobs.json`. Each item needs `title`; it may contain `company`, `location`, `arrangement` (`remote`, `hybrid`, `onsite`, or `unknown`), `description`, `source`, `source_url`, `external_job_id`, and `requirements`. Requirements are objects such as `{"text":"Python","kind":"mandatory"}`. Missing information stays unknown. Imported jobs enter the same normalization, evaluation, deduplication, and storage workflow as search results.

## Reviewing jobs and decisions

Run `job-agent list`, `job-agent view JOB_ID`, `job-agent save JOB_ID`, or `job-agent reject JOB_ID --reason "too far"`. Use `job-agent history` to see local audit events. Exact source URLs or exact external job IDs prevent a listing from being stored repeatedly; no fuzzy duplicate detection is performed.

Fit scores show match to known profile facts and current preferences, not hiring likelihood. Each detail view separates confirmed matches, potential gaps, important concerns, and uncertainties. Senior roles and an explicitly required Master's degree are normally excluded. Project/thesis evidence is never reported as professional employment. Sponsorship or authorization wording is marked for verification rather than interpreted legally.

Role relevance is scored separately from early-career compatibility: configured primary target roles receive the strongest title signal, configured secondary consulting queries receive a smaller relevance signal, and junior/entry/graduate/trainee/intern/associate wording no longer provides a large standalone score bonus. An unrelated junior or remote title can remain borderline or uncertain, but is not recommended solely because of its seniority or work arrangement.

The languages listed under `preferred_languages` in `data/search_config.json` (Python by default) act as a small secondary ranking preference, never as a requirement: a job is never excluded or rejected for lacking Python, and the bonus is far smaller than role, seniority, location, employment-eligibility or core requirement effects. Explicit mentions weigh more than incidental ones - a Python entry in the listed requirements is worth more than a mention in the qualification text, which in turn is worth more than a passing mention in the description.

## Refreshing stored evaluations

If the evaluator rules or the profile change, run `job-agent re-evaluate` to bring the evaluations of jobs already in the database up to date. It performs no search, does not touch the stored listing data, and never changes saved, rejected or application states; it only rewrites evaluations that differ from what the current evaluator produces, and prints how many jobs were examined, updated, newly excluded and how those changes split across sources. The command is idempotent, so running it again directly afterwards reports zero updates.

## CV drafts and applications

After ingesting a job, run `job-agent tailor JOB_ID`. This creates `output/cv_job_JOB_ID.pdf` and the exact source `output/cv_job_JOB_ID.tex` locally, and records its source categories. The thesis is always included, while other projects and skills are tailored to the job when possible. It selects and orders only profile facts; it cannot add skills or professional experience. Review and edit the factual sources before using a draft.

The user applies manually. Track manual progress with `job-agent application JOB_ID applied --date 2026-09-15 --notes "Submitted manually"`, then use `job-agent applications`. Valid tracked states are `applied`, `interview`, `offer`, `rejected_by_company`, and `withdrawn`.

## Storage, privacy, and troubleshooting

The default SQLite database is `data/job_agent.sqlite3`. It contains public job records, decisions, application notes, local CV-version metadata, and audit records. It intentionally contains no passwords and no facility for external personal-data transmission. `job-agent permission-check ACTION DESTINATION DATA --approve` can record a one-time, named approval locally for a future integration, but does not transmit data itself; it always blocks `submit_application`. Delete or move the database yourself if you want a fresh history.

If `validate` fails, correct the reported JSON field. If an Adzuna search fails, check that `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are available in the local `.env` file or environment, then use `ingest` with saved public job data. The search source does not follow Adzuna redirect URLs. Run tests with `python -m pip install -e .[test]` once, then `python -m unittest discover -s tests`; CV tests are skipped when `pdflatex` is missing. Command output is UTF-8 whenever it is piped or redirected, so listings containing emoji, en dashes, or non-Latin titles stay readable.


