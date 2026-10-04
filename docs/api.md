# REST API

The controller exposes a JSON API under `/api`. The UI uses nothing else, so anything you can do in the UI you can script.

The full, generated OpenAPI description is served at **`/api/docs`** (interactive) and `/api/openapi.json`. This page is an overview.

## Base URL

With the default Docker Compose setup the API is reachable two ways:

- through the UI's same-origin proxy: `http://localhost:3000/api/...`
- directly: `http://localhost:8000/api/...`

The proxy adds the `API_TOKEN` to requests that carry no `Authorization` header (see [Deployment](deployment.md#ui-proxy)). Scripts and CI should call the API directly and send the token themselves.

## Authentication

When the controller has `API_TOKEN` set, every route except `GET /api/health` requires:

```
Authorization: Bearer <token>
```

A missing or wrong token gets HTTP 401 with `{"detail": "missing or invalid API token"}`. When `API_TOKEN` is not set, the API is open. `GET /api/meta` reports whether auth is enabled.

## Errors

Every error response has the same shape:

```json
{
  "detail": "contract is invalid",
  "errors": [
    { "loc": "contract.invoke.url", "message": "Field required" }
  ]
}
```

- `detail` is always present: a one-line summary.
- `errors` is present when there are field-level problems. Each item has a `message` and either `loc` (a dotted path to the field in the request) or, for dataset parsing problems, `line` (a line number in the file, which may be `null`).

| Status | Used for |
| --- | --- |
| 400 | Request not applicable to the resource (for example, importing into a URL dataset), or an upload that is not UTF-8. |
| 401 | Missing or invalid API token. |
| 404 | Agent, dataset, run or result not found. |
| 409 | Conflict: cancelling a run that is not active, deleting an active run, appending cases whose ids already exist. |
| 413 | Upload larger than `MAX_UPLOAD_MB`. |
| 422 | Validation failure: request body, contract, dataset content, run options, or a literal credential in a contract. |
| 502 | A URL dataset could not be fetched. Also returned by the UI proxy when it cannot reach the API. |
| 504 | `POST /api/agents/test` did not finish within `TEST_REQUEST_TIMEOUT_S`. |

## Pagination

List endpoints for runs, run results and dataset cases take `limit` and `offset` query parameters and return:

```json
{ "items": [ ... ], "total": 137, "limit": 50, "offset": 0 }
```

`total` is the number of items matching the filters. The agent and dataset lists are returned as plain arrays.

## Endpoints

### Meta

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness and database check: `{"status": "ok", "version": "..."}`. No auth. |
| `GET` | `/api/meta` | Server capabilities: controller and tester versions, `runner_mode`, `auth_enabled`, `max_concurrent_runs`, `outcome_classes` with descriptions, `allow_literal_secrets`. |
| `GET` | `/api/presets` | Contract templates from the presets directory. |
| `POST` | `/api/demo` | Create the demo agents and dataset, reusing existing ones with the same names. Returns `{agent_ids, dataset_id}`. Does not start a run. |

### Agents

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/agents` | List agents, newest first. |
| `POST` | `/api/agents` | Create an agent: `{name, description?, contract, params?, enabled?}`. Returns 201. |
| `POST` | `/api/agents/test` | Dry-run a possibly unsaved contract against one input: `{contract, params?, input?, expected?}`. Returns one full result, including the trajectory. Nothing is stored. |
| `GET` | `/api/agents/{id}` | Get an agent. |
| `PATCH` | `/api/agents/{id}` | Update any of `name`, `description`, `contract`, `params`, `enabled`. |
| `POST` | `/api/agents/{id}/duplicate` | Copy an agent (named `<name> (copy)`). Returns 201. |
| `DELETE` | `/api/agents/{id}` | Delete an agent. Past runs keep their snapshot of its name. Returns 204. |

Creating or updating an agent validates the contract and, unless `ALLOW_LITERAL_SECRETS` is set, rejects literal credentials in headers (see [Secrets](agent-contracts.md#secrets)). A disabled agent (`enabled: false`) cannot be used in new runs.

### Datasets

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/datasets` | List datasets with `case_count` and `tags`, newest first. |
| `POST` | `/api/datasets` | Create a dataset: `{name, description?, source_type?, uri?, cases?}`. `source_type` is `local` (default) or `uri`; a `uri` dataset needs an `http(s)` `uri`. `cases` is an optional list of case objects, validated like an import. Returns 201. |
| `POST` | `/api/datasets/parse` | Preview how text would import: `{text, filename?}`. Always 200; returns `{format, count, preview, errors}` with up to 20 preview cases. Nothing is saved. |
| `GET` | `/api/datasets/{id}` | Get a dataset. |
| `PATCH` | `/api/datasets/{id}` | Update `name`, `description`, or `uri` (URL datasets only). |
| `DELETE` | `/api/datasets/{id}` | Delete a dataset and its cases. Returns 204. |
| `GET` | `/api/datasets/{id}/cases` | List cases. Query: `q` (substring match on id, input or tags), `limit` (1 to 500, default 50), `offset`. For URL datasets this fetches the URL. |
| `POST` | `/api/datasets/{id}/import` | Upload a file as multipart field `file` (JSON, JSONL or CSV). Query: `mode=replace` (default) or `append`. Returns the updated dataset. |
| `GET` | `/api/datasets/{id}/export` | Download the cases as JSONL. |

### Runs

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/runs` | List runs, newest first. Query: `status`, `q` (matches run name, dataset name or agent name), `limit` (1 to 200, default 50), `offset`. |
| `POST` | `/api/runs` | Start a run. See below. Returns 201 with the run in status `queued`. |
| `GET` | `/api/runs/{id}` | Get a run: status, `progress` (`completed`, `total`), `summary`, `error`, timings. |
| `POST` | `/api/runs/{id}/cancel` | Cancel a queued or running run. Results so far are kept and summarized. 409 if the run is not active. |
| `POST` | `/api/runs/{id}/rerun` | Start a new run with the same agents, dataset and options. Returns 201. |
| `DELETE` | `/api/runs/{id}` | Delete a finished run and its results. 409 while the run is active. Returns 204. |
| `GET` | `/api/runs/{id}/results` | List results without trajectories. Query: `agent_id`, `outcome` (comma-separated classes), `passed` (`true`/`false`), `q` (matches case id, final text, error, failures or tags), `sort` (`case` default, `latency` slowest first, `outcome`), `limit` (1 to 1000, default 100), `offset`. |
| `GET` | `/api/runs/{id}/results/{result_id}` | One result with input, expectations, final text, metrics, extracted fields and trajectory. |
| `GET` | `/api/runs/{id}/export` | Download all results. Query: `format=json` (default; the same shape as the CLI's `--out`), `csv`, or `junit`. |
| `POST` | `/api/runs/{id}/results` | Ingest a complete results document. Used by the Docker runner to report back; not needed otherwise. |

Request body for `POST /api/runs`:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string, optional | Run name. |
| `agent_ids` | list, required | One or more agent ids. Duplicates are ignored. |
| `dataset_id` | string | A saved dataset. |
| `dataset_uri` | string | A one-off `http(s)` dataset URL. Takes precedence over `dataset_id`. |
| `options` | object | `concurrency` (1 to 256, default 8), `repeats` (1 to 100, default 1), `score_expectations` (default `true`), `body_truncate_chars` (at least 256, default 32000). |

Run statuses are `queued`, `running`, `completed`, `failed` and `cancelled`. `progress.total` is known at submit time for stored datasets; for URL datasets it is 0 until the dataset has been fetched and results start arriving.

## Walkthrough with curl

This example uses the bundled mock agent, so it works against a fresh Docker Compose stack. It needs `jq`.

```bash
API=http://localhost:8000/api
AUTH=()   # if API_TOKEN is set: AUTH=(-H "Authorization: Bearer $API_TOKEN")
```

Create an agent:

```bash
AGENT_ID=$(curl -sf "${AUTH[@]}" -X POST "$API/agents" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Echo (curl)",
    "contract": {
      "invoke": {
        "method": "POST",
        "url": "{{ agent.params.base_url }}/v1/chat",
        "headers": {"Content-Type": "application/json"},
        "body_template": {"message": "{{ input.message }}"},
        "timeout_s": 30
      },
      "extract": {"final_text": "$.reply", "tokens": "$.tokens"}
    },
    "params": {"base_url": "http://mock-agent:9999"}
  }' | jq -r .id)
```

Optionally dry-run the contract first:

```bash
curl -sf "${AUTH[@]}" -X POST "$API/agents/test" -H 'Content-Type: application/json' \
  -d "{\"contract\": $(curl -sf "${AUTH[@]}" "$API/agents/$AGENT_ID" | jq .contract),
       \"params\": {\"base_url\": \"http://mock-agent:9999\"},
       \"input\": {\"message\": \"Hello\"},
       \"expected\": {\"contains\": [\"Hello\"]}}" \
  | jq '{outcome_class, passed, final_text, latency_ms}'
```

Create a dataset and import a file into it:

```bash
DATASET_ID=$(curl -sf "${AUTH[@]}" -X POST "$API/datasets" \
  -H 'Content-Type: application/json' \
  -d '{"name": "Smoke (curl)"}' | jq -r .id)

curl -sf "${AUTH[@]}" -X POST "$API/datasets/$DATASET_ID/import?mode=replace" \
  -F "file=@datasets/samples/smoke.jsonl" | jq '{name, case_count, tags}'
```

Start a run with three trials per case:

```bash
RUN_ID=$(curl -sf "${AUTH[@]}" -X POST "$API/runs" \
  -H 'Content-Type: application/json' \
  -d "{\"name\": \"curl demo\", \"agent_ids\": [\"$AGENT_ID\"], \"dataset_id\": \"$DATASET_ID\",
       \"options\": {\"repeats\": 3, \"concurrency\": 8}}" | jq -r .id)
```

Poll until it finishes:

```bash
while :; do
  STATUS=$(curl -sf "${AUTH[@]}" "$API/runs/$RUN_ID" | jq -r .status)
  echo "$STATUS"
  case "$STATUS" in completed|failed|cancelled) break ;; esac
  sleep 2
done
```

Read the summary, then the non-success results:

```bash
curl -sf "${AUTH[@]}" "$API/runs/$RUN_ID" \
  | jq '.summary[] | {agent_name, pass_rate, pass_rate_ci95, error_rate, p95: .scalars.latency_ms.p95}'

curl -sf "${AUTH[@]}" "$API/runs/$RUN_ID/results?outcome=failed_assert,agent_error,timeout,transport_error,config_error" \
  | jq '.items[] | {id, case_id, trial, outcome_class, failures, error}'
```

Fetch one result with its trajectory (replace `42` with an `id` from the list):

```bash
curl -sf "${AUTH[@]}" "$API/runs/$RUN_ID/results/42" | jq .trajectory
```

Export JUnit XML:

```bash
curl -sf "${AUTH[@]}" "$API/runs/$RUN_ID/export?format=junit" -o run.junit.xml
```
