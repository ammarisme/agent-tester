# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0]

A rework focused on correctness, operability and user experience.

### Added
- **Trials** (`repeats`): run each case several times and report consistency:
  pass^k (every trial passed), pass@k (any trial passed) and flaky cases.
- **Confidence intervals**: Wilson 95% interval on every pass rate.
- **Per-tag breakdown**, latency **histograms** and p95 in all summaries.
- **Clearer outcome classes**: `agent_error`, `transport_error` and
  `config_error` replace the single `error` class, so "the agent failed" is no
  longer confused with "your contract is broken".
- New checks: `not_contains`, `max_latency_ms`. Failure reasons are stored and
  shown for every result.
- **CLI**: `agent-tester run --agent … --dataset …` (no job file needed),
  `--param` overrides, quality gates (`--fail-under`, `--max-error-rate`,
  `--max-p95-ms`), JUnit XML, stable exit codes, `validate` and `schema`
  commands.
- **In-process runner** (default): live progress, results streamed as they
  finish, queueing (`MAX_CONCURRENT_RUNS`), cancellation, and recovery of runs
  interrupted by a restart. No Docker socket required.
- **UI**: onboarding with a one-click demo; structured agent editor with a live
  "Send test request" panel; dataset import with a validated preview and
  line-numbered errors; run report with agent comparison, distributions and a
  trajectory drawer; filters, search, exports (JSON, CSV, JUnit); dark mode;
  responsive layout.
- Optional `API_TOKEN` authentication; uniform error responses.
- OpenAI-compatible and async submit-and-poll contract templates.
- JSON Schemas generated from the models (`shared/schemas`).
- Documentation, CI, contribution and security guides.

### Fixed
- A 4xx response could be classified as `success` when its body happened to
  satisfy the case's expectations.
- A tester crash (bad dataset URL, missing secret) left the run `running` forever.
- `pass_fail_mode` had no effect; it is now `score_expectations` (the old name
  is still accepted).
- Nested paths in poll `done_when` (`result.state == 'done'`) did not work.
- A single-line `{"cases": [...]}` file was read as one case.

### Security
- Templates render in a sandboxed Jinja environment.
- `${VAR}` secrets resolve only in contract text, never in dataset values, and
  resolved values are scrubbed from stored trajectories.
- The controller rejects contracts with literal credentials in auth headers,
  refuses `file://` dataset URIs, and never exposes its own `API_TOKEN` to
  contracts.

### Changed
- The UI proxies `/api/*` to the backend at request time, so one image works in
  any deployment (`NEXT_PUBLIC_API_BASE` is gone; use `API_INTERNAL_URL`).
- The controller image is built from the repository root and runs as a
  non-root user. Data lives in the `agent-tester-data` volume.
- API docs moved to `/api/docs`.
- Existing 0.1 databases are upgraded in place on startup.

## [0.1.0]

Initial prototype.
