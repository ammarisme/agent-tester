# Agent contracts

A contract tells the runner how to call an agent for one case, how to wait for the answer if the agent is asynchronous, and which parts of the response to keep. Contracts are JSON. Unknown keys are rejected, so typos fail validation instead of being ignored.

Print the authoritative JSON Schema with:

```bash
agent-tester schema contract
```

## Agent files

The CLI and the controller both work with an agent made of a name, a contract and params:

```json
{
  "name": "Support bot (staging)",
  "contract": { "invoke": { "url": "{{ agent.params.base_url }}/v1/chat" } },
  "params": { "base_url": "https://staging.example.com" }
}
```

The CLI also accepts a file that contains a bare contract, and an optional `id`. When `id` or `name` is missing, the file name without extension is used. Presets in `presets/` use this format and add `category` and `description`, which the runner ignores.

## Contract reference

A contract has three top-level keys: `invoke` (required), `poll` (optional) and `extract` (optional).

### `invoke`

How to send the request for one case.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | `POST` | HTTP method. |
| `url` | string, required | | Target URL. Templated. |
| `headers` | object of strings | `{}` | Request headers. Values are templated. A value that renders to `null` is sent as an empty string. |
| `body_template` | any JSON | `null` | Request body. Every string inside is templated. Objects and arrays are sent as JSON; a value that renders to a string is sent as-is without a JSON content type; `null` sends no body. |
| `timeout_s` | number, `0 < x ≤ 3600` | `60` | Timeout for this request. Exceeding it yields `timeout`. |

Redirects are followed.

### `poll`

Optional second phase for agents that accept work and finish later. After a successful invoke response, the runner requests `url_template` repeatedly until `done_when` holds, `failed_when` holds, or `timeout_s` runs out.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | `GET` or `POST` | `GET` | HTTP method for each poll. |
| `url_template` | string, required | | Status URL. Templated; typically uses `{{ extracted.<field> }}` from the invoke response. |
| `headers` | object of strings | `{}` | Templated like `invoke.headers`. |
| `body_template` | any JSON | `null` | Templated like `invoke.body_template`. |
| `interval_s` | number, `0.05 ≤ x ≤ 600` | `2` | Wait between polls. |
| `timeout_s` | number, `0 < x ≤ 86400` | `600` | Total time budget for polling, counted from the first poll. |
| `done_when` | predicate, required | | Stop polling with `success` when this holds for a response. See [Poll predicates](#poll-predicates). |
| `failed_when` | predicate or `null` | `status in ['FAILED','ERROR','CANCELLED']` | Stop polling with `agent_error` when this holds. It is checked before `done_when`. Set to `null` to disable. |
| `extract` | object | `{}` | Field name to JSONPath, applied to every 2xx/3xx poll response. |

Poll behaviour in detail:

- Each poll request's timeout is the remaining poll budget, clamped to between 1 and 60 seconds.
- Connection errors and request timeouts during polling are retried until the budget runs out.
- HTTP 5xx and HTTP 408, 425 and 429 responses are retried.
- Any other HTTP 4xx response ends the result immediately with `agent_error`.
- If the next wait would pass the deadline, the result is `timeout`. When a `status` field has been extracted, the error message includes its last value.
- Only the first 200 poll steps are stored in the trajectory; the number omitted is recorded as `poll_steps_omitted`.

### `extract`

An object mapping a field name to a JSONPath expression (as implemented by `jsonpath-ng`). Paths are validated when the contract is saved.

- Top-level `extract` is applied to the invoke response, whatever its status code. `poll.extract` is applied to each successful poll response. Later values overwrite earlier ones.
- The first match is used. A path that matches nothing sets the field to `null` and records a warning such as `invoke extract 'final_text' ($.reply) matched nothing` in the trajectory.
- The path `$` means the whole raw response body as text. It is the only way to extract from a response that is not JSON. Any other path on a non-JSON response yields `null` and a `response is not JSON` warning.
- Extracted fields are available to poll templates as `{{ extracted.<field> }}` and to `jsonpath_equals` checks by bare name.
- **`final_text`** is special: it is the text that `equals`, `contains`, `not_contains` and `regex` check. If it is not a string, it is serialized as JSON. If the contract does not extract `final_text`, the whole raw body of the last response is used.
- Numeric extracted values (not booleans) are added to the result's `metrics` and summarized like latency. See [Metrics](concepts.md#metrics).

## Templating

Every string in `url`, `headers`, `body_template` and `url_template` is a [Jinja](https://jinja.palletsprojects.com/) template.

### Context variables

| Variable | Contents |
| --- | --- |
| `input` | The case's `input`. |
| `expected` | The case's `expected` block (with every check key present; unset checks are `null`), or `null`. |
| `case` | The whole case: `id`, `input`, `expected`, `tags`, plus any extra keys the case carries. |
| `agent.params` | The agent's params. |
| `extracted` | Fields extracted so far. Empty during invoke; filled for poll templates. |
| `trial` | Trial number, starting at 0. |

Functions:

| Function | Returns |
| --- | --- |
| `uuid()` | A new random UUID string, for example for a per-request session id. |
| `now_iso()` | The current UTC time in ISO 8601 format. |
| `secret('NAME')` | The value of environment variable `NAME` on the runner. See [Secrets](#secrets). |

### Types are preserved for single expressions

A string that consists of exactly one expression, optionally surrounded by whitespace, evaluates to the expression's native value instead of a string:

```json
{
  "body_template": {
    "temperature": "{{ agent.params.temperature }}",
    "messages": "{{ input.messages }}",
    "prompt": "Answer briefly: {{ input.message }}"
  }
}
```

With `params.temperature = 0.2`, `temperature` is the number `0.2`, `messages` is whatever array the case holds, and `prompt` is a string. `"body_template": "{{ input }}"` sends the case input itself as the body.

### Rules

- **Undefined is an error.** Rendering uses `StrictUndefined`, so referencing a missing key (for example `{{ input.mesage }}`) fails the result with `config_error` and names the field, rather than silently sending an empty string. Use Jinja's `default` filter for optional values: `{{ input.locale | default('en') }}`.
- **Sandboxed.** Templates run in Jinja's `SandboxedEnvironment`, which blocks access to unsafe Python attributes and internals.
- **No auto-escaping.** Values are inserted as-is.

## Secrets

Credentials never belong in a contract: contracts are stored in the controller database and exported with runs. Reference environment variables of the **runner** process instead.

| Syntax | Where | Effect |
| --- | --- | --- |
| `${NAME}` | Anywhere in contract strings | Replaced with the value of `NAME`. |
| `{{ secret('NAME') }}` | Inside template expressions | Same value, usable in expressions, for example `{{ 'Bearer ' ~ secret('TOKEN') }}`. |
| `$${NAME}` | Contract strings | A literal `${NAME}`, not expanded. |

```json
{ "headers": { "Authorization": "Bearer ${AGENT_API_KEY}" } }
```

Rules:

- **Dataset values are never expanded.** `${...}` is only resolved in the contract's own text. A case input containing `${AGENT_API_KEY}` is sent literally, so a dataset cannot pull secrets out of the runner.
- **Missing variables fail the result.** An unset variable gives `config_error` with `environment variable 'NAME' is not set on the runner`.
- **Internal variables are denied.** `API_TOKEN`, `AGENT_TESTER_CALLBACK_TOKEN` and `DATABASE_URL` can never be read by a contract.
- **Allowlist.** If `AGENT_TESTER_SECRET_PATTERN` is set on the runner, only variable names that fully match that regular expression can be read, for example `AGENT_TESTER_SECRET_PATTERN='AGENT_[A-Z0-9_]+'`. Without it, a contract can read **any** other environment variable of the runner. Set it in shared deployments; see [Security](security.md#secret-handling).
- **Where the runner is.** With the controller's default in-process runner, variables come from the controller's environment (for Docker Compose, the `.env` file). With the CLI, they come from the shell. With `RUNNER_MODE=docker`, they come from the tester container's environment.

What is stored:

- **Header redaction.** In trajectories, the value of any header named `Authorization`, `Proxy-Authorization`, `Cookie` or `Set-Cookie`, or whose name contains `token`, `secret`, `password`, `api-key`/`api_key`/`apikey` or `session` (case-insensitive), is replaced with `***`.
- **Value scrubbing.** The resolved value of every environment variable the contract references (4 characters or longer) is replaced with `***` everywhere in the stored result: URLs, bodies, errors, extracted fields and final text. This covers secrets placed in query strings or bodies.
- **Literal credentials are rejected.** When you create or update an agent through the controller, any `invoke` or `poll` header whose name looks like a credential (`Authorization`, `Proxy-Authorization`, `Cookie`, or names containing `token`, `secret`, `password` or `api-key`) must reference a variable (`${VAR}`) or a template (`{{ ... }}`) after an optional `Bearer`, `Basic` or `Token` prefix. Otherwise the request fails with HTTP 422 and `contract contains a literal credential`. Set `ALLOW_LITERAL_SECRETS=true` on the controller to disable this check. The check applies to headers only; do not put credentials in URLs, bodies or agent params either, since params are stored in the database too.

## Poll predicates

`done_when` and `failed_when` use a small, safe predicate language. There is no `eval`; each predicate is exactly one comparison.

```
<path>                        the value is present and truthy
<path> == <literal>
<path> != <literal>
<path> in [<literal>, ...]
<path> not in [<literal>, ...]
```

- `<path>` is a JSONPath evaluated against the poll response body. A bare name such as `status` means `$.status`; dotted names such as `result.state` work too; full JSONPath such as `$.jobs[0].state` is accepted. The path cannot contain spaces. The first match is used.
- `<literal>` is JSON or a Python literal: `'DONE'`, `"DONE"`, `200`, `true`, `True`, `null`, `['A', 'B']`.
- `in` and `not in` require a list.
- If the path matches nothing (or the body is not JSON), `!=` and `not in` are true and every other form is false.
- Comparison is exact and type-sensitive: `"200"` does not equal `200`.

Examples:

| Predicate | True when |
| --- | --- |
| `status in ['COMPLETED','FAILED']` | `$.status` is `COMPLETED` or `FAILED` |
| `result.state == 'done'` | `$.result.state` is `done` |
| `done` | `$.done` exists and is truthy |
| `$.progress == 100` | `$.progress` is the number 100 |
| `error != null` | `$.error` is missing, or present and not `null` |
| `status not in ['QUEUED','RUNNING']` | `$.status` is missing or any other value |

Invalid predicates are rejected when the contract is validated.

## Examples

### Synchronous agent

One request returns the answer.

```json
{
  "invoke": {
    "method": "POST",
    "url": "{{ agent.params.base_url }}/v1/chat",
    "headers": {
      "Content-Type": "application/json",
      "Authorization": "Bearer ${AGENT_API_KEY}"
    },
    "body_template": {
      "message": "{{ input.message }}",
      "session_id": "{{ uuid() }}"
    },
    "timeout_s": 120
  },
  "extract": {
    "final_text": "$.reply",
    "tokens": "$.usage.total_tokens"
  }
}
```

### Asynchronous agent (submit, then poll)

The invoke response contains a job id; the poll URL uses it. `status` is extracted on both phases so a timeout message can report the last state.

```json
{
  "invoke": {
    "method": "POST",
    "url": "{{ agent.params.base_url }}/v1/jobs",
    "headers": { "Content-Type": "application/json" },
    "body_template": "{{ input }}",
    "timeout_s": 60
  },
  "poll": {
    "method": "GET",
    "url_template": "{{ agent.params.base_url }}/v1/jobs/{{ extracted.job_id }}",
    "interval_s": 1,
    "timeout_s": 300,
    "done_when": "status in ['COMPLETED','SUCCEEDED','FAILED','ERROR','CANCELLED']",
    "failed_when": "status in ['FAILED','ERROR','CANCELLED']",
    "extract": { "final_text": "$.response", "status": "$.status" }
  },
  "extract": { "job_id": "$.id", "status": "$.status" }
}
```

For async agents, `jsonpath_equals` paths starting with `$` are checked against the **last poll response**.

### OpenAI-compatible chat completions

Works with any `/v1/chat/completions` endpoint. Token usage becomes metrics.

```json
{
  "name": "OpenAI-compatible chat completions",
  "contract": {
    "invoke": {
      "method": "POST",
      "url": "{{ agent.params.base_url }}/v1/chat/completions",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer ${AGENT_API_KEY}"
      },
      "body_template": {
        "model": "{{ agent.params.model }}",
        "temperature": "{{ agent.params.temperature }}",
        "messages": [
          { "role": "system", "content": "{{ agent.params.system_prompt }}" },
          { "role": "user", "content": "{{ input.message }}" }
        ]
      },
      "timeout_s": 120
    },
    "extract": {
      "final_text": "$.choices[0].message.content",
      "prompt_tokens": "$.usage.prompt_tokens",
      "completion_tokens": "$.usage.completion_tokens"
    }
  },
  "params": {
    "base_url": "https://llm-gateway.example.com",
    "model": "your-model-id",
    "temperature": 0.2,
    "system_prompt": "You are a helpful assistant."
  }
}
```

### Non-JSON responses

Extract the whole body with `$`:

```json
{ "extract": { "final_text": "$" } }
```

## Bundled presets

The files in `presets/` are the templates offered by **New agent** in the UI:

| File | Purpose |
| --- | --- |
| `sync-http.json` | Generic synchronous agent. |
| `async-http-poll.json` | Submit-and-poll agent; defaults to the mock async agent. |
| `openai-compatible.json` | OpenAI-compatible chat completions. |
| `mock-echo.json` | Demo: deterministic echo agent (`/v1/chat` on the mock). |
| `mock-flaky.json` | Demo: echo with long-tailed latency, wrong answers and 503s (`/v1/flaky`). |

The mock presets default to `base_url` `http://mock-agent:9999`, the Compose service. From the CLI on your machine, override it with `--param base_url=http://localhost:9999`.

## Testing a contract

In the UI, the **Test request** panel of the agent editor sends one real request with the current, unsaved contract and shows the full result. The API equivalent is `POST /api/agents/test` (see [API](api.md#agents)). It gives up after `TEST_REQUEST_TIMEOUT_S` (30 seconds by default) with HTTP 504; full runs use the contract's own timeouts.

From the command line, `agent-tester validate --agent agent.json` checks the file without sending anything.
