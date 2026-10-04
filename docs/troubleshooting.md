# Troubleshooting

Each entry lists the symptom, the cause and the fix. For any failing result, open it in the UI (or `GET /api/runs/{id}/results/{result_id}`) and read `error`, `failures` and the trajectory first: they usually say exactly what went wrong.

## `transport_error` when the agent URL uses `localhost`

**Symptom.** Every result is `transport_error`, with an error such as `All connection attempts failed — hint: inside Docker, localhost is the runner's own container; use the service name or host.docker.internal`.

**Cause.** The runner runs inside the controller container (or a tester container). There, `localhost` and `127.0.0.1` mean the container itself, not your machine.

**Fix.**

- For an agent running in the same Compose project, use its service name, for example `http://mock-agent:9999`.
- For an agent running on your machine, use `http://host.docker.internal:<port>`. The default Compose file maps that name to the Docker host (`extra_hosts: ["host.docker.internal:host-gateway"]`); add the same mapping if you run the controller some other way on Linux. The agent must listen on an interface the container can reach, not only on `127.0.0.1`.
- For anything else, use an address reachable from the container's network.

Use the **Test request** panel to check the URL before running a whole dataset.

## Other `transport_error` results

**Cause.** DNS failure, connection refused, or a TLS error between the runner and the agent.

**Fix.** Check the URL in the trajectory's invoke step (it is the fully rendered URL). Test reachability from where the runner runs. The controller image has Python but no `curl`:

```bash
docker compose exec controller python -c "import urllib.request; print(urllib.request.urlopen('<url>', timeout=5).status)"
```

## `config_error`: environment variable is not set

**Symptom.** `config_error` with `invoke.headers.Authorization: environment variable 'AGENT_API_KEY' is not set on the runner`.

**Cause.** The contract references `${AGENT_API_KEY}` but the runner process does not have it.

**Fix.** Set the variable where the runner runs:

- Docker Compose with the default in-process runner: add it to `.env` and recreate the controller (`docker compose up -d`). Changes to `.env` are not picked up by a running container.
- CLI: export it in the shell or CI job.
- `RUNNER_MODE=docker`: it must be in the tester container's environment.

## `config_error`: variable not allowed by the secret policy

**Symptom.** `environment variable 'NAME' is not allowed by the secret policy`.

**Cause.** Either `NAME` is one of the reserved variables (`API_TOKEN`, `AGENT_TESTER_CALLBACK_TOKEN`, `DATABASE_URL`), or `AGENT_TESTER_SECRET_PATTERN` is set and `NAME` does not fully match it.

**Fix.** Use a differently named variable that matches the pattern.

## `config_error`: template error

**Symptom.** `invoke.body_template.message: template error: 'dict object' has no attribute 'mesage'`, or similar.

**Cause.** A template references a value that does not exist. Missing values are errors, not empty strings.

**Fix.** Correct the name, or give a default: `{{ input.locale | default('en') }}`. The `where` prefix of the message names the field in the contract. For CSV datasets, check how columns map to `input` (see [CSV](datasets.md#csv)).

## Extract warnings: "matched nothing"

**Symptom.** The result shows an extraction warning such as `invoke extract 'final_text' ($.reply) matched nothing`, and `contains` checks fail even though the agent answered correctly.

**Cause.** The JSONPath does not match the response. The field is set to `null`, and `final_text` falls back to nothing (checked as an empty string).

**Fix.** Look at the response body in the trajectory and correct the path, for example `$.choices[0].message.content`. For async agents, remember that the final answer is usually in the poll response, so extract it under `poll.extract`. If the response is not JSON, the warning says `response is not JSON`; use `"$"` to take the whole body.

## Poll timeouts

**Symptom.** Results are `timeout` with `poll did not satisfy done_when within 300s (last status: RUNNING)`.

**Causes and fixes.**

- **The predicate never matches.** Compare `done_when` with the poll responses in the trajectory. Values are case- and type-sensitive: `status == 'done'` does not match `"DONE"`, and `code == 200` does not match `"200"`. Include the terminal failure states in `done_when` too, or rely on `failed_when` to stop on them.
- **The path is wrong.** A bare name means a top-level field. For nested fields use `result.state` or `$.result.state`.
- **The job is slow.** Raise `poll.timeout_s`.
- **The poll URL is wrong.** If `extracted.job_id` is `null` because the invoke extract matched nothing, the poll URL ends in `/None`. Most agents answer that with 404, which ends the result as `agent_error` with `poll returned HTTP 404`.

5xx, 408, 425 and 429 poll responses and connection errors are retried until the budget runs out, so an agent that keeps failing that way also ends as a timeout; the poll steps in the trajectory show the status codes.

## 401 from the API

**Symptom.** `{"detail": "missing or invalid API token"}`.

**Cause.** `API_TOKEN` is set on the controller and the request did not carry `Authorization: Bearer <token>`, or carried a different one.

**Fix.**

- Scripts: send the header. `GET /api/health` is the only route that works without it.
- The UI: the proxy adds the token only if the request has no `Authorization` header. If an SSO proxy in front of the UI forwards its own `Authorization` header, turn that off. Make sure the UI process has the same `API_TOKEN` as the API.

## Run failed after a controller restart

**Symptom.** A run shows `failed` with `The controller restarted before this run finished. Re-run it.`

**Cause.** Runs execute in the controller process. A run that is queued or running when the controller stops cannot resume, so on startup the controller marks it failed. Results written before the restart are kept.

**Fix.** Use **Re-run** (`POST /api/runs/{id}/rerun`). Avoid restarting the controller during long runs, and run a single controller instance per database.

## Run stays `queued`

**Cause.** `MAX_CONCURRENT_RUNS` runs (default 2) are already executing.

**Fix.** Wait, cancel a running run, or raise `MAX_CONCURRENT_RUNS`.

## Dataset import errors

**Symptom.** Import fails with HTTP 422, and the preview lists problems such as `line 7: invalid JSON: Expecting ',' delimiter` or `line 3: unknown check 'contain' in expected (use one of: ...)`.

**Fixes.**

| Message | Fix |
| --- | --- |
| `invalid JSON: ...` on a line | Fix that line. In JSONL, each case must be on one line. |
| `unknown check '<name>' in expected` | Use one of `contains`, `not_contains`, `equals`, `regex`, `jsonpath_equals`, `max_latency_ms`. |
| `duplicate id '<id>' (first seen in case #N)` | Make ids unique, or remove them to get automatic ids. |
| `expected.regex: ... invalid regex` | Fix the regular expression (Python syntax). |
| `expected an object` | Each case must be a JSON object. |
| `N case id(s) already exist` (HTTP 409) | You imported with `mode=append` and some ids are already in the dataset. Use `replace`, or change the ids. |
| `file is larger than 20 MB` (HTTP 413) | Split the file, or raise `MAX_UPLOAD_MB`. |
| `file is not UTF-8 text` (HTTP 400) | Re-save the file as UTF-8. |
| `dataset URI must be http(s)` | The controller accepts only `http://` and `https://` dataset URLs. |

Validate locally before uploading with `agent-tester validate --dataset file.jsonl`.

## Literal credential rejected

**Symptom.** Saving an agent fails with `contract contains a literal credential` and `contract.invoke.headers.Authorization: looks like a literal credential. Reference an environment variable instead, e.g. "Bearer ${AGENT_API_KEY}".`

**Cause.** A credential-like header contains a literal value. Contracts are stored in the database, so the controller refuses to save credentials in them.

**Fix.** Replace the value with `${VAR}` (for example `Bearer ${AGENT_API_KEY}`), set `VAR` in the runner's environment, and restart. If the header is not actually a credential (for example a public tracing token), you can set `ALLOW_LITERAL_SECRETS=true`, which disables the check for all agents; see [Security](security.md#literal-credential-rejection) before doing so.

## UI shows "API unreachable"

**Symptom.** The sidebar shows **API unreachable**, and pages fail with `The UI cannot reach the controller API at http://127.0.0.1:8000. Check that it is running.`

**Cause.** The UI's proxy cannot connect to the API. Either the API process is not running, or `API_INTERNAL_URL` points to the wrong place.

**Fix.**

- Check the controller logs (`docker compose logs controller`). The container exits if the API fails to start, and the log shows why (often a bad environment variable or an unwritable database path).
- Check `GET http://localhost:8000/api/health`.
- If the UI and API run separately, set `API_INTERNAL_URL` on the UI to the API's address.

The same badge appears when the API rejects the UI's requests with 401; see [401 from the API](#401-from-the-api).

## Test request returns 504

**Cause.** The dry run did not finish within `TEST_REQUEST_TIMEOUT_S` (30 seconds by default). This is common for async agents with long polls.

**Fix.** Raise `TEST_REQUEST_TIMEOUT_S`, or start a real run on a one-case dataset; full runs use the contract's own timeouts.
