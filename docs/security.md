# Security

This page describes what Agent Tester protects, what it deliberately does not, and how to deploy it safely. To report a vulnerability, see [SECURITY.md](../SECURITY.md) at the repository root.

## Threat model

### Who can do what

The controller has no user accounts or roles. There are two levels of access:

| Actor | Can |
| --- | --- |
| Anyone who can reach the UI | Everything: create and edit agents, datasets and runs; start runs that send requests anywhere; read every stored result. The UI proxy attaches `API_TOKEN` for them. |
| Anyone with network access to the API port | With `API_TOKEN` set: only `GET /api/health` unless they have the token. Without `API_TOKEN`: everything. |
| Holder of `API_TOKEN` | Everything, including posting results into runs. |
| Author of a contract | Make the runner send HTTP requests to any URL, with any headers and body, and read environment variables of the runner allowed by the secret policy. |
| Author of a dataset | Supply values inserted into requests. Dataset values cannot read secrets or execute templates. |

In practice: **treat access to the UI as administrative access**. Protect it with SSO (see [Running behind SSO](deployment.md#running-behind-sso)), set `API_TOKEN`, and do not expose the API port publicly.

### Server-side request forgery is inherent

The purpose of the runner is to send HTTP requests to URLs chosen by whoever configures an agent. That is server-side request forgery by design, and it cannot be filtered away without breaking the product. It applies to the invoke and poll URLs, to dataset URLs, and to the **Test request** feature.

Consequences and mitigations:

- Anyone who can create an agent can reach any address the runner can reach: internal services, cloud metadata endpoints, admin interfaces. Responses are stored and shown in the UI.
- Run the controller (or, with `RUNNER_MODE=docker`, the tester containers) in a network segment appropriate for that: one that can reach the agents under test and nothing more sensitive. Block cloud metadata addresses (for example `169.254.169.254`) at the network level.
- Restrict who can reach the UI and the API.

### What is not in scope

- Agents under test are trusted to return responses; response bodies are stored and displayed as text, not executed.
- The mock agents are for demos and tests only. Do not expose them.

## Template sandbox

Contract strings are Jinja templates rendered in Jinja's `SandboxedEnvironment`, which blocks access to unsafe attributes and Python internals. Rendering uses `StrictUndefined`, so a reference to a missing value is an error rather than an empty string.

Only the contract's own strings are templates. Values from datasets and responses are inserted as data and never rendered as templates, so a dataset case cannot run template code or call `secret()`.

## Secret handling

Secrets are environment variables of the runner process, referenced from contracts as `${VAR}` or `{{ secret('VAR') }}`. They are never stored in the database as part of a contract. Full syntax: [Secrets](agent-contracts.md#secrets).

- **Denied variables.** `API_TOKEN`, `AGENT_TESTER_CALLBACK_TOKEN` and `DATABASE_URL` can never be read by a contract.
- **Allowlist.** Without `AGENT_TESTER_SECRET_PATTERN`, a contract can read **any other environment variable of the runner**, including cloud credentials or other service tokens present in the controller's environment. In any shared deployment, set a pattern such as `AGENT_TESTER_SECRET_PATTERN='AGENT_[A-Z0-9_]+'` and keep other credentials out of the runner's environment.
- **Dataset values are not expanded.** `${VAR}` inside a case input is sent literally.
- **Header redaction.** Stored trajectories replace the values of credential-like headers (`Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, and any header whose name contains `token`, `secret`, `password`, `api-key`/`api_key`/`apikey` or `session`) with `***`.
- **Value scrubbing.** The resolved value of every variable a contract references, if at least 4 characters long, is replaced with `***` everywhere in the stored result, including URLs, request and response bodies, errors, extracted fields and final text.

Limits of redaction: it covers values the contract referenced and credential-like header names. A secret that the **agent** echoes back that was never referenced by the contract, or a credential in a response header with an unremarkable name, is stored as-is. Response headers are not stored in trajectories, apart from the content type.

### Literal-credential rejection

When an agent is created or updated through the controller, each `invoke` and `poll` header whose name looks like a credential (`Authorization`, `Proxy-Authorization`, `Cookie`, or a name containing `token`, `secret`, `password` or `api-key`) must reference an environment variable or template, optionally after a `Bearer`, `Basic` or `Token` prefix. A literal value is rejected with HTTP 422 and a message pointing at the field.

`ALLOW_LITERAL_SECRETS=true` disables this check. Leave it off: a literal credential saved in a contract is stored in the database, returned by the API and included in exports.

The check covers headers only. It does not detect credentials in URLs, bodies or agent `params`, and a header such as `Authorization: Bearer {{ agent.params.key }}` passes it while storing the key in the database. Keep credentials in environment variables.

## API token

Setting `API_TOKEN` requires `Authorization: Bearer <token>` on every API route except `GET /api/health`. The comparison is constant-time. Without it, the API is open to anyone who can reach port 8000.

With `RUNNER_MODE=docker`, the controller passes the token to tester containers as `AGENT_TESTER_CALLBACK_TOKEN` so they can post results back.

## Dataset files cannot be read from the controller

The controller accepts dataset content only as uploads, inline JSON, or `http(s)` URLs. It rejects any other URL scheme, and the in-process runner refuses file paths, so a user cannot make the controller read a file from its own filesystem as a dataset. (The CLI, which runs with the invoking user's permissions, does accept local paths.)

## What the database stores

The SQLite database contains:

- agent names, descriptions, contracts and params;
- dataset cases (inputs, expectations, tags);
- runs, with a snapshot of the agent names, options and summary statistics;
- every result: input, expectations, final text, extracted fields, metrics, error, and the **trajectory**: request URL, redacted request headers, request body, response status, content type and response body for the invoke call and each poll step.

Response bodies come from the agents under test and **may contain personal data** or other sensitive content, depending on the agent and the dataset. Treat the database, its backups and exported results with the same care as the agents' own logs.

To limit what is stored:

- Lower `body_truncate_chars` in the run options (default 32000 characters per response body, minimum 256). Request bodies are not truncated.
- Delete runs you no longer need (`DELETE /api/runs/{id}`); their results are deleted with them.
- Use datasets without real personal data where possible.

## Hardening checklist

- Put the UI behind SSO or a VPN; never expose it directly.
- Set `API_TOKEN`, and do not publish the API port beyond the networks that need it.
- Set `AGENT_TESTER_SECRET_PATTERN`, and keep unrelated credentials out of the controller's (or tester's) environment.
- Run the controller in a network segment that can reach the agents under test and nothing more sensitive; block cloud metadata addresses.
- Leave `ALLOW_LITERAL_SECRETS` off.
- Prefer the default in-process runner. The Docker runner overlay mounts the Docker socket and runs the controller as root, which gives it control of the Docker host.
- Remove the `mock-agent` service in production.
- Protect the database volume, its backups and exported results as sensitive data, and delete old runs.

## Reporting vulnerabilities

Please do not open a public issue. Follow the process in [SECURITY.md](../SECURITY.md) at the repository root.
