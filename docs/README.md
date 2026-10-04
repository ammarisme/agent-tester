# Agent Tester documentation

Agent Tester runs a dataset of cases against one or more HTTP agents, several times if you like, records every request and response, and reports distributions: outcome rates, pass rates with confidence intervals, latency percentiles and per-case consistency.

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Run the stack with Docker Compose, try the demo, connect your own agent, and run it locally without Docker. |
| [Concepts](concepts.md) | Agents, datasets, runs and trials; the six outcome classes; how every number in a report is computed and how to read it. |
| [Agent contracts](agent-contracts.md) | Full reference for `invoke`, `poll` and `extract`, templating, secrets and the poll predicate language, with examples. |
| [Datasets](datasets.md) | Case format, every expectation check, and the JSON / JSONL / CSV parsing rules. |
| [CLI](cli.md) | `agent-tester run`, `validate` and `schema`: every flag, exit codes, quality gates and CI examples. |
| [REST API](api.md) | Controller endpoints by resource, auth, error and pagination shapes, and a curl walkthrough. |
| [Deployment](deployment.md) | Controller and UI environment variables, runner modes, persistence, scaling and running behind SSO. |
| [Security](security.md) | Threat model, SSRF, template sandboxing, secret handling and what the database stores. |
| [Troubleshooting](troubleshooting.md) | Common symptoms, their causes and fixes. |
| [Architecture](architecture.md) | Components, the life of a run, repository layout and design principles. |

The JSON Schemas for contracts, cases, jobs and results are generated from the code with [`agent-tester schema`](cli.md#agent-tester-schema). The controller serves its OpenAPI description at `/api/docs`.
