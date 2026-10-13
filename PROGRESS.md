# Progress and TODOs

Last verified: 2026-10-13

## Completed and verified

- [x] Editable profile and separate search configuration validate successfully (`job-agent validate`).
- [x] Editable installation succeeds with `python -m pip install --no-deps -e .` (rechecked 2026-09-23, version 0.1.0) and the installed `job-agent` console script runs.
- [x] Full automated suite passes: 83 tests via `python -m unittest discover -s tests` with the `pypdf` and `geonamescache` dependencies installed. The suite runs on synthetic fixtures only: no test reads a real profile, search configuration, source CV or database.
- [x] Four public sources work live: one manual query per source returned 20 (Adzuna), 20 (Nomado24), 19 (Himalayas) and 5 (BA Jobsuche) listings in a throwaway database.
- [x] Example JSON ingestion works and stores jobs locally.
- [x] Job listing, detail view, fit explanation, save, and audit history work.
- [x] Local browser dashboard serves overview, job browsing with filtering/sorting/paging, job detail with the full evaluation and original-posting link, save/reject, saved jobs, application tracking, search history, source statistics, CV generation and PDF download.
- [x] The dashboard reuses the stored SQLite database, the evaluator, the LaTeX CV pipeline and the shared search orchestration; changes made in the dashboard are immediately visible to the CLI and vice versa.
- [x] Dashboard verification: all pages load, filters and sorting return the expected rows, and the save/reject/apply/CV/search flows were exercised over HTTP against a copy of a populated database, including a real LaTeX CV draft.
- [x] The dashboard job detail page shows the internal database id next to the title (for example `#502`), and the id matches the one printed by `job-agent list` and stored in the `jobs` table.
- [x] Himalayas country restrictions are interpreted from the published `locationRestrictions` list; in a sample of 152 live listings, 144 published restrictions, 141 excluded Germany and were therefore excluded, while worldwide listings and multi-country lists containing Germany kept the existing remote handling.
- [x] BA listings keep the published `externeURL` as the original posting link (3 of 10 in one sampled query, 27 of 50 in a wider sample); listings without it keep an unknown URL instead of a constructed one.
- [x] `job-agent re-evaluate` refreshes stored evaluations in place: it rewrites only the rows whose evaluation changed, without a search and without changing listing facts, statuses, decisions or application records.
- [x] Dependency check: `geonamescache>=2.0` is declared in `pyproject.toml` runtime dependencies, appears in the installed distribution metadata and is resolved by a dry-run reinstall; no change was needed.
- [x] Dashboard default filtering: evaluator-excluded and user-rejected jobs are hidden from the job list and the overview until the Excluded/User rejections filters are explicitly set to show; jobs stay stored and counts stay visible.
- [x] Dashboard configured search: Run configured search uses the same `discovery.collect()` orchestration as `job-agent search`, running all configured primary and secondary queries across all four sources in the existing background thread, next to the retained single-query option.
- [x] Python is a secondary ranking preference from `preferred_languages` in the search configuration: a small additive signal (requirement +3, qualification +2, description +1) that never excludes a job and cannot outweigh role, seniority, location, eligibility or core requirement effects.
- [x] Redirected or piped CLI output no longer aborts on job titles outside the console code page (emoji, en dashes, non-Latin scripts), and closing the reading side of a pipe early exits quietly instead of printing an ignored `BrokenPipeError`.
- [x] The CLI closes its SQLite connection when a command finishes, so the database file is released instead of staying locked.
- [x] Truthful local LaTeX-generated PDF CV generation works when a `pdflatex` executable is available.
- [x] Manual application status tracking and application listing work.
- [x] `permission-check submit_application` is refused with a clear message and no audit write, while an approved non-submission action records a local approval.
- [x] Public search command runs without sending profile or CV data.
- [x] SQLite persistence and exact URL/job-ID duplicate prevention work.
- [x] GitHub repository is linked; only the changes from this verification pass are uncommitted.

## Publication cleanup (2026-10-13)

- [x] Stopped tracking the personal files `MASTER_PROFILE.md`, `SOURCE_CV.pdf`, `data/profile.json`, `data/search_config.json` and `test.sqlite3`; local copies were kept and are now ignored by Git.
- [x] Extended `.gitignore` to cover personal configuration, `*.sqlite3`, generated output, archives, caches, build artefacts and virtual environments.
- [x] Added `data/profile.example.json` and `data/search_config.example.json` as tracked, placeholder-only templates, plus `tests/test_examples.py` to keep them loadable.
- [x] Removed personal data from the test suite: every module now uses `tests/support.py` fixtures and temporary directories.
- [x] Rewrote `README.md` as a project landing page and added a GitHub Actions workflow that installs the package with the test extra and runs the suite.
- [ ] Still open by design: the personal files remain in earlier commits (no history rewrite was performed), no license has been chosen, and the new workflow has not yet been executed on GitHub.
- [ ] Still open: no CI run has been observed on GitHub. A clean-venv installation and the full suite were verified on an isolated snapshot of this release candidate.

## Current limitations / TODOs

- [ ] Make one failing search source non-fatal instead of ending the whole run (specification section 30 allows a single source to fail).
- [ ] Improve public-search result extraction and add fixtures for changing search-result HTML.
- [ ] Add explicit conflict detection between `MASTER_PROFILE.md`, the structured profile, and the master CV.
- [ ] Add CLI setup/edit helpers so users do not need to edit JSON manually.
- [ ] Add richer requirement extraction from full job descriptions while preserving unknown states.
- [ ] Add tests for malformed web responses and incomplete imported job records.
- [ ] Add CLI-level tests for reject/save decisions and for the blocked `submit_application` permission check (storage-level invalid-job-ID tests already exist).
- [ ] Add a rendered CV review step and optional PDF export only after validating truthful content.
- [ ] Add a controlled way to configure source-specific public search providers.
- [ ] Add a release/update workflow and CI test run on GitHub.
- [ ] Decide whether the BA adapter should fetch more than five listings per query.
- [ ] Decide whether the BA adapter should link listings without `externeURL` to a BA search page by reference number; the API publishes no canonical posting URL, so nothing is constructed today.
- [ ] Map the Himalayas salary fields (`minSalary`/`maxSalary`) which the adapter does not read yet, so salary stays unknown for that source.
- [ ] Cache the geonamescache city dataset: `resolve_location` reloads it for every job, which slows `job-agent re-evaluate` and every search.
- [ ] Consider authentication or an access token for the dashboard if it is ever bound beyond localhost (it currently relies on the 127.0.0.1 default plus an Origin check).
- [ ] Replace dashboard search status polling with server-sent events if the polling proves noisy.
- [ ] Add pagination or filtering to the dashboard history page; it currently shows the 200 newest audit events.

## Known manual-test observations

- The original manual referenced `SOURCE_CV.pdf.pdf`; the corrected file name is `SOURCE_CV.pdf`, an optional local master CV that is not tracked in Git. The configuration and manual have been corrected.
- Live availability is verified for a single manual query per source; the full configured multi-query automatic search was not re-run end to end in this pass.
- Dashboard verification used real HTTP requests against a running server plus HTML content assertions rather than a scripted browser.
