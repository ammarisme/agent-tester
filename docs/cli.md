# CLI

`agent-tester` is the evaluation engine as a command-line tool. It uses the same code as the controller, needs no server, and exits with a code that CI can gate on.

## Install

Python 3.10 or later.

```bash
pip install ./tester
agent-tester --version
```

The `tester/` directory also has a Dockerfile whose entrypoint is `agent-tester`:

```bash
docker build -t agent-tester ./tester
docker run --rm -v "$PWD:/work" agent-tester run --agent agent.json --dataset cases.jsonl
```

Inside the Docker Compose project, the `tester` service (profile `cli`) mounts the repository at `/work`, reads `.env`, and can reach the other services by name:

```bash
docker compose run --rm tester run --agent presets/mock-echo.json --dataset datasets/samples/smoke.jsonl
```

## Commands

| Command | Purpose |
| --- | --- |
| [`agent-tester run`](#agent-tester-run) | Evaluate agents against a dataset. |
| [`agent-tester validate`](#agent-tester-validate) | Check agent, dataset or job files without sending requests. |
| [`agent-tester schema`](#agent-tester-schema) | Print the JSON Schema for a file type. |

## `agent-tester run`

```bash
agent-tester run \
  --agent agents/support-bot.json \
  --dataset evals/support.jsonl \
  --repeats 3 \
  --fail-under 0.9 --max-error-rate 0.05 \
  --junit reports/agent-eval.xml
```

Provide either `--job`, or both `--agent` and `--dataset`.

### What to run

| Flag | Description |
| --- | --- |
| `--job PATH\|URL` | A full EvalJob JSON document (agents, dataset, options), such as the controller produces. See `agent-tester schema job`. |
| `--agent PATH` | An agent file (`{name, contract, params}`) or a bare contract. Repeat to compare several agents. The file name (without extension) is used as the id and name when the file has none; two agents with the same id are an error. See [Agent files](agent-contracts.md#agent-files). |
| `--dataset PATH\|URL` | A dataset file or an `http(s)` URL: JSON, JSONL or CSV. `file://` paths are accepted. |
| `--param KEY=VALUE` | Set `agent.params.KEY` on every `--agent`, overriding the file. Repeatable. The value is parsed as JSON when possible (`--param temperature=0.7` is a number, `--param 'stop=["\n"]'` a list); otherwise it is a string. |
| `--run-id ID` | Explicit run id. Default: a random UUID. |

With `--job`, only `--concurrency`, `--repeats` and `--no-score` override the job file; `--param` and `--run-id` apply only to `--agent` runs.

### Evaluation

| Flag | Default | Description |
| --- | --- | --- |
| `--concurrency N` | `8` | Requests in flight at once, across all agents. 1 to 256. |
| `--repeats N` | `1` | Trials per case. 1 to 100. Use 3 or more to measure [consistency](concepts.md#consistency-passk-passk-and-flaky-cases). |
| `--no-score` | off | Ignore `expected`; report outcome classes only. |

### Output

| Flag | Default | Description |
| --- | --- | --- |
| `--out PATH` | | Write the full results JSON (see `agent-tester schema results`). Parent directories are created. |
| `--junit PATH` | | Write JUnit XML for CI test reporting. |
| `--format text\|json` | `text` | Stdout format. `text` prints a per-agent summary; `json` prints one JSON line with `run_id`, `status`, `results` and per-agent `pass_rate` and `error_rate`. |
| `--quiet`, `-q` | off | No progress or text summary. `--format json` output is still printed. |
| `--callback-url URL` | | POST the full results JSON here when done (retried up to 3 times). If the dataset cannot be loaded or the run fails, a result with `status: "failed"` and the error is posted instead. If `AGENT_TESTER_CALLBACK_TOKEN` is set, it is sent as `Authorization: Bearer <token>`. |

The start banner and the progress bar go to stderr. The progress bar is shown only when stderr is a terminal, so CI logs stay clean. Colour is disabled when output is not a terminal or `NO_COLOR` is set.

The text summary shows, per agent: pass rate with its 95% interval, error rate, latency p50/p90/p99/mean, outcome counts, consistency when trials > 1, and up to five non-success results with their reasons, followed by the gate results.

### Quality gates

Gates are checked for **each agent**. Any violated gate makes the command exit with code 1.

| Flag | Fails when |
| --- | --- |
| `--fail-under RATE` | The agent's pass rate is below `RATE` (0 to 1). If nothing was scored (no expectations, or `--no-score`), the success rate is used instead. |
| `--max-error-rate RATE` | The share of results in an error class is above `RATE` (0 to 1). |
| `--max-p95-ms MS` | Latency p95 is above `MS` milliseconds. |

Rates outside 0 to 1 are rejected with exit code 2. See [Concepts](concepts.md) for how each rate is computed. A pass rate from few cases is uncertain; set `--fail-under` with the confidence interval in mind.

### Environment

| Variable | Effect |
| --- | --- |
| Any variable referenced as `${VAR}` or `secret('VAR')` | Supplies secrets to contracts. See [Secrets](agent-contracts.md#secrets). |
| `AGENT_TESTER_SECRET_PATTERN` | Regular expression; if set, contracts can only read variables whose full name matches. |
| `AGENT_TESTER_CALLBACK_TOKEN` | Bearer token for `--callback-url`. Contracts cannot read it. |
| `NO_COLOR` | Disables colour. |

## `agent-tester validate`

Checks files without sending any requests. Each flag is repeatable, and flags can be combined.

```bash
agent-tester validate --agent agents/support-bot.json --dataset evals/support.jsonl
```

| Flag | Checks |
| --- | --- |
| `--agent PATH` | The agent file or bare contract, including JSONPath expressions and poll predicates. |
| `--dataset PATH` | A local dataset file. Every problem is printed with its line number. |
| `--job PATH` | A full EvalJob file. |

Exits 0 if everything is valid and 2 otherwise, or if no flag is given.

## `agent-tester schema`

Prints the JSON Schema for one file type, generated from the same models the runner validates against.

```bash
agent-tester schema contract   # an agent contract
agent-tester schema case       # one dataset case
agent-tester schema job        # a full EvalJob
agent-tester schema results    # the results JSON written by --out
```

Use it for editor validation or to check files in other tooling.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The run completed and all gates passed. `validate`: all files valid. |
| `1` | The run completed, but at least one quality gate failed. |
| `2` | Invalid input: agent, dataset, job or flags, an unreadable or empty dataset, or a gate rate outside 0 to 1. |
| `3` | The run failed, or results could not be delivered to `--callback-url`. |

An agent that errors on every case is not exit code 3: the run itself completed. Use `--max-error-rate` to gate on errors.

## Job files

A job file bundles everything into one document. Options use the same names as the controller's run options:

```json
{
  "agents": [
    {
      "id": "support-bot",
      "name": "Support bot",
      "contract": { "invoke": { "url": "{{ agent.params.base_url }}/v1/chat", "body_template": { "message": "{{ input.message }}" } }, "extract": { "final_text": "$.reply" } },
      "params": { "base_url": "https://staging.example.com" }
    }
  ],
  "dataset": { "uri": "https://example.com/evals/support.jsonl" },
  "options": { "concurrency": 8, "repeats": 3, "score_expectations": true, "body_truncate_chars": 32000 }
}
```

`dataset` takes exactly one of `cases` (an inline list) or `uri`. With `uri`, `headers` can be added for the fetch. `options.body_truncate_chars` (default 32000, minimum 256) truncates stored response bodies; see [Security](security.md#what-the-database-stores).

## Output formats

- **Results JSON** (`--out`): `run_id`, `status`, `case_results` (one per agent, case and trial, with the full trajectory), `summary` (per-agent statistics, see [The summary object](concepts.md#the-summary-object)), `error` and `tester_version`.
- **JUnit XML** (`--junit`): one `<testsuite>` per agent, one `<testcase>` per case and trial (named `<case id> [trial N]` when trials > 1). `failed_assert` results are `<failure>` elements with the failed checks and the final text; error-class results are `<error>` elements whose `type` is the outcome class. Test time is the result latency.

## CI examples

### GitHub Actions

```yaml
name: agent-eval
on: [pull_request]

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ./tester
      - name: Evaluate
        env:
          AGENT_API_KEY: ${{ secrets.AGENT_API_KEY }}
        run: |
          agent-tester run \
            --agent agents/support-bot.json \
            --param base_url=https://staging.example.com \
            --dataset evals/support.jsonl \
            --repeats 3 \
            --fail-under 0.9 --max-error-rate 0.05 --max-p95-ms 8000 \
            --out reports/results.json \
            --junit reports/agent-eval.xml
      - name: Upload reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: agent-eval
          path: reports/
```

To show the JUnit results in the pull request, add a JUnit reporter action of your choice pointed at `reports/agent-eval.xml`.

### GitLab CI

```yaml
agent-eval:
  image: python:3.12-slim
  script:
    - pip install ./tester
    - >
      agent-tester run
      --agent agents/support-bot.json
      --param base_url=https://staging.example.com
      --dataset evals/support.jsonl
      --repeats 3
      --fail-under 0.9 --max-error-rate 0.05
      --out reports/results.json
      --junit reports/agent-eval.xml
  artifacts:
    when: always
    paths:
      - reports/
    reports:
      junit: reports/agent-eval.xml
```

Define `AGENT_API_KEY` as a masked CI/CD variable. GitLab shows the JUnit report in the merge request's test summary.
