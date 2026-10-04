# Getting started

This page takes you from a fresh checkout to a report for your own agent. It assumes Docker with the Compose plugin. To run without Docker, see [Local development without Docker](#local-development-without-docker).

## 1. Start the stack

```bash
cp .env.example .env
docker compose up --build
```

The default Compose file starts two services:

| Service | What it is | Default port |
| --- | --- | --- |
| `controller` | The web UI, plus the API behind the UI's proxy at `/api` | UI on `3000`, API on `8000` |
| `mock-agent` | Bundled mock HTTP agents used by the demo | `9999` |

Runs execute inside the controller process by default (the in-process runner), so the default setup needs no Docker socket and no `HOST_PROJECT_DIR`. The database is kept in the named volume `agent-tester-data`, so it survives `docker compose down`. To change the published ports, set `UI_PORT`, `API_PORT` or `MOCK_PORT` in `.env`. [Deployment](deployment.md) covers every setting and the optional Docker runner.

`make up` does the same as `docker compose up --build -d`; `make logs` follows the controller logs and `make down` stops the stack.

Open <http://localhost:3000>. The interactive API documentation is at <http://localhost:3000/api/docs>.

## 2. Run the demo

On the overview page, click **Run the 30-second demo**. This:

1. Creates two agents from the bundled presets, *Mock echo agent* (reliable) and *Mock flaky agent* (long-tailed latency, occasional wrong answers and HTTP 503s).
2. Creates a *Smoke test* dataset with six cases from `datasets/samples/smoke.jsonl`.
3. Starts a run with 3 trials per case, concurrency 8, with expectations checked.

The demo reuses existing agents and datasets with the same names, so clicking it twice does not create duplicates. You land on the run page, which fills in while the run executes. [Reading the report](#6-read-the-report) explains what you see.

## 3. Connect your own agent

1. Go to **Agents** and click **New agent**.
2. Pick a template:
   - **Sync HTTP agent**: one request returns the answer.
   - **Async agent (submit + poll)**: submit a job, then poll a status URL until it reaches a terminal state.
   - **OpenAI-compatible chat completions**: any `/v1/chat/completions` endpoint.
3. Fill in the request (URL, headers, body), the response fields to extract, and the parameters. Put the base URL in a parameter such as `base_url` and reference it as `{{ agent.params.base_url }}`. You can then duplicate the agent and change only the parameter to target another environment.
4. Reference credentials as environment variables, for example `Authorization: Bearer ${AGENT_API_KEY}`, and set `AGENT_API_KEY` in `.env` (then restart the stack). The controller refuses to save a credential-looking header that contains a literal value. See [Secrets](agent-contracts.md#secrets).
5. In the **Test request** panel, enter a case input (for example `{"message": "Hello"}`) and optionally an expectation, then click **Send test request**. You get the full trajectory: the rendered request, the response, extracted fields and the outcome. Nothing is saved.
6. Save the agent.

If the agent runs on your machine rather than in Compose, do not use `localhost` in the URL: inside a container that is the container itself. Use `http://host.docker.internal:<port>` (the default Compose file maps that name to the Docker host) or the Compose service name. See [Troubleshooting](troubleshooting.md#transport_error-when-the-agent-url-uses-localhost).

The full contract format is in [Agent contracts](agent-contracts.md).

## 4. Create a dataset

1. Go to **Datasets** and click **New dataset**.
2. Choose where the cases live:
   - **Store them here**: upload or paste JSONL, JSON or CSV (up to 20 MB by default). The import shows a preview and lists every problem with its line number before anything is saved.
   - **Fetch from a URL at run time**: an `http(s)` URL to a JSONL, JSON or CSV file. It is fetched fresh on every run, so the source of truth can stay in your repository or bucket.

A minimal JSONL dataset:

```jsonl
{"id": "greet", "input": {"message": "Hello"}, "expected": {"contains": ["Hello"]}, "tags": ["smoke"]}
{"id": "refund", "input": {"message": "What is your refund policy?"}, "expected": {"not_contains": ["I'm not sure"]}, "tags": ["support"]}
```

Every field of `input` is available to the contract as `{{ input.<field> }}`. [Datasets](datasets.md) documents all checks and formats.

## 5. Start a run

Go to **Runs**, then **New run** (or use **Run evaluation** from an agent or dataset):

- **Agents**: pick one or more. Several agents are evaluated on identical cases and trials so they can be compared.
- **Dataset**: a saved dataset or a URL.
- **Trials per case**: 1 to 100. Use 3 to 5 to see how consistent answers are.
- **Concurrency**: 1 to 256 requests in flight at once, across all agents in the run.
- **Check expectations**: turn off to measure only reachability and latency.
- **Run name**: optional, for finding the run later.

Click **Start run**. If other runs are already executing, the run waits as `queued` (see [Scaling](deployment.md#scaling)).

## 6. Read the report

The run page shows, per agent:

- **Pass rate** with its 95% confidence interval. When the intervals of two agents overlap, the difference may be noise; add cases or trials.
- **Outcome classes**: how many results were `success`, `failed_assert`, `agent_error`, `timeout`, `transport_error` or `config_error`.
- **Latency**: percentiles and a histogram.
- **Consistency** (when trials > 1): the share of cases that passed on every trial versus on any trial, and which cases are flaky.
- **By tag**: pass rate, error rate and median latency per dataset tag.
- **Results**: every (agent, case, trial) result. Open one to see failed expectations, extraction warnings and the full request/response trajectory.

From the run menu you can download results as JSON, CSV or JUnit XML, re-run with the same setup, cancel an active run, or delete a finished one. [Concepts](concepts.md) explains how each number is computed.

## 7. Evaluate from CI

The same engine is available as a CLI with quality gates and JUnit output:

```bash
pip install ./tester
agent-tester run \
  --agent presets/mock-echo.json \
  --param base_url=http://localhost:9999 \
  --dataset datasets/samples/smoke.jsonl \
  --repeats 3 --fail-under 0.9 --junit reports/agent-eval.xml
```

The same CLI is available inside the Compose project, where the mock agent is reachable by its service name:

```bash
docker compose run --rm tester run --agent presets/mock-echo.json --dataset datasets/samples/smoke.jsonl
```

See [CLI](cli.md).

## Local development without Docker

You need Python 3.10+ and Node.js 20. The Makefile wraps the common tasks; `make help` lists them.

```bash
make setup   # creates .venv, installs the engine, API, mock and UI dependencies
make dev     # mock agent on :9999, API on :8000, UI on :3000, with hot reload
```

`make dev` stores its database in `data/dev.db` and points the demo agents at the local mock (`DEMO_AGENT_URL=http://127.0.0.1:9999`). Other targets:

| Target | What it does |
| --- | --- |
| `make test` | Engine and API tests (`make test-tester`, `make test-api`). |
| `make smoke` | Runs the CLI with both mock presets against the local mock agent, 3 trials. Start `make dev` first. |
| `make lint`, `make fmt` | Lint or auto-format Python (ruff) and lint the UI (eslint). |
| `make typecheck` | Type-check the UI. |
| `make schemas` | Regenerate `shared/schemas/` from the models. |
| `make check` | Lint, type-check and test: everything CI runs. |

### Without make

Install the engine (the controller imports it as the `agent_tester` package) and the other dependencies:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "tester[dev]" -r controller/backend/requirements-dev.txt -r mocks/requirements.txt
```

Start each process in its own terminal:

```bash
# Mock agents on :9999
cd mocks && uvicorn echo_agent:app --port 9999

# API on :8000
cd controller/backend && DEMO_AGENT_URL=http://127.0.0.1:9999 uvicorn app.main:app --port 8000 --reload

# UI on :3000 (its /api proxy forwards to API_INTERNAL_URL, default http://127.0.0.1:8000)
cd controller/frontend && npm ci && npx next dev -p 3000
```

Without `DATABASE_PATH`, the API creates `data/agent_tester.db` in the repository and reads presets and samples from `presets/` and `datasets/samples/`.
