# Job Searching Agent — Implementation Specification

## 1. Project Overview

Build a local-first Python application that helps the user find suitable jobs in Germany.

The application should:

1. Search the web for relevant job opportunities.
2. Extract and normalize job information.
3. Compare jobs against the user's profile and preferences.
4. Filter obvious mismatches.
5. Rank suitable jobs.
6. Explain why each job is or is not a good match.
7. Allow the user to save or reject jobs.
8. Maintain a history of discovered jobs and user decisions.
9. Generate truthful, job-specific CV versions for jobs selected by the user.
10. Track application progress.
11. Maintain a local audit/history of important actions.
12. Protect the user's personal information.
13. Never automatically submit job applications.

The user is the final authority over all consequential actions.

The application should be designed as a useful MVP first. Do not over-engineer the system or implement future features prematurely.

---

# 2. Core Principles

The following are non-negotiable requirements.

### 2.1 Never invent user information

The application must never invent, infer, embellish, or fabricate:

- skills
- work experience
- education
- projects
- certifications
- languages
- responsibilities
- achievements
- employment history
- qualifications
- personal details

If information is not present in the user's authoritative profile/CV, it must be treated as unknown.

This is especially important when generating tailored CVs.

A tailored CV may:

- reorder information
- emphasize relevant existing experience
- change wording
- shorten irrelevant sections
- adapt descriptions to the job
- highlight relevant projects or skills

It must not create new facts.

---

### 2.2 Never automatically apply

The application must never submit a job application automatically.

The user applies manually.

The system may:

- analyze a job
- prepare a tailored CV
- prepare supporting material
- create an application checklist
- track application status

But the actual application submission remains entirely under the user's control.

---

### 2.3 Never send personal information externally without explicit approval

User data should remain local by default.

Any action that would transmit personal information to an external service requires explicit user approval immediately before the action.

Examples include:

- uploading a CV
- sending a CV
- sending personal information to a recruiter
- contacting a company
- sending an email containing personal information
- creating an external account using personal information
- submitting application information

Public job information may be retrieved automatically.

The system must clearly distinguish between:

- retrieving public job information
- processing the user's private information locally
- transmitting the user's private information externally

---

### 2.4 No password storage in the MVP

Do not store job-board, company, email, or other external-service passwords.

If browser interaction is implemented in the future, prefer user-authenticated sessions rather than storing credentials.

Browser-based application submission is not part of the MVP.

---

### 2.5 Never silently guess

If an important piece of information is uncertain or ambiguous:

- represent it as unknown/uncertain, or
- ask the user for clarification when necessary.

Do not silently assume the most favorable interpretation.

Jobs with uncertain requirements may still be shown, but the uncertainty must be visible.

---

### 2.6 Keep the MVP simple

Prefer straightforward Python code and understandable architecture.

Avoid:

- unnecessary abstractions
- premature optimization
- excessive design patterns
- complex infrastructure
- unnecessary services
- unnecessary databases
- complicated duplicate-detection systems
- elaborate visa-analysis systems

The architecture should allow future expansion without implementing that expansion now.

---

# 3. User Profile

The application must have a canonical local user profile.

The profile is the authoritative source of machine-readable facts about the user.

It should contain information such as:

- education
- degree
- university
- skills
- programming languages
- tools/technologies
- projects
- thesis
- work experience
- certifications
- languages
- location
- work authorization information
- other explicitly relevant qualifications

Personal facts must not be hardcoded into source code.

The profile must be editable without modifying application source code.

The application should validate the profile when loaded.

---

# 4. Master CV

The user will provide a master CV separately.

The master CV should contain the user's factual career information and serve as the source material for tailored CVs.

The structured profile and master CV must not silently contradict each other.

If they contain conflicting information:

- detect the conflict
- make it visible
- do not silently choose one version

The user must be able to correct the source information.

The master CV should not contain dynamic search preferences such as:

- preferred job titles
- preferred locations
- salary preferences
- search terms
- ranking preferences

Those belong in configuration.

---

# 5. Search Configuration

Search preferences should be configurable separately from the user's factual profile.

Configuration may include:

- preferred job categories
- preferred role titles
- related role/title variants
- location preferences
- remote/hybrid/onsite preference
- maximum preferred commute
- salary preference
- search terms
- other job-search preferences

Do not hardcode these preferences into the application.

---

# 6. Target Job Market

The primary target is Germany.

### Location rules

Germany-wide remote jobs are generally acceptable.

Hybrid and onsite jobs should be evaluated against the user's configured geographic/commute preferences.

The user's approximate target is:

- near the user's own city
- nearby cities count as reachable in the same way
- the commute expectation is configurable, for example a maximum travel time by train

The exact location/commute configuration should remain editable rather than hardcoded.

The system should distinguish between:

- remote
- hybrid
- onsite
- unknown

Unknown location/work-arrangement information should not automatically cause rejection.

---

# 7. Job Discovery

Use a general web-search approach rather than designing the application around one specific job board.

The system should be capable of discovering jobs from publicly accessible sources such as:

- job boards
- company career pages
- recruitment websites
- search-engine results
- other relevant public job sources

Do not hardcode the system around LinkedIn, Indeed, or any single website.

The search system should support multiple relevant role/title variants.

For example, if the user is interested in entry-level data-related work, the system should be able to find conceptually related titles rather than requiring an exact title match.

Potential role levels include:

- internship
- trainee
- graduate
- entry-level
- junior
- associate
- mid-level
- senior
- lead
- principal
- staff

Strong seniority mismatches should be filtered out.

---

# 8. Job Representation

Each discovered job should contain, where available:

- title
- company
- location
- work arrangement
- description
- requirements
- responsibilities
- qualifications
- salary
- employment type
- seniority
- source
- source URL
- external job ID if available
- discovery timestamp
- relevant metadata

Missing fields must be represented as unknown rather than invented.

The system should normalize job information into a consistent internal representation.

---

# 9. Job Requirements

The system should distinguish between different kinds of requirements.

Examples:

- required/mandatory
- preferred
- useful
- nice-to-have

Where possible, distinguish important/core requirements from secondary requirements.

A missing preferred skill should generally be treated differently from a missing mandatory requirement.

---

# 10. Education Matching

Education requirements should be evaluated sensibly.

If a job explicitly requires a Master's degree and the user's profile only contains a Bachelor's degree:

- normally treat this as a strong mismatch/exclusion.

If a Master's degree is listed as preferred rather than required:

- do not automatically exclude the job
- apply an appropriate penalty

Do not invent equivalent qualifications.

---

# 11. Skill Matching

Skill matching should be based on explicit information in the user profile.

Do not infer that the user knows a technology merely because:

- they have a related degree
- they know another programming language
- they completed an unrelated project
- the technology is commonly associated with their field

Missing skills should generally reduce the fit score rather than automatically eliminate a job.

However, explicitly mandatory/core missing skills should have a substantially larger negative impact and may justify exclusion when appropriate.

---

# 12. Language Matching

Use only explicitly stated language information from the profile.

Do not assume a language based on:

- nationality
- location
- education
- name
- other languages

Language requirements should not become an unnecessary blocker.

If the job's language requirement is unclear, mark it as uncertain rather than guessing.

---

# 13. Work Authorization / Visa

Do not build an elaborate legal or visa-analysis engine.

Work authorization is a secondary/basic eligibility consideration.

Obvious incompatibilities may be excluded or flagged.

For example, a job explicitly requiring authorization that the user's profile does not satisfy may be considered a mismatch.

Ambiguous wording should result in:

- unknown
- needs review

Do not perform legal analysis or make unsupported legal claims.

---

# 14. Fit Evaluation

Every sufficiently analyzed job should receive a transparent fit evaluation.

The score represents:

> How well this job matches the user's known profile and configured preferences.

It does NOT represent:

- probability of getting hired
- probability of receiving an interview
- company hiring likelihood

The evaluation should consider factors such as:

- role relevance
- seniority
- skill match
- required skills
- preferred skills
- education
- experience
- location
- work arrangement
- work authorization/basic eligibility
- missing requirements
- user preferences
- salary when available

Salary should be a relatively modest factor.

Unknown salary should not heavily penalize a job.

Do not introduce a hard salary filter unless explicitly configured later.

---

# 15. Transparent Explanations

The user must be able to understand why a job received its ranking.

For each recommended job, show information such as:

### Strong matches

What the user clearly satisfies.

### Potential gaps

Skills, qualifications, experience, or preferences that are missing or weaker.

### Important concerns

Requirements that may be significant mismatches.

### Overall assessment

A concise explanation of why the job is recommended, borderline, or rejected.

Do not present the score as objective truth.

---

# 16. Filtering

The system should filter obvious strong mismatches.

Examples:

- clearly senior-only role when the user is entry-level
- explicitly required Master's degree when the user has only a Bachelor's
- clearly incompatible location
- clearly incompatible work authorization
- other explicitly incompatible hard requirements

However, do not over-filter jobs simply because the user does not satisfy every listed technology.

A job should generally remain visible when:

- only some skills are missing
- missing skills are preferred rather than mandatory
- the requirement is ambiguous
- the title differs but the underlying role is relevant

---

# 17. Uncertainty

The system should represent uncertainty explicitly.

Possible states include:

- known
- unknown
- uncertain
- needs review

Examples:

- unknown salary
- unclear work arrangement
- ambiguous education requirement
- unclear experience requirement

Uncertainty should affect the explanation and potentially the ranking, but should not be silently converted into a yes/no assumption.

---

# 18. Duplicate Handling

Do NOT implement sophisticated duplicate detection in the MVP.

Basic repetition prevention is sufficient.

For example:

- exact source URL
- exact external job ID when available

can be used to avoid repeatedly storing the exact same job.

Do not spend significant implementation effort on:

- URL canonicalization
- semantic duplicate detection
- company/job-title similarity algorithms
- cross-site duplicate matching

The architecture may leave room for improved duplicate detection later.

---

# 19. Job History

The system should remember jobs it has already discovered.

Store information such as:

- source URL
- discovery date
- last seen date
- status
- whether the user has viewed it
- user decision
- evaluation

This prevents the application from repeatedly presenting the same jobs as if they were new.

---

# 20. User Job Decisions

The user should be able to make decisions about discovered jobs.

At minimum support:

- save/interested
- reject

Rejected jobs should remain in history.

If the user provides a rejection reason, store it.

Potential rejection reasons include:

- too senior
- too far
- missing skills
- salary
- role mismatch
- company
- work arrangement
- other

Do not implement a machine-learning preference system in the MVP.

Persisting these decisions is enough.

---

# 21. Application Tracking

The application must distinguish between job discovery and application state.

Potential application states include:

- discovered
- interested/saved
- rejected by user
- applied
- interview
- offer
- rejected by company
- withdrawn

Do not confuse:

> user rejected this job

with:

> company rejected the user's application

The user should be able to manually update application status.

Store useful information such as:

- application date
- current status
- notes
- relevant job
- timestamps
- optional rejection reason
- other user-entered information

---

# 22. Application Assistance

For a selected job, the application may help the user prepare.

It should be able to:

- analyze the job
- summarize relevant requirements
- identify strengths
- identify gaps
- prepare a tailored CV
- prepare supporting material where appropriate
- create an application checklist
- track progress

The user remains responsible for submitting the application.

---

# 23. Tailored CV Generation

The system should be able to generate a job-specific CV from:

1. the master CV
2. the canonical user profile
3. the selected job

The resulting CV should be truthful.

Allowed:

- reordering sections
- changing emphasis
- shortening irrelevant content
- highlighting relevant projects
- rewriting descriptions while preserving factual meaning
- adapting wording to the job

Not allowed:

- inventing experience
- inventing skills
- inventing achievements
- inventing responsibilities
- claiming the user used a technology they have not explicitly listed
- changing dates
- changing education
- fabricating qualifications

The system should be able to identify which source facts support the tailored CV.

---

# 24. External Data Permissions

The system should have a clear permission mechanism for external actions involving user data.

Before transmitting personal information externally, the user must explicitly approve the specific action.

The system should make clear:

- what data will be sent
- where it will be sent
- why it is needed

No permanent blanket approval should silently authorize future unrelated transmissions.

---

# 25. Privacy

Default behavior:

- user data stays local
- profile stays local
- master CV stays local
- tailored CVs stay local
- application history stays local
- notes stay local

Logs should avoid unnecessarily storing sensitive personal information.

Public job information may be retrieved from the internet.

---

# 26. Persistence

Use a local SQLite database for application/job state unless there is a strong technical reason to choose another local persistence mechanism.

The database should store appropriate entities such as:

- jobs
- job sources
- job requirements
- evaluations
- user decisions
- applications
- CV versions
- audit events

The exact schema and model structure are an implementation decision.

Do not require the user to manually edit the database.

---

# 27. Audit Trail

Maintain a local audit/history of important operations.

Examples:

- search started
- search completed
- job discovered
- job analyzed
- job excluded
- job recommended
- user viewed job
- user saved job
- user rejected job
- CV generated
- application status changed
- external action approved
- errors

Avoid putting unnecessary personal information into audit logs.

---

# 28. CLI

The initial interface should be a CLI.

It should provide functionality equivalent to:

- configure/setup
- search for jobs
- list jobs
- view job details
- view fit analysis
- save a job
- reject a job
- view history
- tailor a CV
- list applications
- update application status

Exact command names and CLI framework are implementation decisions.

The CLI should provide clear errors and useful feedback.

---

# 29. Architecture

Use a clean separation of responsibilities.

At minimum, keep these concerns conceptually separate:

- profile management
- configuration
- web/search
- job extraction
- job normalization
- job analysis
- matching/scoring
- persistence
- CV generation
- application management
- permissions
- audit logging
- CLI

Avoid giant modules that contain unrelated responsibilities.

Avoid unnecessary abstractions.

The architecture should be understandable to a Python developer reading the project for the first time.

---

# 30. Web/Search Architecture

Use a general search strategy initially.

Do not build the MVP around one specific job board.

The system should make it reasonably possible to add better source-specific handling later.

Public job information should be retrieved and normalized into the internal job representation.

The search process should tolerate:

- missing information
- malformed pages
- unavailable pages
- changing page structures
- incomplete job descriptions

A single failed source should not necessarily break the entire search.

---

# 31. Configuration vs Profile

Keep these concepts separate.

### Profile

Facts about the user.

Examples:

- degree
- university
- skills
- projects
- experience
- thesis
- certifications
- languages

### Configuration

How the user wants the job-search system to behave.

Examples:

- preferred roles
- preferred locations
- remote preference
- commute preference
- salary preference
- search terms
- ranking preferences

Do not mix these unnecessarily.

---

# 32. Testing

Automated tests are mandatory.

Tests should cover at least:

### Profile

- valid profile loading
- invalid profile handling
- missing fields
- profile validation

### No-invention behavior

- unsupported skills are not added
- unsupported experience is not added
- unsupported qualifications are not added
- tailored CV does not contain unsupported claims

### Job evaluation

Test cases should include:

- strong junior match
- senior mismatch
- required Master's degree
- preferred Master's degree
- missing mandatory skill
- missing optional skill
- strong skill match
- remote job
- hybrid job
- onsite job
- incompatible location
- obvious work-authorization mismatch
- ambiguous requirement
- unknown information

### Scoring

Test that:

- stronger matches rank appropriately
- major mismatches reduce the score
- missing optional skills do not behave like mandatory failures
- unknown information does not become an invented fact

### Persistence

Test:

- saving jobs
- retrieving jobs
- updating jobs
- saving decisions
- retrieving history
- application tracking
- persistence across program runs

### Application state

Test valid and invalid status transitions where appropriate.

### CV generation

Test:

- truthful tailoring
- preservation of factual information
- no unsupported claims
- job-specific emphasis

### Permissions

Test:

- external personal-data actions require approval
- unapproved actions are blocked
- application submission is always blocked

### Error handling

Test malformed or incomplete:

- jobs
- profiles
- configuration
- web responses
- stored data

---

# 33. Documentation

The project must contain accurate documentation.

## USER_MANUAL.md

Codex must create and maintain a `USER_MANUAL.md`.

It must describe the actual implemented application, not an imagined future version.

It should cover:

- installation
- setup
- profile configuration
- master CV configuration
- search
- viewing jobs
- understanding fit scores
- saving/rejecting jobs
- viewing history
- tailoring CVs
- application tracking
- configuration
- storage
- privacy
- permissions
- troubleshooting

Whenever implementation changes, update the manual if necessary.

## Developer documentation

Also document:

- installation for development
- running tests
- project structure
- architecture
- important design decisions
- development workflow
- relevant implementation notes

---

# 34. Project Structure

Choose the project structure independently based on the requirements above.

Do not copy the architecture of another project merely because it exists.

The structure should be:

- clean
- maintainable
- testable
- understandable
- appropriate for a Python CLI application

The exact modules, packages, classes, functions, and database schema are implementation decisions.

---

# 35. Recommended Development Stages

Implement incrementally.

A sensible progression is:

## Stage 1 — Foundation

Implement:

- Python project setup
- configuration
- user profile
- master CV handling
- local SQLite persistence
- core models
- initial tests

## Stage 2 — Job ingestion

Implement:

- job representation
- web search
- extraction
- normalization
- persistence
- basic repetition prevention

## Stage 3 — Evaluation

Implement:

- requirement extraction
- eligibility checks
- seniority evaluation
- education matching
- skill matching
- location evaluation
- work-authorization/basic eligibility evaluation
- fit scoring
- explanations

## Stage 4 — User workflow

Implement:

- CLI
- job listing
- job details
- fit explanations
- save/reject
- history

## Stage 5 — Application management

Implement:

- application creation
- application status
- notes
- history

## Stage 6 — CV tailoring

Implement:

- job-specific CV generation
- truthful-content validation
- CV version storage

## Stage 7 — Polish

Implement/refine:

- tests
- error handling
- permissions
- audit trail
- documentation
- `USER_MANUAL.md`

The exact order may be adjusted if there is a strong implementation reason.

---

# 36. MVP Definition

The MVP is complete when the user can:

1. Configure their profile.
2. Configure job-search preferences.
3. Run a job search.
4. Receive relevant discovered jobs.
5. See why each job fits or does not fit.
6. See important gaps and mismatches.
7. Save jobs.
8. Reject jobs.
9. Preserve job history.
10. Select a job.
11. Generate a truthful tailored CV.
12. Track the application manually.
13. Keep their personal information local by default.
14. Approve or reject external personal-data actions.
15. Run automated tests successfully.
16. Understand the system through `USER_MANUAL.md`.

---

# 37. Future Features

The architecture may allow future additions such as:

- better duplicate detection
- scheduled searches
- notifications
- preference learning
- additional job sources
- richer CV generation
- browser assistance
- richer application preparation
- additional interfaces
- improved job-source integrations

Do not implement these features in the MVP unless required for the MVP itself.

---

# 38. Implementation Autonomy

Codex should make low-level implementation decisions independently.

Codex should:

1. Inspect the project directory before making changes.
2. Establish a clean project structure.
3. Identify existing files or conflicts.
4. Choose appropriate Python tooling.
5. Implement the architecture incrementally.
6. Write tests alongside implementation.
7. Keep documentation synchronized with the actual implementation.
8. Make reasonable implementation decisions without repeatedly asking the user for low-level choices.

If a decision would materially change one of the non-negotiable requirements, stop and ask the user before proceeding.

Otherwise, use engineering judgment.

---

# 39. User Authority

The user is the owner and final authority.

The system may autonomously:

- search
- retrieve public job information
- analyze jobs
- rank jobs
- store job information
- maintain history
- prepare local CV drafts

The system must not autonomously:

- submit applications
- send personal information externally
- contact recruiters
- contact companies
- create external accounts using personal information
- perform other consequential external actions involving the user's personal data

Those actions require explicit user control, and application submission is never automated.

---

# 40. Final Non-Negotiable Requirements

Before considering the implementation complete, verify all of the following:

1. The system never invents user information.
2. The system never automatically submits applications.
3. Personal information is never sent externally without explicit approval.
4. Passwords are not stored in the MVP.
5. Important uncertainty is never silently guessed.
6. User data remains local by default.
7. Job recommendations include transparent explanations.
8. The MVP remains reasonably simple.
9. Sophisticated duplicate detection is not implemented prematurely.
10. No elaborate visa-analysis system is implemented.
11. `USER_MANUAL.md` accurately reflects the implementation.
12. The user remains in control of consequential actions.
13. Automated tests cover the important behavior.
14. Tailored CVs contain only truthful information supported by the user's profile/master CV.
15. The project remains independent and self-contained.