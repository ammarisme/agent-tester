# Architecture

## Components

| Component | Location | Role |
| --- | --- | --- |
| **Engine and CLI** | `tester/` (Python package `agent_tester`) | Everything about evaluation: the typed models, templating and secrets, invoking and polling agents, scoring expectations, statistics, JUnit output. Exposed as the `agent-tester` CLI and as a library (`run_job`, `invoke_once`, `parse_cases`). |
| **Controller API** | `controller/backend/` (FastAPI, SQLAlchemy, SQLite) | Stores agents, datasets, runs and results; turns API requests into evaluation jobs; queues and executes runs; serves reports and exports. It imports the engine rather than reimplementing it. |
| **Web UI** | `controller/frontend/` (Next.js) | Browser interface. All API calls go to its own origin at `/api/*`, and a server-side route forwards them to the controller API, adding `API_TOKEN` when configured. |
| **Mock agents** | `mocks/echo_agent.py` (FastAPI) | Echo, flaky and async submit-and-poll agents for the demo and tests. |

The controller API and the UI ship as one container. The engine is shared, so a contract that works in the UI behaves identically in the CLI, and results from either have the same shape.

### Mock agents

| Endpoint | Behaviour |
| --- | --- |
| `GET /health` | `{"status": "ok"}` |
| `POST /v1/chat` | Echoes `message` as `Echo: <message>` with up to `MOCK_JITTER_MS` of random delay. Returns `reply`, `echoed`, `session_id`, `tokens`. |
| `POST /v1/flaky` | Same response shape, with long-tailed latency. Returns HTTP 503 with probability `MOCK_FLAKY_ERROR_RATE`, and a wrong answer (`I'm not sure how to help with that.`) with probability `MOCK_FLAKY_WRONG_RATE`. |
| `POST /v1/jobs` | Accepts `{message}` or `{payload: {message}}` and returns `{id, status: "RUNNING"}`. |
| `GET /v1/jobs/{id}` | Returns `RUNNING` until polled `MOCK_POLLS_UNTIL_DONE` times, then `COMPLETED` with `response: "Async echo: <message>"`. Unknown ids get 404. |

| Variable | Default |
| --- | --- |
| `MOCK_JITTER_MS` | `60` |
| `MOCK_FLAKY_ERROR_RATE` | `0.08` |
| `MOCK_FLAKY_WRONG_RATE` | `0.12` |
| `MOCK_POLLS_UNTIL_DONE` | `2` |

The mock listens on port 9999 in its container. Job state is in memory.

## Life of a run

```
 Browser ──/api──► UI proxy ──► Controller API ──► SQLite
                                   │    ▲
                        submit     │    │ results in batches (~0.5 s)
                                   ▼    │ final summary
                              RunManager (queue: MAX_CONCURRENT_RUNS)
                                   │
                                   ▼
                          engine.run_job ──HTTP──► agents under test
                     (agents × cases × trials,       (invoke, poll)
                      bounded by concurrency)
```

1. **Submit.** `POST /api/runs` validates the options and loads the agents (each must exist, be enabled and have a valid contract) and the dataset. It snapshots the agents' ids and names, builds an `EvalJob`, stores the run as `queued`, and hands the job to the run manager.
2. **Queue.** The run manager starts a background task per run. At most `MAX_CONCURRENT_RUNS` tasks execute at once; the others wait as `queued`. When a slot frees up, the run becomes `running`.
3. **Execute.** In-process, the task calls the engine's `run_job`. It fetches the dataset if it is a URL, then evaluates every (agent, case, trial) combination with at most `concurrency` requests in flight. For each one it renders the request, invokes the agent, polls if the contract says so, extracts fields, scores expectations, and scrubs secrets from the result.
4. **Stream.** `run_job` calls `on_result` after each result. The run manager buffers results and writes them to the database in batches, at most every 0.5 seconds and once more at the end, together with the progress counters. This is what lets the UI show progress and partial results while the run executes.
5. **Summarize.** When all results are in, the engine computes the per-agent summary (rates, Wilson intervals, latency statistics and histogram, consistency, per-tag breakdown). The run is stored as `completed` with the summary.
6. **Cancel or fail.** Cancelling stops the task. Buffered results are flushed, a summary of the results collected so far is stored, and the run becomes `cancelled`. An unexpected exception marks the run `failed` with the error, again keeping partial results. On startup, runs left `queued` or `running` by a previous process are marked `failed`.

With `RUNNER_MODE=docker`, step 3 instead writes the job to a file and runs a tester container with `agent-tester run --job`, which posts the complete results to `POST /api/runs/{id}/results` when done. There is no streaming in that mode. See [Runner modes](deployment.md#runner-modes).

The CLI runs steps 3 and 5 directly, without a controller or database.

## Repository layout

```
agent-tester/
  tester/                  Engine and CLI (Python package agent_tester)
    agent_tester/
      models.py            Typed contract, case, job and results models
      template.py          Sandboxed templating and ${VAR} secrets
      predicate.py         Poll predicate language
      invoke.py            Invoke, poll, extract; outcome classification
      scoring.py           Expectation checks
      stats.py             Aggregates, Wilson intervals, consistency, histograms
      dataset.py           JSON / JSONL / CSV parsing
      redact.py            Header redaction and secret scrubbing
      engine.py            run_job and invoke_once
      report.py            Terminal summary, quality gates, JUnit XML
      cli.py               agent-tester command line
    tests/
  controller/
    backend/app/           FastAPI app: config, api/, services/, db, models
    frontend/              Next.js UI; app/api/[...path]/route.ts is the proxy
    Dockerfile             One image for API and UI (build context: repository root)
    entrypoint.sh          Starts API and UI; exits if either dies
  mocks/                   Mock agents
  presets/                 Contract templates shown under New agent
  datasets/samples/        Sample datasets used by the demo
  shared/schemas/          JSON Schemas exported from the engine models
  docs/                    This documentation
  docker-compose.yml       Default stack: controller + mock-agent (+ tester, profile cli)
  docker-compose.docker-runner.yml   Optional overlay for RUNNER_MODE=docker
  .env.example             Environment template
  Makefile                 Developer tasks (make help)
```

## Design principles

**Distributions over verdicts.** Agents are non-deterministic. A single pass/fail per case hides how often an agent is right, how certain that estimate is, how slow the tail is, and whether it answers consistently. Reports lead with rates and confidence intervals, percentiles, histograms and consistency across trials. Expectations are optional; without them, a run still measures outcome classes and latency.

**Full trajectories.** Every result keeps what happened: the rendered request, the response, every poll step, extracted fields, warnings and errors, with secrets redacted. A number in a report can always be traced back to the requests behind it.

**Outcome classes, not a single error bucket.** A wrong answer, an agent error, a timeout, a network failure and a broken contract need different fixes, so they are counted separately.

**Declarative contracts over adapters.** An agent is described by data (an HTTP contract with templates and JSONPath), not code. Any HTTP endpoint can be evaluated without writing a plugin, and contracts can be reviewed, versioned and copied between environments.

**Typed contracts as the single source of truth.** The Pydantic models in `tester/agent_tester/models.py` define contracts, cases, jobs and results. The controller validates against them, the engine executes them, and `agent-tester schema` exports them as JSON Schema (the copies in `shared/schemas/` are generated this way). There is no second definition to drift out of sync.

**Secrets stay in the environment.** Contracts reference environment variables; resolved values never reach the database.

**One engine for UI and CI.** The controller embeds the same engine as the CLI, so results from an interactive run and a CI gate are directly comparable.
